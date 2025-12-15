"""Find tradeable arbitrage opportunities in the 2-10% range.

This script:
1. Fetches currently active markets from both Kalshi and Polymarket (with prices)
2. Performs vector similarity search to find matching markets
3. Calculates arbitrage for each potential match
4. Filters to show ONLY opportunities in the 2-10% range
5. Outputs a tradeable opportunities report
"""

import sys
import os
from typing import List, Dict, Any, Tuple
import structlog

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from sqlalchemy import text
from src.models import get_db, Market
from src.config import settings

logger = structlog.get_logger()


def get_markets_with_prices(db: Session, platform: str, limit: int = 1000) -> List[Market]:
    """Get markets with valid price data.

    Args:
        db: Database session
        platform: Platform name (kalshi or polymarket)
        limit: Maximum markets to fetch

    Returns:
        List of markets with prices in outcome_schema
    """
    # Query markets that have outcome_schema with prices
    query = text("""
        SELECT id, platform, clean_title, raw_title, outcome_schema, text_embedding
        FROM markets
        WHERE platform = :platform
          AND status = 'active'
          AND outcome_schema IS NOT NULL
          AND outcome_schema::jsonb->'outcomes' IS NOT NULL
          AND jsonb_array_length((outcome_schema::jsonb->'outcomes')::jsonb) > 0
        LIMIT :limit
    """)

    results = db.execute(query, {"platform": platform, "limit": limit})

    markets = []
    for row in results:
        # Check if at least one outcome has a price
        outcomes = row.outcome_schema.get("outcomes", [])
        has_price = any(o.get("price") is not None for o in outcomes)

        if has_price:
            market = Market(
                id=row.id,
                platform=row.platform,
                clean_title=row.clean_title,
                raw_title=row.raw_title,
                outcome_schema=row.outcome_schema,
                text_embedding=row.text_embedding,
            )
            markets.append(market)

    return markets


def calculate_simple_arbitrage(kalshi_market: Market, poly_market: Market) -> Tuple[bool, float, str, Dict]:
    """Calculate arbitrage opportunity between two markets.

    Args:
        kalshi_market: Kalshi market
        poly_market: Polymarket market

    Returns:
        Tuple of (has_arb, arb_pct, explanation, details)
    """
    kalshi_outcomes = kalshi_market.outcome_schema.get("outcomes", [])
    poly_outcomes = poly_market.outcome_schema.get("outcomes", [])

    # Find Yes outcomes
    kalshi_yes = next((o for o in kalshi_outcomes if o.get("value") is True), None)
    poly_yes = next((o for o in poly_outcomes if o.get("value") is True), None)

    if not kalshi_yes or not poly_yes:
        return False, 0.0, "No Yes outcomes found", {}

    kalshi_price = kalshi_yes.get("price")
    poly_price = poly_yes.get("price")

    if kalshi_price is None or poly_price is None:
        return False, 0.0, "Missing price data", {}

    # Calculate arbitrage both directions
    # Direction 1: Buy Kalshi, Sell Polymarket
    arb1 = (1.0 - kalshi_price - poly_price) * 100  # Profit % if buy K@kalshi_price, sell P@poly_price

    # Direction 2: Buy Polymarket, Sell Kalshi
    arb2 = (1.0 - poly_price - kalshi_price) * 100  # Same calculation (symmetric)

    # Take the profitable direction
    if arb1 > 0:
        return True, arb1, f"Buy Kalshi @ {kalshi_price:.3f}, Sell Poly @ {poly_price:.3f}", {
            "kalshi_price": kalshi_price,
            "poly_price": poly_price,
            "direction": "Buy Kalshi, Sell Poly",
        }
    elif arb2 > 0:
        return True, arb2, f"Buy Poly @ {poly_price:.3f}, Sell Kalshi @ {kalshi_price:.3f}", {
            "kalshi_price": kalshi_price,
            "poly_price": poly_price,
            "direction": "Buy Poly, Sell Kalshi",
        }
    else:
        return False, max(arb1, arb2), "No arbitrage (prices sum > 1.0)", {
            "kalshi_price": kalshi_price,
            "poly_price": poly_price,
        }


def find_similar_markets(db: Session, kalshi_market: Market, poly_markets: List[Market], top_k: int = 10) -> List[Tuple[Market, float]]:
    """Find similar Polymarket markets using vector similarity.

    Args:
        db: Database session
        kalshi_market: Kalshi market to match
        poly_markets: List of Polymarket markets
        top_k: Number of top matches to return

    Returns:
        List of (poly_market, similarity_score) tuples
    """
    if not kalshi_market.text_embedding:
        return []

    # Get Polymarket market IDs
    poly_ids = [m.id for m in poly_markets]

    if not poly_ids:
        return []

    # Vector similarity query
    # Use cosine similarity: 1 - (embedding <=> kalshi_embedding)
    embedding_str = f"[{','.join(map(str, kalshi_market.text_embedding))}]"

    query = text(f"""
        SELECT id, 1 - (text_embedding <=> '{embedding_str}'::vector) AS similarity
        FROM markets
        WHERE id = ANY(:poly_ids)
        ORDER BY text_embedding <=> '{embedding_str}'::vector
        LIMIT :top_k
    """)

    results = db.execute(query, {"poly_ids": poly_ids, "top_k": top_k})

    # Map results back to Market objects
    id_to_market = {m.id: m for m in poly_markets}
    matches = []
    for row in results:
        if row.id in id_to_market:
            matches.append((id_to_market[row.id], row.similarity))

    return matches


def main():
    """Main function to find arbitrage opportunities."""
    logger.info("arbitrage_search_start")

    db = next(get_db())

    try:
        # Fetch markets with prices
        logger.info("fetching_kalshi_markets")
        kalshi_markets = get_markets_with_prices(db, "kalshi", limit=500)
        logger.info("kalshi_markets_fetched", count=len(kalshi_markets))

        logger.info("fetching_polymarket_markets")
        poly_markets = get_markets_with_prices(db, "polymarket", limit=1000)
        logger.info("polymarket_markets_fetched", count=len(poly_markets))

        if not kalshi_markets:
            logger.error("no_kalshi_markets_with_prices")
            print("ERROR: No Kalshi markets with prices found")
            return

        if not poly_markets:
            logger.error("no_polymarket_markets_with_prices")
            print("ERROR: No Polymarket markets with prices found")
            return

        # Find arbitrage opportunities
        opportunities = []

        for i, k_market in enumerate(kalshi_markets):
            if (i + 1) % 50 == 0:
                logger.info("progress", processed=i+1, total=len(kalshi_markets))

            # Find similar Polymarket markets
            similar = find_similar_markets(db, k_market, poly_markets, top_k=5)

            for p_market, similarity in similar:
                # Only consider high similarity matches
                if similarity < 0.70:
                    continue

                # Calculate arbitrage
                has_arb, arb_pct, explanation, details = calculate_simple_arbitrage(k_market, p_market)

                # Filter to 2-10% range as requested
                if has_arb and 2.0 <= arb_pct <= 10.0:
                    opportunities.append({
                        "kalshi_id": k_market.id,
                        "kalshi_title": k_market.clean_title or k_market.raw_title,
                        "poly_id": p_market.id,
                        "poly_title": p_market.clean_title or p_market.raw_title,
                        "similarity": similarity,
                        "arbitrage_pct": arb_pct,
                        "explanation": explanation,
                        "kalshi_price": details.get("kalshi_price"),
                        "poly_price": details.get("poly_price"),
                        "direction": details.get("direction"),
                    })

        # Sort by arbitrage percentage (descending)
        opportunities.sort(key=lambda x: x["arbitrage_pct"], reverse=True)

        # Display results
        print("\n" + "="*100)
        print(f"ARBITRAGE OPPORTUNITIES (2-10% range)")
        print("="*100)
        print(f"Total opportunities found: {len(opportunities)}")
        print("="*100)

        if not opportunities:
            print("\nNo arbitrage opportunities found in the 2-10% range.")
            print("\nPossible reasons:")
            print("1. Markets are efficient (prices aligned)")
            print("2. Not enough markets with current price data")
            print("3. Similarity threshold too high")
        else:
            print(f"\nTop {min(20, len(opportunities))} opportunities:\n")

            for i, opp in enumerate(opportunities[:20], 1):
                print(f"{i}. {opp['arbitrage_pct']:.2f}% arbitrage (similarity: {opp['similarity']:.3f})")
                print(f"   Kalshi:     {opp['kalshi_id'][:30]:<30} | {opp['kalshi_title'][:50]}")
                print(f"   Polymarket: {opp['poly_id'][:30]:<30} | {opp['poly_title'][:50]}")
                print(f"   Prices:     Kalshi=${opp['kalshi_price']:.3f}, Poly=${opp['poly_price']:.3f}")
                print(f"   Direction:  {opp['direction']}")
                print()

        logger.info("arbitrage_search_complete", opportunities=len(opportunities))

    finally:
        db.close()


if __name__ == "__main__":
    main()
