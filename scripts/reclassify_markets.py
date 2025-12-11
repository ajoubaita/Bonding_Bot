#!/usr/bin/env python3
"""Reclassify all existing markets with updated event classifier.

This script re-runs the event classification on all markets in the database
to apply the improved classification rules (better sports detection, etc.).
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import get_db, Market
from src.normalization.event_classifier import classify_event_type, determine_geo_scope
import structlog

logger = structlog.get_logger()


def reclassify_all_markets(batch_size: int = 1000):
    """Reclassify all markets in the database.

    Args:
        batch_size: Number of markets to process per batch
    """
    db = next(get_db())

    try:
        # Get total count
        total = db.query(Market).count()
        logger.info("reclassification_start", total_markets=total)

        # Process in batches
        offset = 0
        updated = 0
        sports_count = 0
        election_count = 0

        while offset < total:
            markets = db.query(Market).offset(offset).limit(batch_size).all()

            for market in markets:
                # Get entities and title
                entities = market.entities or {}
                title = market.clean_title or market.raw_title or ""
                category = market.category or "unknown"

                # Reclassify
                old_event_type = market.event_type
                new_event_type = classify_event_type(category, entities, title)
                new_geo_scope = determine_geo_scope(entities, title)

                # Update if changed
                if new_event_type != old_event_type or new_geo_scope != market.geo_scope:
                    market.event_type = new_event_type
                    market.geo_scope = new_geo_scope
                    updated += 1

                    if old_event_type != new_event_type:
                        logger.debug(
                            "event_type_changed",
                            market_id=market.id,
                            old=old_event_type,
                            new=new_event_type,
                            title_preview=title[:50],
                        )

                # Track stats
                if new_event_type == "sports":
                    sports_count += 1
                elif new_event_type == "election":
                    election_count += 1

            # Commit batch
            db.commit()

            offset += batch_size
            logger.info(
                "reclassification_progress",
                processed=offset,
                total=total,
                updated=updated,
                sports_count=sports_count,
                election_count=election_count,
            )

        logger.info(
            "reclassification_complete",
            total_processed=total,
            total_updated=updated,
            sports_final=sports_count,
            election_final=election_count,
        )

        print(f"\n{'='*60}")
        print(f"RECLASSIFICATION COMPLETE")
        print(f"{'='*60}")
        print(f"Total processed:     {total:,}")
        print(f"Total updated:       {updated:,}")
        print(f"Sports markets:      {sports_count:,}")
        print(f"Election markets:    {election_count:,}")
        print(f"{'='*60}\n")

    except Exception as e:
        logger.error("reclassification_error", error=str(e))
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Reclassify all markets")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for processing (default: 1000)",
    )

    args = parser.parse_args()

    reclassify_all_markets(batch_size=args.batch_size)
