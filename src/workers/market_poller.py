"""Market polling service for automatic ingestion."""

import time
from typing import List, Dict, Any
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


class MarketPoller:
    """Poll external APIs and ingest markets."""

    def __init__(self):
        """Initialize market poller."""
        self.kalshi_client = KalshiClient()
        self.poly_client = PolymarketClient()
        self.running = False

    def ingest_market(self, raw_market: Dict[str, Any], platform: str, db: Session) -> bool:
        """Ingest a single market.

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
                existing.metadata = normalized["metadata"]
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
                    metadata=normalized["metadata"],
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

    def poll_kalshi(self) -> int:
        """Poll Kalshi for new markets.

        Returns:
            Number of markets ingested
        """
        logger.info("poll_kalshi_start")

        try:
            # Fetch all active markets
            markets = self.kalshi_client.fetch_all_active_markets()

            logger.info("poll_kalshi_fetched", count=len(markets))

            # Ingest each market
            db = next(get_db())
            ingested = 0

            try:
                for market in markets:
                    if self.ingest_market(market, "kalshi", db):
                        ingested += 1

                logger.info("poll_kalshi_complete", total=len(markets), ingested=ingested)

                return ingested

            finally:
                db.close()

        except Exception as e:
            logger.error("poll_kalshi_failed", error=str(e))
            return 0

    def poll_polymarket(self) -> int:
        """Poll Polymarket for new markets.

        Returns:
            Number of markets ingested
        """
        logger.info("poll_polymarket_start")

        try:
            # Fetch all active markets with prices
            markets = self.poly_client.fetch_all_active_markets_with_prices()

            logger.info("poll_polymarket_fetched", count=len(markets))

            # Ingest each market
            db = next(get_db())
            ingested = 0

            try:
                for market in markets:
                    if self.ingest_market(market, "polymarket", db):
                        ingested += 1

                logger.info("poll_polymarket_complete", total=len(markets), ingested=ingested)

                return ingested

            finally:
                db.close()

        except Exception as e:
            logger.error("poll_polymarket_failed", error=str(e))
            return 0

    def poll_once(self) -> Dict[str, int]:
        """Poll both platforms once.

        Returns:
            Dictionary with ingestion counts
        """
        logger.info("poll_once_start")

        start_time = datetime.utcnow()

        kalshi_count = self.poll_kalshi()
        poly_count = self.poll_polymarket()

        duration = (datetime.utcnow() - start_time).total_seconds()

        logger.info(
            "poll_once_complete",
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
