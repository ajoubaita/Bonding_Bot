"""Price updater service for real-time arbitrage detection.

This service polls Kalshi and Polymarket APIs for current market prices
and updates the database without re-running expensive NLP processing.
"""

import time
import json
from typing import Dict, Any, List
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
import structlog

from src.config import settings
from src.models import Market, get_db
from src.ingestion.kalshi_client import KalshiClient
from src.ingestion.polymarket_client import PolymarketGammaClient

logger = structlog.get_logger()


class PriceUpdater:
    """Update market prices without full normalization."""

    def __init__(self):
        """Initialize price updater."""
        self.kalshi_client = KalshiClient()
        self.poly_gamma_client = PolymarketGammaClient()
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

                        # Mark JSONB field as modified for SQLAlchemy
                        flag_modified(market, "outcome_schema")

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
        """Update prices for Polymarket markets using Gamma API.

        Args:
            db: Database session

        Returns:
            Number of markets updated
        """
        logger.info("update_polymarket_prices_start")

        try:
            # Fetch markets from Gamma API with prices
            # Gamma API returns max 500 markets per request, so we'll fetch multiple batches
            all_markets_data = []
            limit = 500
            offset = 0
            max_markets = 5000  # Fetch up to 5000 markets (10 batches)

            while offset < max_markets:
                batch = self.poly_gamma_client.get_markets(
                    limit=limit,
                    offset=offset,
                    active=True,  # Only active markets
                )

                if not batch or not isinstance(batch, list):
                    break

                all_markets_data.extend(batch)

                # If we got fewer markets than limit, we've reached the end
                if len(batch) < limit:
                    break

                offset += limit

            logger.info(
                "polymarket_gamma_fetch_complete",
                total_markets=len(all_markets_data),
            )

            # Log sample conditionIds from API for debugging
            if all_markets_data:
                sample_ids = [m.get("conditionId") for m in all_markets_data[:5] if isinstance(m, dict)]
                logger.info(
                    "polymarket_sample_api_condition_ids",
                    sample_ids=sample_ids,
                )

            updated_count = 0
            checked_count = 0

            for market_data in all_markets_data:
                try:
                    if not isinstance(market_data, dict):
                        continue

                    condition_id = market_data.get("conditionId")
                    outcome_prices_str = market_data.get("outcomePrices")

                    if not condition_id or not outcome_prices_str:
                        continue

                    # Parse outcomePrices JSON string array
                    try:
                        outcome_prices = json.loads(outcome_prices_str)
                        if not isinstance(outcome_prices, list):
                            continue
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(
                            "invalid_outcome_prices_json",
                            condition_id=condition_id,
                            outcome_prices=outcome_prices_str,
                        )
                        continue

                    # Find market in database by condition_id
                    market = db.query(Market).filter(
                        Market.id == condition_id,
                        Market.platform == "polymarket"
                    ).first()

                    if market and market.outcome_schema:
                        # Update prices in outcome_schema
                        outcome_schema = market.outcome_schema.copy()
                        outcomes = outcome_schema.get("outcomes", [])

                        # Map prices to outcomes by index
                        for i, price_str in enumerate(outcome_prices):
                            if i < len(outcomes):
                                try:
                                    price = float(price_str)
                                    outcomes[i]["price"] = price
                                except (ValueError, TypeError):
                                    logger.warning(
                                        "invalid_price_value",
                                        condition_id=condition_id,
                                        index=i,
                                        price_str=price_str,
                                    )
                                    continue

                        market.outcome_schema = outcome_schema
                        market.updated_at = datetime.utcnow()

                        # Mark JSONB field as modified for SQLAlchemy
                        flag_modified(market, "outcome_schema")

                        updated_count += 1

                except Exception as e:
                    logger.error(
                        "update_polymarket_price_failed",
                        condition_id=market_data.get("conditionId") if isinstance(market_data, dict) else "unknown",
                        error=str(e),
                    )
                    continue

            db.commit()

            logger.info(
                "update_polymarket_prices_complete",
                updated=updated_count,
                total_fetched=len(all_markets_data),
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
        self.poly_gamma_client.session.close()
