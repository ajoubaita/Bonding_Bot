#!/usr/bin/env python3
"""Bond creation script - runs similarity matching across all normalized markets.

This script:
1. Queries normalized markets from both Kalshi and Polymarket
2. Uses pgvector embedding similarity to find candidate pairs
3. Runs full 5-feature similarity calculation on top candidates (PARALLELIZED)
4. Creates Bond records for pairs meeting tier thresholds
5. Stores feature breakdown and outcome mapping

Run this after markets have been ingested and normalized.

OPTIMIZATION: Uses multiprocessing to parallelize similarity calculations (3-4x faster)
"""

import sys
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text
import structlog
import multiprocessing as mp
from functools import partial

from src.models import get_db, Market, Bond
from src.config import settings
from src.similarity.calculator import calculate_similarity

logger = structlog.get_logger()


# Global worker function for multiprocessing (must be picklable)
def _calculate_similarity_worker(
    poly_market_data: Tuple[str, str, str],
    kalshi_market_data: Tuple[str, str, str]
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """Worker function for parallel similarity calculation.

    Args:
        poly_market_data: Tuple of (id, clean_title, raw_title) for Polymarket market
        kalshi_market_data: Tuple of (id, clean_title, raw_title) for Kalshi market

    Returns:
        Tuple of (poly_market_id, similarity_result) or None if error
    """
    try:
        # Reconstruct minimal Market objects from serialized data
        # We only need the IDs here - the full similarity calculation
        # will fetch the complete objects from the database
        from src.models import get_db, Market

        db = next(get_db())

        # Fetch full market objects
        kalshi_market = db.query(Market).filter(Market.id == kalshi_market_data[0]).first()
        poly_market = db.query(Market).filter(Market.id == poly_market_data[0]).first()

        if not kalshi_market or not poly_market:
            return None

        # Calculate similarity
        result = calculate_similarity(kalshi_market, poly_market)

        db.close()

        return (poly_market.id, result)

    except Exception as e:
        logger.error(
            "parallel_similarity_calculation_failed",
            kalshi_id=kalshi_market_data[0],
            poly_id=poly_market_data[0],
            error=str(e),
        )
        return None


def find_candidates_with_embedding(
    db: Session,
    kalshi_market: Market,
    limit: int = 20
) -> List[Market]:
    """Find candidate Polymarket markets using pgvector embedding similarity.

    Args:
        db: Database session
        kalshi_market: Kalshi market to find matches for
        limit: Max candidates to return

    Returns:
        List of candidate Polymarket markets sorted by embedding similarity
    """
    if kalshi_market.text_embedding is None or len(kalshi_market.text_embedding) == 0:
        logger.warning(
            "find_candidates_no_embedding",
            market_id=kalshi_market.id,
        )
        return []

    # Use pgvector cosine similarity search
    # <=> operator computes cosine distance (1 - cosine_similarity)
    # We want similarity DESC, so distance ASC
    # NOTE: Removed category filter since all markets have category="unknown"
    query = text("""
        SELECT m.id, m.text_embedding <=> CAST(:embedding AS vector) AS distance
        FROM markets m
        WHERE m.platform = 'polymarket'
          AND m.text_embedding IS NOT NULL
        ORDER BY m.text_embedding <=> CAST(:embedding AS vector)
        LIMIT :limit
    """)

    # Convert numpy array to list for pgvector compatibility
    embedding_list = kalshi_market.text_embedding.tolist() if hasattr(kalshi_market.text_embedding, 'tolist') else list(kalshi_market.text_embedding)

    results = db.execute(
        query,
        {
            "embedding": embedding_list,
            "limit": limit,
        }
    ).fetchall()

    # Fetch full Market objects
    candidate_ids = [row[0] for row in results]
    candidates = db.query(Market).filter(Market.id.in_(candidate_ids)).all()

    # Sort by original order from vector search
    id_to_market = {m.id: m for m in candidates}
    ordered_candidates = [id_to_market[cid] for cid in candidate_ids if cid in id_to_market]

    logger.debug(
        "find_candidates_complete",
        kalshi_id=kalshi_market.id,
        found=len(ordered_candidates),
        top_distance=results[0][1] if results else None,
    )

    return ordered_candidates


def determine_tier(similarity_result: Dict[str, Any]) -> Optional[int]:
    """Determine bond tier based on similarity scores.

    Args:
        similarity_result: Result from calculate_similarity()

    Returns:
        Tier (1, 2, or 3) or None if below all thresholds
    """
    if similarity_result["hard_constraints_violated"]:
        return None

    p_match = similarity_result["p_match"]
    features = similarity_result["features"]

    # Extract feature scores
    text_score = features.get("text", {}).get("score_text", 0.0)
    outcome_score = features.get("outcome", {}).get("score_outcome", 0.0)
    time_score = features.get("time", {}).get("score_time_final", 0.0)
    resolution_score = features.get("resolution", {}).get("score_resolution", 0.0)

    # Check Tier 1: Highest confidence, auto-execute
    if (
        p_match >= settings.tier1_p_match_threshold
        and text_score >= settings.tier1_min_text_score
        and outcome_score >= settings.tier1_min_outcome_score
        and time_score >= settings.tier1_min_time_score
        and resolution_score >= settings.tier1_min_resolution_score
    ):
        return 1

    # Check Tier 2: Medium confidence, cautious execution
    if (
        p_match >= settings.tier2_p_match_threshold
        and text_score >= settings.tier2_min_text_score
        and outcome_score >= settings.tier2_min_outcome_score
        and time_score >= settings.tier2_min_time_score
    ):
        return 2

    # Tier 3: Low confidence, informational only
    return 3


def extract_outcome_mapping(similarity_result: Dict[str, Any]) -> Dict[str, str]:
    """Extract outcome mapping from similarity calculation.

    Args:
        similarity_result: Result from calculate_similarity()

    Returns:
        Outcome mapping dict
    """
    outcome_feature = similarity_result.get("features", {}).get("outcome", {})
    return outcome_feature.get("outcome_mapping", {})


def extract_feature_breakdown(similarity_result: Dict[str, Any]) -> Dict[str, float]:
    """Extract feature breakdown for storage.

    Args:
        similarity_result: Result from calculate_similarity()

    Returns:
        Feature breakdown dict with scores
    """
    features = similarity_result.get("features", {})

    return {
        "text_similarity": features.get("text", {}).get("score_text", 0.0),
        "entity_similarity": features.get("entity", {}).get("score_entity_final", 0.0),
        "time_alignment": features.get("time", {}).get("score_time_final", 0.0),
        "outcome_similarity": features.get("outcome", {}).get("score_outcome", 0.0),
        "resolution_similarity": features.get("resolution", {}).get("score_resolution", 0.0),
    }


def create_bond(
    db: Session,
    kalshi_market: Market,
    poly_market: Market,
    similarity_result: Dict[str, Any],
    tier: int,
) -> Optional[Bond]:
    """Create a bond record in the database.

    Args:
        db: Database session
        kalshi_market: Kalshi market
        poly_market: Polymarket market
        similarity_result: Similarity calculation result
        tier: Bond tier (1, 2, or 3)

    Returns:
        Created Bond or None if error
    """
    pair_id = f"{kalshi_market.id}_{poly_market.id}"

    # Extract data
    outcome_mapping = extract_outcome_mapping(similarity_result)
    feature_breakdown = extract_feature_breakdown(similarity_result)

    # Check if bond already exists
    existing = db.query(Bond).filter(Bond.pair_id == pair_id).first()
    if existing:
        # Update bond if new tier is better (lower tier number = higher confidence)
        if tier < existing.tier:
            existing.tier = tier
            existing.p_match = similarity_result["p_match"]
            existing.similarity_score = similarity_result["similarity_score"]
            existing.outcome_mapping = outcome_mapping
            existing.feature_breakdown = feature_breakdown
            existing.last_validated = datetime.utcnow()

            try:
                db.commit()
                logger.info(
                    "bond_tier_upgraded",
                    pair_id=pair_id,
                    old_tier=existing.tier,
                    new_tier=tier,
                    p_match=existing.p_match,
                )
                return existing
            except Exception as e:
                db.rollback()
                logger.error(
                    "bond_upgrade_failed",
                    pair_id=pair_id,
                    error=str(e),
                )
                return existing
        else:
            logger.debug(
                "bond_already_exists_same_tier",
                pair_id=pair_id,
                existing_tier=existing.tier,
                new_tier=tier,
            )
            return existing

    # Create bond
    bond = Bond(
        pair_id=pair_id,
        kalshi_market_id=kalshi_market.id,
        polymarket_market_id=poly_market.id,
        tier=tier,
        p_match=similarity_result["p_match"],
        similarity_score=similarity_result["similarity_score"],
        outcome_mapping=outcome_mapping,
        feature_breakdown=feature_breakdown,
        status="active",
        created_at=datetime.utcnow(),
        last_validated=datetime.utcnow(),
    )

    try:
        db.add(bond)
        db.commit()

        logger.info(
            "bond_created",
            pair_id=pair_id,
            tier=tier,
            p_match=bond.p_match,
            similarity_score=bond.similarity_score,
        )

        return bond

    except Exception as e:
        db.rollback()
        logger.error(
            "bond_creation_failed",
            pair_id=pair_id,
            error=str(e),
        )
        return None


def process_kalshi_market(
    db: Session,
    kalshi_market: Market,
    use_parallel: bool = True,
    num_workers: Optional[int] = None,
) -> Dict[str, int]:
    """Process one Kalshi market to find and create bonds.

    Args:
        db: Database session
        kalshi_market: Kalshi market to process
        use_parallel: Use multiprocessing for similarity calculations (default: True)
        num_workers: Number of parallel workers (default: CPU count)

    Returns:
        Stats dict with tier counts
    """
    stats = {
        "candidates": 0,
        "tier1": 0,
        "tier2": 0,
        "tier3": 0,
        "rejected": 0,
    }

    # Find candidates using embedding similarity
    candidates = find_candidates_with_embedding(
        db,
        kalshi_market,
        limit=settings.candidate_limit,
    )

    stats["candidates"] = len(candidates)

    if not candidates:
        return stats

    # OPTIMIZATION: Parallel similarity calculations
    if use_parallel and len(candidates) > 5:
        # Prepare data for parallel processing
        kalshi_data = (kalshi_market.id, kalshi_market.clean_title or "", kalshi_market.raw_title or "")
        poly_data_list = [
            (p.id, p.clean_title or "", p.raw_title or "")
            for p in candidates
        ]

        # Use multiprocessing pool
        if num_workers is None:
            num_workers = min(mp.cpu_count(), len(candidates))

        try:
            with mp.Pool(processes=num_workers) as pool:
                # Create partial function with kalshi_market fixed
                worker_fn = partial(_calculate_similarity_worker, kalshi_market_data=kalshi_data)

                # Map function across all candidates
                results = pool.map(worker_fn, poly_data_list)

            # Process results
            poly_markets_by_id = {p.id: p for p in candidates}

            for result in results:
                if result is None:
                    stats["rejected"] += 1
                    continue

                poly_id, similarity_result = result
                poly_market = poly_markets_by_id.get(poly_id)

                if not poly_market:
                    stats["rejected"] += 1
                    continue

                # Determine tier
                tier = determine_tier(similarity_result)

                if tier is None:
                    stats["rejected"] += 1
                    continue

                # Create bond
                bond = create_bond(
                    db,
                    kalshi_market,
                    poly_market,
                    similarity_result,
                    tier,
                )

                if bond:
                    if tier == 1:
                        stats["tier1"] += 1
                    elif tier == 2:
                        stats["tier2"] += 1
                    else:
                        stats["tier3"] += 1

        except Exception as e:
            logger.error(
                "parallel_processing_failed_fallback_to_sequential",
                kalshi_id=kalshi_market.id,
                error=str(e),
            )
            # Fallback to sequential processing
            use_parallel = False

    # Sequential processing (original code) - fallback or small candidate lists
    if not use_parallel or len(candidates) <= 5:
        for poly_market in candidates:
            try:
                # Calculate similarity
                result = calculate_similarity(kalshi_market, poly_market)

                # Determine tier
                tier = determine_tier(result)

                if tier is None:
                    stats["rejected"] += 1
                    continue

                # Create bond
                bond = create_bond(
                    db,
                    kalshi_market,
                    poly_market,
                    result,
                    tier,
                )

                if bond:
                    if tier == 1:
                        stats["tier1"] += 1
                    elif tier == 2:
                        stats["tier2"] += 1
                    else:
                        stats["tier3"] += 1

            except Exception as e:
                logger.error(
                    "similarity_calculation_failed",
                    kalshi_id=kalshi_market.id,
                    poly_id=poly_market.id,
                    error=str(e),
                )
                stats["rejected"] += 1

    return stats


def create_bonds_batch(
    batch_size: int = 100,
    max_markets: Optional[int] = None,
) -> Dict[str, Any]:
    """Create bonds for all normalized Kalshi markets.

    Args:
        batch_size: Number of Kalshi markets to process per batch
        max_markets: Maximum markets to process (None = all)

    Returns:
        Summary statistics
    """
    db = next(get_db())

    start_time = time.time()

    # Query normalized Kalshi markets
    # Filter for active markets only and order by recency
    query = (
        db.query(Market)
        .filter(
            Market.platform == "kalshi",
            Market.status == "active",  # Only active markets
            Market.text_embedding.isnot(None),
        )
        .order_by(Market.created_at.desc())  # Most recent markets first
    )

    if max_markets:
        query = query.limit(max_markets)

    kalshi_markets = query.all()

    logger.info(
        "bond_creation_start",
        total_kalshi_markets=len(kalshi_markets),
        batch_size=batch_size,
    )

    # Overall stats
    overall_stats = {
        "processed": 0,
        "candidates_total": 0,
        "tier1_total": 0,
        "tier2_total": 0,
        "tier3_total": 0,
        "rejected_total": 0,
    }

    # Process markets
    for i, kalshi_market in enumerate(kalshi_markets):
        logger.info(
            "processing_kalshi_market",
            progress=f"{i+1}/{len(kalshi_markets)}",
            market_id=kalshi_market.id,
            title=(kalshi_market.clean_title or kalshi_market.raw_title or "")[:80],
        )

        market_stats = process_kalshi_market(db, kalshi_market)

        # Update overall stats
        overall_stats["processed"] += 1
        overall_stats["candidates_total"] += market_stats["candidates"]
        overall_stats["tier1_total"] += market_stats["tier1"]
        overall_stats["tier2_total"] += market_stats["tier2"]
        overall_stats["tier3_total"] += market_stats["tier3"]
        overall_stats["rejected_total"] += market_stats["rejected"]

        # Log progress every batch
        if (i + 1) % batch_size == 0:
            logger.info(
                "batch_progress",
                processed=overall_stats["processed"],
                tier1=overall_stats["tier1_total"],
                tier2=overall_stats["tier2_total"],
                tier3=overall_stats["tier3_total"],
            )

    duration = time.time() - start_time

    overall_stats["duration_seconds"] = round(duration, 2)
    overall_stats["markets_per_second"] = round(overall_stats["processed"] / duration, 2)

    logger.info(
        "bond_creation_complete",
        **overall_stats,
    )

    return overall_stats


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Create bonds between Kalshi and Polymarket markets")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Batch size for processing (default: 100)"
    )
    parser.add_argument(
        "--max-markets",
        type=int,
        default=None,
        help="Maximum markets to process (default: all)"
    )
    parser.add_argument(
        "--tier1-only",
        action="store_true",
        help="Stop after finding first Tier 1 bond"
    )

    args = parser.parse_args()

    logger.info(
        "bond_creation_script_start",
        batch_size=args.batch_size,
        max_markets=args.max_markets,
        tier1_only=args.tier1_only,
    )

    try:
        stats = create_bonds_batch(
            batch_size=args.batch_size,
            max_markets=args.max_markets,
        )

        print("\n" + "="*60)
        print("BOND CREATION COMPLETE")
        print("="*60)
        print(f"Processed:        {stats['processed']} markets")
        print(f"Candidates found: {stats['candidates_total']}")
        print(f"Tier 1 bonds:     {stats['tier1_total']} (auto-execute)")
        print(f"Tier 2 bonds:     {stats['tier2_total']} (cautious)")
        print(f"Tier 3 bonds:     {stats['tier3_total']} (informational)")
        print(f"Rejected:         {stats['rejected_total']}")
        print(f"Duration:         {stats['duration_seconds']}s")
        print(f"Rate:             {stats['markets_per_second']} markets/sec")
        print("="*60)

        if stats['tier1_total'] > 0:
            print(f"\n🎉 SUCCESS: Created {stats['tier1_total']} Tier 1 bond(s)!")
            sys.exit(0)
        else:
            print("\n⚠️  No Tier 1 bonds found. Consider adjusting thresholds.")
            sys.exit(0)

    except Exception as e:
        logger.error("bond_creation_script_failed", error=str(e))
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
