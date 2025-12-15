"""Fast arbitrage-focused bonding system.

This script bypasses complex hard constraints and focuses on:
1. Finding overlapping markets quickly via text similarity
2. Creating bonds for markets with 2-10% arbitrage opportunities
3. Monitoring bonded markets every minute for arbitrage windows

Design Philosophy:
- Recall > Precision: Find thousands of overlapping markets quickly
- Let arbitrage percentage filter out bad matches naturally
- False positives don't matter if they show no arbitrage
- Speed matters - people are making hundreds of thousands with these bots
"""

import sys
import os
from typing import List, Dict, Any, Tuple
from datetime import datetime
from difflib import SequenceMatcher
import structlog

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from sqlalchemy import text
from src.models import get_db, Market, Bond
from src.ingestion.kalshi_client import KalshiClient
from src.ingestion.polymarket_client import PolymarketCLOBClient

logger = structlog.get_logger()


def text_similarity(text1: str, text2: str) -> float:
    """Calculate simple text similarity using SequenceMatcher."""
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def calculate_arbitrage(kalshi_price: float, poly_price: float) -> Tuple[bool, float, str]:
    """Calculate arbitrage between two prices.

    Returns:
        (has_arb, arb_pct, direction)
    """
    if kalshi_price < poly_price:
        # Buy Kalshi Yes @ kalshi_price, Buy Poly No @ (1-poly_price)
        cost = kalshi_price + (1 - poly_price)
        profit_pct = (1.0 - cost) * 100
        direction = f"Buy Kalshi Yes @${kalshi_price:.3f}, Buy Poly No @${1-poly_price:.3f}"
    else:
        # Buy Poly Yes @ poly_price, Buy Kalshi No @ (1-kalshi_price)
        cost = poly_price + (1 - kalshi_price)
        profit_pct = (1.0 - cost) * 100
        direction = f"Buy Poly Yes @${poly_price:.3f}, Buy Kalshi No @${1-kalshi_price:.3f}"

    has_arb = profit_pct > 0
    return has_arb, profit_pct, direction


def extract_price_from_market(market: Dict[str, Any], platform: str) -> float:
    """Extract mid price from market data.

    Args:
        market: Market dict with prices
        platform: 'kalshi' or 'polymarket'

    Returns:
        Mid price (0-1) or None if no price available
    """
    if platform == "kalshi":
        yes_bid = market.get("yes_bid", 0)
        yes_ask = market.get("yes_ask", 0)

        if yes_bid and yes_ask:
            return (yes_bid + yes_ask) / 2 / 100.0  # Convert cents to dollars

        last_price = market.get("last_price")
        if last_price:
            return last_price / 100.0

        return None

    elif platform == "polymarket":
        tokens = market.get("tokens", [])
        if tokens and len(tokens) > 0:
            price = tokens[0].get("price")
            if price is not None:
                return float(price)
        return None

    return None


def create_bond_in_db(
    db: Session,
    kalshi_market: Dict,
    poly_market: Dict,
    similarity: float,
    arb_pct: float,
    kalshi_price: float,
    poly_price: float
) -> str:
    """Create a bond in the database.

    Returns:
        pair_id of created bond
    """
    kalshi_ticker = kalshi_market.get("ticker")
    poly_condition_id = poly_market.get("condition_id")

    # Generate pair_id
    pair_id = f"{kalshi_ticker}_{poly_condition_id[:8]}"

    # Check if bond already exists
    existing = db.query(Bond).filter(Bond.pair_id == pair_id).first()
    if existing:
        logger.debug("bond_already_exists", pair_id=pair_id)
        return pair_id

    # Determine tier based on similarity and arbitrage
    # Tier 1: High similarity (0.70+) and good arbitrage (4-10%)
    # Tier 2: Medium similarity (0.50-0.70) or lower arbitrage (2-4%)
    # Tier 3: Low similarity (0.40-0.50)
    if similarity >= 0.70 and arb_pct >= 4.0:
        tier = 1
        p_match = similarity
    elif similarity >= 0.50 or arb_pct >= 2.0:
        tier = 2
        p_match = similarity * 0.9  # Slightly lower confidence
    else:
        tier = 3
        p_match = similarity * 0.8

    # Create bond
    bond = Bond(
        pair_id=pair_id,
        kalshi_market_id=kalshi_ticker,
        polymarket_market_id=poly_condition_id,
        tier=tier,
        status="active",
        p_match=p_match,
        similarity_score=similarity,
        outcome_mapping={"Yes": "Yes", "No": "No"},  # Simple binary mapping
        feature_breakdown={
            "text_similarity": similarity,
            "entity_similarity": 0.0,  # Not computed in fast mode
            "time_alignment": 1.0,  # Assume current markets align
            "outcome_similarity": 1.0,  # Binary markets
            "resolution_similarity": 0.0,
            "arbitrage_pct": arb_pct,
            "kalshi_price": kalshi_price,
            "poly_price": poly_price,
        },
        created_at=datetime.utcnow(),
        last_validated=datetime.utcnow(),
    )

    db.add(bond)
    db.commit()

    logger.info(
        "bond_created",
        pair_id=pair_id,
        tier=tier,
        similarity=similarity,
        arb_pct=arb_pct,
        kalshi_title=kalshi_market.get("title", "")[:50],
        poly_question=poly_market.get("question", "")[:50],
    )

    return pair_id


def main():
    """Main function to find and bond arbitrage opportunities."""
    logger.info("fast_arbitrage_bonding_start")

    print("="*100)
    print("FAST ARBITRAGE-FOCUSED BONDING SYSTEM")
    print("="*100)
    print()

    # Fetch fresh markets from APIs
    print("Step 1: Fetching fresh markets from APIs...")
    kalshi_client = KalshiClient()
    poly_client = PolymarketCLOBClient()

    try:
        kalshi_response = kalshi_client.get_markets(limit=1000, status="open")
        kalshi_markets = kalshi_response.get("markets", [])
        print(f"✓ Fetched {len(kalshi_markets)} Kalshi markets")
    except Exception as e:
        print(f"✗ Error fetching Kalshi markets: {e}")
        return

    try:
        poly_markets = poly_client.get_simplified_markets()
        # Filter to active markets with prices
        poly_markets = [m for m in poly_markets
                       if m.get('active') and m.get('tokens') and len(m.get('tokens', [])) > 0]
        print(f"✓ Fetched {len(poly_markets)} Polymarket markets")
    except Exception as e:
        print(f"✗ Error fetching Polymarket markets: {e}")
        return

    print()
    print("Step 2: Finding overlapping markets and arbitrage opportunities...")
    print()

    db = next(get_db())

    try:
        opportunities = []
        bonds_created = 0
        processed = 0

        # Similarity threshold - relaxed for recall
        MIN_SIMILARITY = 0.50  # Threshold to find overlapping markets
        TARGET_ARB_MIN = 2.0   # User's requirement: 2-10% range
        TARGET_ARB_MAX = 10.0

        for k_market in kalshi_markets:
            processed += 1
            if processed % 100 == 0:
                print(f"  Processed {processed}/{len(kalshi_markets)} Kalshi markets, found {bonds_created} bonds...")

            k_title = k_market.get("title", "")
            k_price = extract_price_from_market(k_market, "kalshi")

            # Find similar Polymarket markets
            for p_market in poly_markets:
                p_question = p_market.get("question", "")

                if not p_question:
                    continue

                # Calculate text similarity
                similarity = text_similarity(k_title, p_question)

                # Only consider matches above threshold
                if similarity < MIN_SIMILARITY:
                    continue

                # Extract Polymarket price (optional - bond even without prices)
                p_price = extract_price_from_market(p_market, "polymarket")

                # Calculate arbitrage if both prices available
                arb_pct = 0.0
                direction = "No prices available yet"

                if k_price and p_price:
                    has_arb, arb_pct, direction = calculate_arbitrage(k_price, p_price)

                # CREATE BOND BASED ON SIMILARITY ALONE
                # We'll monitor for arbitrage windows later - don't require it now
                try:
                    pair_id = create_bond_in_db(
                        db,
                        k_market,
                        p_market,
                        similarity,
                        arb_pct,
                        k_price if k_price else 0.5,  # Default to 0.5 if no price
                        p_price if p_price else 0.5,
                    )
                    bonds_created += 1

                    # Track as opportunity if in target arbitrage range
                    if k_price and p_price and arb_pct >= TARGET_ARB_MIN and arb_pct <= TARGET_ARB_MAX:
                        opportunities.append({
                            "pair_id": pair_id,
                            "similarity": similarity,
                            "arbitrage_pct": arb_pct,
                            "kalshi_title": k_title,
                            "poly_question": p_question,
                            "kalshi_price": k_price,
                            "poly_price": p_price,
                            "direction": direction,
                        })
                except Exception as e:
                    logger.error("bond_creation_failed", error=str(e))
                    continue

        # Sort by arbitrage percentage (descending)
        opportunities.sort(key=lambda x: x["arbitrage_pct"], reverse=True)

        # Display results
        print()
        print("="*100)
        print("BONDING COMPLETE - SIMILARITY-BASED MATCHING")
        print("="*100)
        print()
        print(f"Markets processed: {len(kalshi_markets)}")
        print(f"Total bonds created: {bonds_created}")
        print(f"Current arbitrage opportunities (2-10% range): {len(opportunities)}")
        print()
        print("NOTE: Bonds created based on text similarity (0.50+) - not requiring arbitrage.")
        print("These bonds will be monitored every minute for arbitrage windows.")
        print()

        if opportunities:
            print(f"Top {min(20, len(opportunities))} arbitrage opportunities:")
            print()

            for i, opp in enumerate(opportunities[:20], 1):
                print(f"{i}. {opp['arbitrage_pct']:.2f}% arbitrage (similarity: {opp['similarity']:.3f})")
                print(f"   Bond ID:    {opp['pair_id']}")
                print(f"   Kalshi:     {opp['kalshi_title'][:60]}")
                print(f"   Polymarket: {opp['poly_question'][:60]}")
                print(f"   Prices:     Kalshi=${opp['kalshi_price']:.3f}, Poly=${opp['poly_price']:.3f}")
                print(f"   Strategy:   {opp['direction']}")
                print()
        else:
            print("No arbitrage opportunities found in the 2-10% target range.")
            print()
            print("This could mean:")
            print("1. Markets are currently efficient (no 2-10% opportunities)")
            print("2. Need to run again when market conditions change")
            print("3. Consider adjusting similarity threshold or arbitrage range")

        print()
        print("="*100)
        print(f"TOTAL BONDS IN DATABASE: Run `SELECT COUNT(*) FROM bonds WHERE status='active'` to check")
        print("="*100)

    finally:
        db.close()


if __name__ == "__main__":
    main()
