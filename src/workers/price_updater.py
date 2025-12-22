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
from src.models import Market, Bond, get_db
from src.ingestion.kalshi_client import KalshiClient
from src.ingestion.polymarket_client import PolymarketGammaClient, PolymarketCLOBClient

logger = structlog.get_logger()


class PriceUpdater:
    """Update market prices without full normalization."""

    def __init__(self):
        """Initialize price updater."""
        self.kalshi_client = KalshiClient()
        self.poly_gamma_client = PolymarketGammaClient()
        self.poly_clob_client = PolymarketCLOBClient()
        self.running = False

        logger.info("price_updater_initialized")

    def update_kalshi_prices(self, db: Session, target_market_ids: List[str] = None) -> int:
        """Update prices for Kalshi markets.

        Args:
            db: Database session
            target_market_ids: Optional list of specific market IDs to update (for bond-aware updates)

        Returns:
            Number of markets updated
        """
        logger.info("update_kalshi_prices_start", target_count=len(target_market_ids) if target_market_ids else "all")

        try:
            # If target_market_ids provided, fetch those specific markets using tickers parameter
            # This guarantees we get exactly the markets we need (instead of random 1000)
            if target_market_ids:
                # Kalshi API accepts comma-separated list of tickers
                # Split into batches of 100 to avoid URL length limits
                markets_data = []
                batch_size = 100

                for i in range(0, len(target_market_ids), batch_size):
                    batch_tickers = target_market_ids[i:i + batch_size]
                    tickers_str = ",".join(batch_tickers)

                    response = self.kalshi_client.get_markets(
                        limit=batch_size,
                        tickers=tickers_str
                    )

                    batch_markets = response.get("markets", [])
                    markets_data.extend(batch_markets)

                    logger.debug(
                        "kalshi_batch_fetched",
                        batch=i//batch_size + 1,
                        requested=len(batch_tickers),
                        received=len(batch_markets),
                    )
            else:
                # Fallback: fetch all active markets
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
                    # Store both bid/ask and mid-price for enhanced arbitrage calculation
                    yes_bid = market_data.get("yes_bid", 0)
                    yes_ask = market_data.get("yes_ask", 0)

                    # Calculate mid prices
                    if yes_bid and yes_ask:
                        yes_price = (yes_bid + yes_ask) / 2 / 100  # Kalshi prices are in cents
                        no_price = 1.0 - yes_price
                        # Store bid/ask in metadata for order book reconstruction
                        bid_price = yes_bid / 100.0
                        ask_price = yes_ask / 100.0
                    else:
                        # Fallback to last_price if available
                        last_price = market_data.get("last_price", 50) / 100
                        yes_price = last_price
                        no_price = 1.0 - last_price
                        # Estimate bid/ask from mid
                        bid_price = yes_price * 0.995
                        ask_price = yes_price * 1.005

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
                                outcome["bid"] = bid_price  # Store bid for enhanced calculator
                                outcome["ask"] = ask_price  # Store ask for enhanced calculator
                            elif outcome.get("value") is False:  # No outcome
                                outcome["price"] = no_price
                                outcome["bid"] = 1.0 - ask_price  # No bid = 1 - Yes ask
                                outcome["ask"] = 1.0 - bid_price  # No ask = 1 - Yes bid

                        market.outcome_schema = outcome_schema
                        market.updated_at = datetime.utcnow()

                        # Mark JSONB field as modified for SQLAlchemy
                        flag_modified(market, "outcome_schema")
                        
                        # Log price update
                        from src.utils.bonding_logger import log_price_update
                        log_price_update(
                            platform="kalshi",
                            market_id=ticker,
                            price=yes_price,
                            price_type="mid",
                        )

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

    def update_polymarket_prices(self, db: Session, target_market_ids: List[str] = None) -> int:
        """Update prices for Polymarket markets using individual token order books.

        NEW APPROACH (2025-12-16): Fetch individual order books for each bonded market's tokens
        instead of relying on simplified-markets which only returns top 1000 active markets.

        Args:
            db: Database session
            target_market_ids: Optional list of specific market IDs to update (for bond-aware updates)

        Returns:
            Number of markets updated
        """
        logger.info("update_polymarket_prices_start", target_count=len(target_market_ids) if target_market_ids else "all")

        try:
            # NEW: Fetch markets from database to get their clob_token_ids
            # This guarantees we have token IDs for bonded markets
            if target_market_ids:
                # Fetch bonded markets from database
                markets_query = db.query(Market).filter(
                    Market.id.in_(target_market_ids),
                    Market.platform == "polymarket"
                )
                markets_to_update = markets_query.all()

                logger.info(
                    "polymarket_markets_fetched_from_db",
                    requested=len(target_market_ids),
                    found=len(markets_to_update),
                )
            else:
                # Fallback: fetch all active Polymarket markets
                markets_to_update = db.query(Market).filter(
                    Market.platform == "polymarket",
                    Market.status == "active"
                ).limit(1000).all()

            updated_count = 0
            failed_count = 0

            for market in markets_to_update:
                try:
                    condition_id = market.id

                    # Extract clob_token_ids from market_metadata
                    clob_token_ids = None
                    if market.market_metadata and isinstance(market.market_metadata, dict):
                        clob_token_ids = market.market_metadata.get("clob_token_ids")

                    if not clob_token_ids:
                        logger.debug(
                            "polymarket_no_token_ids",
                            condition_id=condition_id,
                        )
                        failed_count += 1
                        continue

                    # Fetch order book for each token to get current prices
                    outcome_schema = market.outcome_schema.copy() if market.outcome_schema else {"outcomes": []}
                    outcomes = outcome_schema.get("outcomes", [])

                    prices_updated = False

                    for i, token_id in enumerate(clob_token_ids):
                        try:
                            # Fetch order book for this token
                            order_book = self.poly_clob_client.get_market_order_book(token_id)

                            # Extract mid price from order book
                            bids = order_book.get("bids", [])
                            asks = order_book.get("asks", [])

                            if bids and asks:
                                # Get best bid and ask
                                best_bid = float(bids[0].get("price", 0)) if isinstance(bids[0], dict) else 0
                                best_ask = float(asks[0].get("price", 0)) if isinstance(asks[0], dict) else 0

                                # Calculate mid price
                                mid_price = (best_bid + best_ask) / 2

                                # Update outcome price
                                if i < len(outcomes):
                                    outcomes[i]["price"] = mid_price
                                    outcomes[i]["bid"] = best_bid
                                    outcomes[i]["ask"] = best_ask
                                    prices_updated = True

                                    logger.debug(
                                        "polymarket_token_price_updated",
                                        condition_id=condition_id,
                                        token_id=token_id[:20] + "...",
                                        mid_price=mid_price,
                                    )

                        except Exception as e:
                            logger.warning(
                                "polymarket_token_order_book_failed",
                                condition_id=condition_id,
                                token_id=token_id[:20] + "..." if token_id else None,
                                error=str(e),
                            )
                            # Continue to next token - partial updates are OK
                            continue

                    # Only update market if at least one price was fetched
                    if prices_updated:
                        market.outcome_schema = outcome_schema
                        market.updated_at = datetime.utcnow()

                        # Mark JSONB field as modified for SQLAlchemy
                        flag_modified(market, "outcome_schema")

                        # Log price update
                        from src.utils.bonding_logger import log_price_update
                        if outcomes and len(outcomes) > 0:
                            first_outcome_price = outcomes[0].get("price", 0.0)
                            log_price_update(
                                platform="polymarket",
                                market_id=condition_id,
                                price=float(first_outcome_price) if first_outcome_price else 0.0,
                                price_type="mid",
                            )

                        updated_count += 1
                    else:
                        failed_count += 1

                except Exception as e:
                    logger.error(
                        "update_polymarket_market_failed",
                        condition_id=market.id if market else "unknown",
                        error=str(e),
                    )
                    failed_count += 1
                    continue

            db.commit()

            logger.info(
                "update_polymarket_prices_complete",
                updated=updated_count,
                failed=failed_count,
                total_processed=len(markets_to_update),
            )

            return updated_count

        except Exception as e:
            logger.error("update_polymarket_prices_error", error=str(e))
            db.rollback()
            return 0

    def get_bonded_market_ids(self, db: Session) -> Dict[str, List[str]]:
        """Get market IDs for all active bonds (for bond-aware price updates).

        Args:
            db: Database session

        Returns:
            Dictionary with kalshi and polymarket market ID lists
        """
        # Get all active bonds
        bonds = db.query(Bond).filter(Bond.status == "active").all()

        kalshi_ids = set()
        poly_ids = set()

        for bond in bonds:
            kalshi_ids.add(bond.kalshi_market_id)
            poly_ids.add(bond.polymarket_market_id)

        logger.info(
            "bonded_markets_identified",
            kalshi_count=len(kalshi_ids),
            polymarket_count=len(poly_ids),
            total_bonds=len(bonds),
        )

        return {
            "kalshi": list(kalshi_ids),
            "polymarket": list(poly_ids),
        }

    def update_once(self) -> Dict[str, int]:
        """Update all prices once (bond-aware prioritization).

        Returns:
            Dictionary with update counts
        """
        logger.info("price_update_cycle_start")

        db = next(get_db())

        try:
            start_time = datetime.utcnow()

            # Get bonded market IDs for targeted updates
            bonded_ids = self.get_bonded_market_ids(db)

            # Update prices for bonded markets only (guarantees 100% match rate)
            kalshi_count = self.update_kalshi_prices(db, target_market_ids=bonded_ids["kalshi"])
            poly_count = self.update_polymarket_prices(db, target_market_ids=bonded_ids["polymarket"])

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
