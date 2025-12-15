"""Fetch fresh markets from APIs and find arbitrage opportunities.

This script:
1. Fetches currently active markets DIRECTLY from Kalshi and Polymarket APIs
2. Performs simple text similarity matching (no complex NLP/embeddings)
3. Calculates arbitrage for each match
4. Filters to 2-10% range as requested
5. Outputs trading opportunities
"""

import sys
import os
from typing import List, Dict, Any, Tuple
from difflib import SequenceMatcher

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion.kalshi_client import KalshiClient
from src.ingestion.polymarket_client import PolymarketCLOBClient

print("="*100)
print("FRESH ARBITRAGE OPPORTUNITY FINDER")
print("="*100)
print()

def text_similarity(text1: str, text2: str) -> float:
    """Calculate simple text similarity using SequenceMatcher."""
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def calculate_arbitrage(kalshi_price: float, poly_price: float) -> Tuple[bool, float, str]:
    """Calculate arbitrage between two prices.

    Args:
        kalshi_price: Kalshi Yes price (0-1)
        poly_price: Polymarket Yes price (0-1)

    Returns:
        (has_arb, arb_pct, direction)
    """
    # Arbitrage exists if you can buy both outcomes for < $1 total
    # Buy Yes on cheaper platform, buy No on more expensive platform

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


def main():
    """Main function."""
    print("Step 1: Fetching fresh Kalshi markets...")
    kalshi_client = KalshiClient()

    try:
        kalshi_response = kalshi_client.get_markets(limit=500, status="open")
        kalshi_markets = kalshi_response.get("markets", [])
        print(f"✓ Fetched {len(kalshi_markets)} Kalshi markets")
    except Exception as e:
        print(f"✗ Error fetching Kalshi markets: {e}")
        return

    print()
    print("Step 2: Fetching fresh Polymarket markets...")
    poly_client = PolymarketCLOBClient()

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
    print("Step 3: Finding matches and calculating arbitrage...")
    print()

    opportunities = []
    processed = 0

    for k_market in kalshi_markets:
        processed += 1
        if processed % 100 == 0:
            print(f"  Processed {processed}/{len(kalshi_markets)} Kalshi markets...")

        # Extract Kalshi data
        k_ticker = k_market.get("ticker", "")
        k_title = k_market.get("title", "")

        # Extract price - Kalshi provides yes_bid, yes_ask
        yes_bid = k_market.get("yes_bid", 0)
        yes_ask = k_market.get("yes_ask", 0)

        if not yes_bid or not yes_ask:
            # Try last_price
            last_price = k_market.get("last_price")
            if not last_price:
                continue
            k_price = last_price / 100.0  # Kalshi prices in cents
        else:
            # Use mid price
            k_price = (yes_bid + yes_ask) / 2 / 100.0  # Convert cents to dollars

        # Find similar Polymarket markets
        for p_market in poly_markets:
            p_question = p_market.get("question", "")

            if not p_question:
                continue

            # Calculate text similarity
            similarity = text_similarity(k_title, p_question)

            # Only consider moderate similarity matches (0.50+)
            # Lowered from 0.70 to find more opportunities
            if similarity < 0.50:
                continue

            # Extract Polymarket price (first token assumed to be Yes)
            tokens = p_market.get("tokens", [])
            if not tokens:
                continue

            p_price = tokens[0].get("price")
            if p_price is None:
                continue

            p_price = float(p_price)

            # Calculate arbitrage
            has_arb, arb_pct, direction = calculate_arbitrage(k_price, p_price)

            # COLLECT ALL ARBITRAGE OPPORTUNITIES (not just 2-10%)
            # We'll filter and categorize later
            if has_arb:
                opportunities.append({
                    "kalshi_ticker": k_ticker,
                    "kalshi_title": k_title,
                    "polymarket_question": p_question,
                    "similarity": similarity,
                    "kalshi_price": k_price,
                    "poly_price": p_price,
                    "arbitrage_pct": arb_pct,
                    "direction": direction,
                })

    # Sort by arbitrage percentage (descending)
    opportunities.sort(key=lambda x: x["arbitrage_pct"], reverse=True)

    # Categorize opportunities by percentage ranges
    categories = {
        "0-1%": [o for o in opportunities if o["arbitrage_pct"] < 1.0],
        "1-2%": [o for o in opportunities if 1.0 <= o["arbitrage_pct"] < 2.0],
        "2-5%": [o for o in opportunities if 2.0 <= o["arbitrage_pct"] < 5.0],
        "5-10%": [o for o in opportunities if 5.0 <= o["arbitrage_pct"] < 10.0],
        "10%+": [o for o in opportunities if o["arbitrage_pct"] >= 10.0],
    }

    # TARGET: 2-10% range
    target_opportunities = [o for o in opportunities if 2.0 <= o["arbitrage_pct"] <= 10.0]

    # Display results
    print()
    print("="*100)
    print("ARBITRAGE OPPORTUNITY ANALYSIS")
    print("="*100)
    print()
    print(f"Total opportunities found: {len(opportunities)}")
    print()
    print("Distribution by arbitrage percentage:")
    for range_name, opps in categories.items():
        print(f"  {range_name:<8} : {len(opps):>4} opportunities")
    print()
    print("="*100)
    print(f"TARGET RANGE (2-10%): {len(target_opportunities)} opportunities")
    print("="*100)

    if not target_opportunities:
        print()
        print("No arbitrage opportunities found in the 2-10% target range.")
        print()
        if len(opportunities) > 0:
            print(f"However, {len(opportunities)} total arbitrage opportunities exist outside this range:")
            print(f"  - Below 2%: {len(categories['0-1%']) + len(categories['1-2%'])} opportunities (too small)")
            print(f"  - Above 10%: {len(categories['10%+'])} opportunities (suspicious - check for errors)")
        else:
            print("No arbitrage opportunities found at any percentage level.")
            print()
            print("Possible reasons:")
            print("1. Markets are very efficient (prices closely aligned)")
            print("2. Similarity threshold too high (currently 0.50)")
            print("3. Not enough overlapping markets between platforms")
        print()
    else:
        print()
        print(f"Top {min(20, len(target_opportunities))} opportunities in 2-10% range:")
        print()

        for i, opp in enumerate(target_opportunities[:20], 1):
            print(f"{i}. {opp['arbitrage_pct']:.2f}% arbitrage (similarity: {opp['similarity']:.3f})")
            print(f"   Kalshi:     {opp['kalshi_ticker'][:20]:<20} | {opp['kalshi_title'][:60]}")
            print(f"   Polymarket: {opp['polymarket_question'][:82]}")
            print(f"   Prices:     Kalshi=${opp['kalshi_price']:.3f}, Poly=${opp['poly_price']:.3f}")
            print(f"   Strategy:   {opp['direction']}")
            print()

        print(f"Total in target range: {len(target_opportunities)}")
        print()

    # Show top ALL opportunities regardless of range (for debugging)
    if len(opportunities) > 0 and len(target_opportunities) == 0:
        print("="*100)
        print("ALL ARBITRAGE OPPORTUNITIES (any percentage):")
        print("="*100)
        print()
        for i, opp in enumerate(opportunities[:10], 1):
            print(f"{i}. {opp['arbitrage_pct']:.2f}% arbitrage (similarity: {opp['similarity']:.3f})")
            print(f"   Kalshi:     {opp['kalshi_ticker'][:20]:<20} | {opp['kalshi_title'][:60]}")
            print(f"   Polymarket: {opp['polymarket_question'][:82]}")
            print(f"   Prices:     Kalshi=${opp['kalshi_price']:.3f}, Poly=${opp['poly_price']:.3f}")
            print(f"   Strategy:   {opp['direction']}")
            print()
        print(f"Showing top 10 of {len(opportunities)} total")
        print()

if __name__ == "__main__":
    main()
