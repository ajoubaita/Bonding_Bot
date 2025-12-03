"""Price updater service for real-time arbitrage detection.

This service polls Kalshi and Polymarket APIs for current market prices
and updates the database without re-running expensive NLP processing.
"""

import time
from typing import Dict, Any, List
from datetime import datetime
from sqlalchemy.orm import Session
import structlog

from src.config import settings
from src.models import Market, get_db
from src.ingestion.kalshi_client import KalshiClient
from src.ingestion.polymarket_client import PolymarketCLOBClient

logger = structlog.get_logger()


class PriceUpdater:
    """Update market prices without full normalization."""

    def __init__(self):
        """Initialize price updater."""
        self.kalshi_client = KalshiClient()
        self.poly_clob_client = PolymarketCLOBClient()
        self.running = False

        logger.info("price_updater_initialized")

    def update_kalshi_prices(self, db: Session) -> int:
        """Update prices for Kalshi markets.

        Args:
            db: Database session

        Returns:
            Number of markets updated
        """
        logger.info("update_kalshi_prices_start")

        try:
            # Fetch all active markets with prices from Kalshi API
            response = self.kalshi_client.get_markets(
                limit=1000,
                status="open"
            )

            markets_data = response.get("markets", [])
            updated_count = 0

            for market_data in markets_data:
                try:
                    ticker = market_data.get("ticker")

                    # Extract prices - Kalshi provides yes_bid, yes_ask, etc.
                    # We'll use the mid-price (average of bid/ask)
                    yes_bid = market_data.get("yes_bid", 0)
                    yes_ask = market_data.get("yes_ask", 0)

                    # Calculate mid prices
                    if yes_bid and yes_ask:
                        yes_price = (yes_bid + yes_ask) / 2 / 100  # Kalshi prices are in cents
                        no_price = 1.0 - yes_price
                    else:
                        # Fallback to last_price if available
                        last_price = market_data.get("last_price", 50) / 100
                        yes_price = last_price
                        no_price = 1.0 - last_price

                    # Find market in database
                    market = db.query(Market).filter(
                        Market.id == ticker,
                        Market.platform == "kalshi"
                    ).first()

                    if market and market.outcome_schema:
                        # Update prices in outcome_schema
                        outcome_schema = market.outcome_schema.copy()
                        outcomes = outcome_schema.get("outcomes", [])

                        for outcome in outcomes:
                            if outcome.get("value") is True:  # Yes outcome
                                outcome["price"] = yes_price
                            elif outcome.get("value") is False:  # No outcome
                                outcome["price"] = no_price

                        market.outcome_schema = outcome_schema
                        market.updated_at = datetime.utcnow()
                        updated_count += 1

                except Exception as e:
                    logger.error(
                        "update_kalshi_price_failed",
                        ticker=market_data.get("ticker"),
                        error=str(e),
                    )
                    continue

            db.commit()

            logger.info(
                "update_kalshi_prices_complete",
                updated=updated_count,
                total_fetched=len(markets_data),
            )

            return updated_count

        except Exception as e:
            logger.error("update_kalshi_prices_error", error=str(e))
            db.rollback()
            return 0

    def update_polymarket_prices(self, db: Session) -> int:
        """Update prices for Polymarket markets.

        Args:
            db: Database session

        Returns:
            Number of markets updated
        """
        logger.info("update_polymarket_prices_start")

        try:
            # Fetch simplified markets with prices from CLOB API
            markets_data = self.poly_clob_client.get_simplified_markets()

            if not isinstance(markets_data, list):
                logger.error(
                    "unexpected_polymarket_response",
                    response_type=type(markets_data).__name__,
                )
                return 0

            updated_count = 0

            for market_data in markets_data:
                try:
                    if not isinstance(market_data, dict):
                        continue

                    condition_id = market_data.get("condition_id")
                    tokens = market_data.get("tokens", [])

                    if not condition_id or not tokens:
                        continue

                    # Find market in database
                    market = db.query(Market).filter(
                        Market.id == condition_id,
                        Market.platform == "polymarket"
                    ).first()

                    if market and market.outcome_schema:
                        # Update prices in outcome_schema
                        outcome_schema = market.outcome_schema.copy()
                        outcomes = outcome_schema.get("outcomes", [])

                        # Match tokens to outcomes
                        for token in tokens:
                            if not isinstance(token, dict):
                                continue

                            token_price = float(token.get("price", 0.5))
                            token_outcome = token.get("outcome", "").lower()

                            # Update matching outcome
                            for outcome in outcomes:
                                outcome_label = outcome.get("label", "").lower()
                                if token_outcome in outcome_label or outcome_label in token_outcome:
                                    outcome["price"] = token_price
                                    break

                        market.outcome_schema = outcome_schema
                        market.updated_at = datetime.utcnow()
                        updated_count += 1

                except Exception as e:
                    logger.error(
                        "update_polymarket_price_failed",
                        condition_id=market_data.get("condition_id") if isinstance(market_data, dict) else "unknown",
                        error=str(e),
                    )
                    continue

            db.commit()

            logger.info(
                "update_polymarket_prices_complete",
                updated=updated_count,
                total_fetched=len(markets_data),
            )

            return updated_count

        except Exception as e:
            logger.error("update_polymarket_prices_error", error=str(e))
            db.rollback()
            return 0

    def update_once(self) -> Dict[str, int]:
        """Update all prices once.

        Returns:
            Dictionary with update counts
        """
        logger.info("price_update_cycle_start")

        db = next(get_db())

        try:
            start_time = datetime.utcnow()

            kalshi_count = self.update_kalshi_prices(db)
            poly_count = self.update_polymarket_prices(db)

            duration = (datetime.utcnow() - start_time).total_seconds()

            logger.info(
                "price_update_cycle_complete",
                kalshi_updated=kalshi_count,
                polymarket_updated=poly_count,
                duration_seconds=duration,
            )

            return {
                "kalshi": kalshi_count,
                "polymarket": poly_count,
                "duration_seconds": duration,
            }

        finally:
            db.close()

    def run_continuous(self, interval_seconds: int = 60):
        """Run continuous price updates.

        Args:
            interval_seconds: Seconds between updates (default 60)
        """
        logger.info(
            "price_updater_start_continuous",
            interval_seconds=interval_seconds,
        )

        self.running = True

        while self.running:
            try:
                self.update_once()
                time.sleep(interval_seconds)

            except KeyboardInterrupt:
                logger.info("price_updater_interrupted")
                break

            except Exception as e:
                logger.error("price_updater_error", error=str(e))
                time.sleep(10)  # Wait before retrying

        self.running = False
        logger.info("price_updater_stopped")

    def stop(self):
        """Stop continuous updates."""
        logger.info("price_updater_stop_requested")
        self.running = False

    def close(self):
        """Close API clients."""
        self.kalshi_client.close()
        self.poly_clob_client.close()
