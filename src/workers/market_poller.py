"""Market polling service for automatic ingestion."""

import time
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
import structlog

from src.config import settings
from src.models import Market, get_db
from src.ingestion.kalshi_client import KalshiClient
from src.ingestion.polymarket_client import PolymarketClient
from src.normalization.pipeline import normalize_market
from src.utils.metrics import record_market_ingestion

logger = structlog.get_logger()


def process_market_worker(args: Tuple[Dict[str, Any], str]) -> Tuple[bool, str, str]:
    """Worker function to process a single market in parallel.

    Args:
        args: Tuple of (raw_market, platform)

    Returns:
        Tuple of (success, platform, market_id)
    """
    raw_market, platform = args

    try:
        # Normalize market (CPU-intensive part)
        normalized = normalize_market(raw_market, platform)
        market_id = normalized["id"]

        # Get database session for this worker
        db = next(get_db())

        try:
            # Check if market exists
            existing = db.query(Market).filter(Market.id == market_id).first()

            if existing:
                # Update existing market
                existing.raw_title = normalized["raw_title"]
                existing.raw_description = normalized["raw_description"]
                existing.clean_title = normalized["clean_title"]
                existing.clean_description = normalized["clean_description"]
                existing.category = normalized["category"]
                existing.event_type = normalized["event_type"]
                existing.entities = normalized["entities"]
                existing.geo_scope = normalized["geo_scope"]
                existing.time_window = normalized["time_window"]
                existing.resolution_source = normalized["resolution_source"]
                existing.outcome_schema = normalized["outcome_schema"]
                existing.text_embedding = normalized["text_embedding"]
                existing.market_metadata = normalized["metadata"]
                existing.updated_at = datetime.utcnow()

                logger.debug("market_updated", platform=platform, market_id=market_id)
            else:
                # Create new market
                new_market = Market(
                    id=normalized["id"],
                    platform=normalized["platform"],
                    condition_id=normalized["condition_id"],
                    status=normalized["status"],
                    raw_title=normalized["raw_title"],
                    raw_description=normalized["raw_description"],
                    clean_title=normalized["clean_title"],
                    clean_description=normalized["clean_description"],
                    category=normalized["category"],
                    event_type=normalized["event_type"],
                    entities=normalized["entities"],
                    geo_scope=normalized["geo_scope"],
                    time_window=normalized["time_window"],
                    resolution_source=normalized["resolution_source"],
                    outcome_schema=normalized["outcome_schema"],
                    text_embedding=normalized["text_embedding"],
                    market_metadata=normalized["metadata"],
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )

                db.add(new_market)
                logger.debug("market_created", platform=platform, market_id=market_id)

            db.commit()
            return (True, platform, market_id)

        finally:
            db.close()

    except Exception as e:
        logger.error(
            "process_market_worker_failed",
            platform=platform,
            market_id=raw_market.get("id", "unknown"),
            error=str(e),
        )
        return (False, platform, raw_market.get("id", "unknown"))


class MarketPoller:
    """Poll external APIs and ingest markets."""

    def __init__(self, num_workers: int = None):
        """Initialize market poller.

        Args:
            num_workers: Number of parallel workers (default: CPU count)
        """
        self.kalshi_client = KalshiClient()
        self.poly_client = PolymarketClient()
        self.running = False
        self.num_workers = num_workers or mp.cpu_count()

        logger.info("market_poller_initialized", num_workers=self.num_workers)

    def ingest_market(self, raw_market: Dict[str, Any], platform: str, db: Session) -> bool:
        """Ingest a single market (legacy serial method).

        Args:
            raw_market: Raw market data from API
            platform: Platform name
            db: Database session

        Returns:
            True if successful
        """
        try:
            # Normalize market
            normalized = normalize_market(raw_market, platform)

            market_id = normalized["id"]

            # Check if market exists
            existing = db.query(Market).filter(Market.id == market_id).first()

            if existing:
                # Update existing market
                existing.raw_title = normalized["raw_title"]
                existing.raw_description = normalized["raw_description"]
                existing.clean_title = normalized["clean_title"]
                existing.clean_description = normalized["clean_description"]
                existing.category = normalized["category"]
                existing.event_type = normalized["event_type"]
                existing.entities = normalized["entities"]
                existing.geo_scope = normalized["geo_scope"]
                existing.time_window = normalized["time_window"]
                existing.resolution_source = normalized["resolution_source"]
                existing.outcome_schema = normalized["outcome_schema"]
                existing.text_embedding = normalized["text_embedding"]
                existing.market_metadata = normalized["metadata"]
                existing.updated_at = datetime.utcnow()

                logger.debug("market_updated", platform=platform, market_id=market_id)
            else:
                # Create new market
                new_market = Market(
                    id=normalized["id"],
                    platform=normalized["platform"],
                    condition_id=normalized["condition_id"],
                    status=normalized["status"],
                    raw_title=normalized["raw_title"],
                    raw_description=normalized["raw_description"],
                    clean_title=normalized["clean_title"],
                    clean_description=normalized["clean_description"],
                    category=normalized["category"],
                    event_type=normalized["event_type"],
                    entities=normalized["entities"],
                    geo_scope=normalized["geo_scope"],
                    time_window=normalized["time_window"],
                    resolution_source=normalized["resolution_source"],
                    outcome_schema=normalized["outcome_schema"],
                    text_embedding=normalized["text_embedding"],
                    market_metadata=normalized["metadata"],
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )

                db.add(new_market)
                logger.debug("market_created", platform=platform, market_id=market_id)

            db.commit()
            record_market_ingestion(platform, success=True)
            return True

        except Exception as e:
            logger.error(
                "ingest_market_failed",
                platform=platform,
                market_id=raw_market.get("id"),
                error=str(e),
            )
            db.rollback()
            record_market_ingestion(platform, success=False)
            return False

    def ingest_markets_parallel(self, markets: List[Dict[str, Any]], platform: str) -> int:
        """Ingest multiple markets in parallel.

        Args:
            markets: List of raw market data
            platform: Platform name

        Returns:
            Number of successfully ingested markets
        """
        if not markets:
            return 0

        logger.info(
            "ingest_markets_parallel_start",
            platform=platform,
            total_markets=len(markets),
            num_workers=self.num_workers,
        )

        start_time = time.time()

        # Prepare arguments for workers
        worker_args = [(market, platform) for market in markets]

        # Process markets in parallel
        with mp.Pool(processes=self.num_workers) as pool:
            results = pool.map(process_market_worker, worker_args)

        # Count successes and record metrics
        success_count = sum(1 for success, _, _ in results if success)
        fail_count = len(results) - success_count

        # Record metrics
        for success, plat, market_id in results:
            record_market_ingestion(plat, success=success)

        duration = time.time() - start_time

        logger.info(
            "ingest_markets_parallel_complete",
            platform=platform,
            total=len(markets),
            success=success_count,
            failed=fail_count,
            duration_seconds=round(duration, 2),
            markets_per_second=round(len(markets) / duration, 2) if duration > 0 else 0,
        )

        return success_count

    def poll_kalshi(self) -> int:
        """Poll Kalshi for new markets with batch processing.

        Returns:
            Number of markets ingested
        """
        logger.info("poll_kalshi_start")

        total_ingested = 0

        def batch_callback(markets_batch, platform):
            """Process each batch as it's fetched."""
            nonlocal total_ingested
            ingested = self.ingest_markets_parallel(markets_batch, platform)
            total_ingested += ingested

        try:
            # Fetch all active markets with batch processing callback
            # Markets are ingested immediately as each page is fetched
            markets = self.kalshi_client.fetch_all_active_markets(
                batch_callback=batch_callback
            )

            logger.info(
                "poll_kalshi_complete",
                total_fetched=len(markets),
                total_ingested=total_ingested,
            )

            return total_ingested

        except Exception as e:
            logger.error("poll_kalshi_failed", error=str(e))
            return total_ingested  # Return what was ingested before error

    def poll_polymarket(self) -> int:
        """Poll Polymarket for new markets with batch processing.

        Returns:
            Number of markets ingested
        """
        logger.info("poll_polymarket_start")

        total_ingested = 0

        def batch_callback(markets_batch, platform):
            """Process each batch as it's fetched."""
            nonlocal total_ingested
            ingested = self.ingest_markets_parallel(markets_batch, platform)
            total_ingested += ingested

        try:
            # Fetch all active markets with batch processing callback
            # Markets are ingested immediately as each page is fetched
            markets = self.poly_client.fetch_all_active_markets_with_prices(
                batch_callback=batch_callback
            )

            logger.info(
                "poll_polymarket_complete",
                total_fetched=len(markets),
                total_ingested=total_ingested,
            )

            return total_ingested

        except Exception as e:
            logger.error("poll_polymarket_failed", error=str(e))
            return total_ingested  # Return what was ingested before error

    def poll_once(self) -> Dict[str, int]:
        """Poll both platforms once in parallel.

        Returns:
            Dictionary with ingestion counts
        """
        logger.info("poll_once_start_parallel")

        start_time = datetime.utcnow()

        # Run both platform polls in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            # Submit both polls to run concurrently
            kalshi_future = executor.submit(self.poll_kalshi)
            poly_future = executor.submit(self.poll_polymarket)

            # Wait for both to complete and get results
            kalshi_count = kalshi_future.result()
            poly_count = poly_future.result()

        duration = (datetime.utcnow() - start_time).total_seconds()

        logger.info(
            "poll_once_complete_parallel",
            kalshi_markets=kalshi_count,
            polymarket_markets=poly_count,
            duration_seconds=duration,
        )

        return {
            "kalshi": kalshi_count,
            "polymarket": poly_count,
            "duration_seconds": duration,
        }

    def run_continuous(self):
        """Run continuous polling loop."""
        logger.info(
            "poll_continuous_start",
            kalshi_interval=settings.kalshi_poll_interval_sec,
            polymarket_interval=settings.polymarket_poll_interval_sec,
        )

        self.running = True

        last_kalshi_poll = 0
        last_poly_poll = 0

        while self.running:
            try:
                current_time = time.time()

                # Check if it's time to poll Kalshi
                if current_time - last_kalshi_poll >= settings.kalshi_poll_interval_sec:
                    self.poll_kalshi()
                    last_kalshi_poll = current_time

                # Check if it's time to poll Polymarket
                if current_time - last_poly_poll >= settings.polymarket_poll_interval_sec:
                    self.poll_polymarket()
                    last_poly_poll = current_time

                # Sleep for 1 second before next check
                time.sleep(1)

            except KeyboardInterrupt:
                logger.info("poll_continuous_interrupted")
                break

            except Exception as e:
                logger.error("poll_continuous_error", error=str(e))
                time.sleep(10)  # Wait before retrying

        self.running = False
        logger.info("poll_continuous_stopped")

    def stop(self):
        """Stop continuous polling."""
        logger.info("poll_continuous_stop_requested")
        self.running = False

    def close(self):
        """Close API clients."""
        self.kalshi_client.close()
        self.poly_client.close()
