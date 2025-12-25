#!/usr/bin/env python3
"""Audit bond quality and identify false positives.

This script reviews Tier 1 and Tier 2 bonds to measure accuracy and help
calibrate thresholds for production use.
"""

import sys
from typing import List, Dict, Tuple
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Database connection
DATABASE_URL = "postgresql://bonding_user:bonding_pass@localhost:5432/bonding_agent"


def get_random_bonds(tier: int, limit: int = 50) -> List[Dict]:
    """Get random sample of bonds for manual review."""
    engine = create_engine(DATABASE_URL)
    Session = sessionmaker(bind=engine)
    session = Session()

    query = text("""
        SELECT
            b.pair_id,
            b.tier,
            b.similarity_score,
            b.p_match,
            b.text_similarity,
            b.entity_similarity,
            b.time_alignment,
            b.outcome_similarity,
            mk.clean_title as kalshi_title,
            mk.raw_title as kalshi_raw,
            mp.clean_title as poly_title,
            mp.raw_title as poly_raw
        FROM bonds b
        JOIN markets mk ON mk.id = b.kalshi_market_id
        JOIN markets mp ON mp.id = b.polymarket_market_id
        WHERE b.tier = :tier AND b.status = 'active'
        ORDER BY RANDOM()
        LIMIT :limit
    """)

    result = session.execute(query, {"tier": tier, "limit": limit})
    bonds = [dict(row._mapping) for row in result]
    session.close()

    return bonds


def analyze_bond_quality(bonds: List[Dict]) -> Dict:
    """Analyze bond quality patterns."""

    # Group by similarity score ranges
    score_ranges = {
        "0.48-0.55": [],
        "0.55-0.65": [],
        "0.65-0.75": [],
        "0.75-0.85": [],
        "0.85+": []
    }

    for bond in bonds:
        score = bond['similarity_score']
        if score < 0.55:
            score_ranges["0.48-0.55"].append(bond)
        elif score < 0.65:
            score_ranges["0.55-0.65"].append(bond)
        elif score < 0.75:
            score_ranges["0.65-0.75"].append(bond)
        elif score < 0.85:
            score_ranges["0.75-0.85"].append(bond)
        else:
            score_ranges["0.85+"].append(bond)

    print("\n" + "=" * 100)
    print(f"BOND QUALITY ANALYSIS - TIER {bonds[0]['tier']} (n={len(bonds)})")
    print("=" * 100)
    print()

    for range_name, range_bonds in score_ranges.items():
        if not range_bonds:
            continue

        print(f"\n{'─' * 100}")
        print(f"SIMILARITY SCORE RANGE: {range_name} (n={len(range_bonds)})")
        print(f"{'─' * 100}")

        for i, bond in enumerate(range_bonds[:10], 1):  # Show max 10 per range
            print(f"\n{i}. Similarity: {bond['similarity_score']:.3f} | p_match: {bond['p_match']:.3f}")
            print(f"   Kalshi:     {bond['kalshi_title']}")
            print(f"   Polymarket: {bond['poly_title']}")
            print(f"   Text: {bond['text_similarity']:.3f} | Entity: {bond['entity_similarity']:.3f} | "
                  f"Time: {bond['time_alignment']:.3f} | Outcome: {bond['outcome_similarity']:.3f}")

            # Basic heuristic checks
            issues = []

            # Check for different team names in sports markets
            kalshi_lower = bond['kalshi_title'].lower()
            poly_lower = bond['poly_title'].lower()

            # Check if market types match
            if ('total' in kalshi_lower or 'o/u' in kalshi_lower or 'over' in kalshi_lower or 'under' in kalshi_lower) != \
               ('total' in poly_lower or 'o/u' in poly_lower or 'over' in poly_lower or 'under' in poly_lower):
                issues.append("⚠️  Market type mismatch (totals vs non-totals)")

            if ('spread' in kalshi_lower) != ('spread' in poly_lower):
                issues.append("⚠️  Market type mismatch (spread vs non-spread)")

            if ('winner' in kalshi_lower) != ('winner' in poly_lower or 'win' in poly_lower):
                issues.append("⚠️  Market type mismatch (winner vs other)")

            # Check for "in a row" / "streak" mismatches
            if ('in a row' in kalshi_lower or 'streak' in kalshi_lower) != \
               ('in a row' in poly_lower or 'streak' in poly_lower):
                issues.append("⚠️  Streak vs total wins mismatch")

            # Check for draw mentions
            if ('draw' in kalshi_lower or 'tie' in kalshi_lower) != \
               ('draw' in poly_lower or 'tie' in poly_lower):
                issues.append("⚠️  Draw/tie outcome mismatch")

            if issues:
                for issue in issues:
                    print(f"   {issue}")

    # Summary statistics
    print("\n" + "=" * 100)
    print("SUMMARY STATISTICS")
    print("=" * 100)

    avg_similarity = sum(b['similarity_score'] for b in bonds) / len(bonds)
    avg_p_match = sum(b['p_match'] for b in bonds) / len(bonds)

    print(f"Average Similarity Score: {avg_similarity:.3f}")
    print(f"Average P_Match:          {avg_p_match:.3f}")
    print()

    for range_name, range_bonds in score_ranges.items():
        if range_bonds:
            pct = (len(range_bonds) / len(bonds)) * 100
            print(f"  {range_name}: {len(range_bonds):3d} bonds ({pct:5.1f}%)")

    print("\n" + "=" * 100)
    print()


def main():
    """Main execution."""
    import argparse

    parser = argparse.ArgumentParser(description="Audit bond quality")
    parser.add_argument("--tier", type=int, default=1, help="Bond tier to audit (1, 2, or 3)")
    parser.add_argument("--limit", type=int, default=50, help="Number of bonds to sample")

    args = parser.parse_args()

    print(f"\nFetching {args.limit} random Tier {args.tier} bonds for audit...\n")

    bonds = get_random_bonds(tier=args.tier, limit=args.limit)

    if not bonds:
        print(f"No Tier {args.tier} bonds found!")
        return

    analyze_bond_quality(bonds)


if __name__ == "__main__":
    main()
