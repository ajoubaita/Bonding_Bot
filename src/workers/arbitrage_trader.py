"""Continuous arbitrage trading worker (dry-run mode).

Monitors bonded markets for arbitrage opportunities and executes mock trades.
Runs every 60 seconds to detect price inefficiencies.
"""

import time
import sys
from typing import List, Dict, Any
from datetime import datetime
import structlog

from src.models import Bond, Market, get_db
from src.trading.mock_trader import MockTrader
from src.utils.bonding_logger import log_arbitrage_scan

logger = structlog.get_logger()


class ArbitrageTrader:
    """Continuous worker for arbitrage detection and mock trading."""

    def __init__(
        self,
        starting_balance: float = 5000.00,
        max_position_size: float = 100.00,
        min_profit_threshold: float = 0.01,  # 1% minimum
        scan_interval_sec: int = 60,
        tier_filter: int = 1,  # Only trade Tier 1 bonds by default
    ):
        """Initialize arbitrage trader.

        Args:
            starting_balance: Starting capital ($5000 default)
            max_position_size: Max $ per trade ($100 default)
            min_profit_threshold: Minimum profit % (0.01 = 1%)
            scan_interval_sec: Seconds between scans (60 default)
            tier_filter: Only trade bonds of this tier (1 = Tier 1 only)
        """
        self.scan_interval_sec = scan_interval_sec
        self.tier_filter = tier_filter
        self.running = False

        # Initialize mock trader
        self.trader = MockTrader(
            starting_balance=starting_balance,
            max_position_size=max_position_size,
            min_profit_threshold=min_profit_threshold,
        )

        logger.info(
            "arbitrage_trader_initialized",
            starting_balance=starting_balance,
            max_position_size=max_position_size,
            min_profit_pct=min_profit_threshold * 100,
            scan_interval_sec=scan_interval_sec,
            tier_filter=tier_filter,
        )

    def get_market_price(self, market: Market) -> float:
        """Extract YES price from market.

        Args:
            market: Market object with outcome_schema

        Returns:
            YES price as float [0, 1], or None if not available
        """
        if not market or not market.outcome_schema:
            return None

        outcomes = market.outcome_schema.get("outcomes", [])
        if not outcomes:
            return None

        # Find YES outcome
        for outcome in outcomes:
            if outcome.get("value") is True:  # YES outcome
                price = outcome.get("price")
                if price is not None:
                    return float(price)

        # Fallback: use first outcome if no YES found
        if outcomes:
            price = outcomes[0].get("price")
            if price is not None:
                return float(price)

        return None

    def scan_for_opportunities(self) -> List[Dict[str, Any]]:
        """Scan all bonds for arbitrage opportunities.

        Returns:
            List of arbitrage opportunities detected
        """
        db = next(get_db())

        try:
            # Query active bonds (filter by tier if specified)
            query = db.query(Bond).filter(Bond.status == "active")

            if self.tier_filter is not None:
                query = query.filter(Bond.tier == self.tier_filter)

            bonds = query.all()

            logger.info(
                "arbitrage_scan_start",
                total_bonds=len(bonds),
                tier_filter=self.tier_filter,
            )

            opportunities = []
            trades_executed = 0

            for bond in bonds:
                try:
                    # Get markets
                    kalshi_market = db.query(Market).filter(
                        Market.id == bond.kalshi_market_id
                    ).first()

                    poly_market = db.query(Market).filter(
                        Market.id == bond.polymarket_market_id
                    ).first()

                    if not kalshi_market or not poly_market:
                        continue

                    # Get YES prices
                    kalshi_yes_price = self.get_market_price(kalshi_market)
                    poly_yes_price = self.get_market_price(poly_market)

                    if kalshi_yes_price is None or poly_yes_price is None:
                        continue

                    # Calculate NO prices (complement)
                    kalshi_no_price = 1.0 - kalshi_yes_price
                    poly_no_price = 1.0 - poly_yes_price

                    # Check both arbitrage directions
                    # Direction 1: Buy Kalshi YES + Poly NO
                    cost1 = kalshi_yes_price + poly_no_price
                    profit1 = 1.0 - cost1
                    profit1_pct = (profit1 / cost1) * 100 if cost1 > 0 else 0

                    # Direction 2: Buy Poly YES + Kalshi NO
                    cost2 = poly_yes_price + kalshi_no_price
                    profit2 = 1.0 - cost2
                    profit2_pct = (profit2 / cost2) * 100 if cost2 > 0 else 0

                    # Take best direction
                    best_profit_pct = max(profit1_pct, profit2_pct)

                    # Check if profitable
                    if best_profit_pct > (self.trader.min_profit_threshold * 100):
                        opportunity = {
                            "bond_id": bond.pair_id,
                            "kalshi_market_id": bond.kalshi_market_id,
                            "poly_market_id": bond.polymarket_market_id,
                            "kalshi_yes_price": kalshi_yes_price,
                            "poly_yes_price": poly_yes_price,
                            "profit_pct": best_profit_pct,
                            "tier": bond.tier,
                            "similarity_score": bond.similarity_score,
                        }

                        opportunities.append(opportunity)

                        # Execute mock trade
                        trade = self.trader.execute_arbitrage_trade(
                            bond_id=bond.pair_id,
                            kalshi_market_id=bond.kalshi_market_id,
                            poly_market_id=bond.polymarket_market_id,
                            kalshi_yes_price=kalshi_yes_price,
                            poly_yes_price=poly_yes_price,
                            tier=bond.tier,
                            similarity_score=bond.similarity_score,
                        )

                        if trade:
                            trades_executed += 1

                            logger.info(
                                "arbitrage_opportunity_traded",
                                bond_id=bond.pair_id,
                                trade_id=trade.trade_id,
                                profit_pct=best_profit_pct,
                                position_size=trade.kalshi_size,
                            )

                except Exception as e:
                    logger.error(
                        "bond_scan_error",
                        bond_id=bond.pair_id if bond else "unknown",
                        error=str(e),
                    )
                    continue

            logger.info(
                "arbitrage_scan_complete",
                total_bonds=len(bonds),
                opportunities_found=len(opportunities),
                trades_executed=trades_executed,
                portfolio_balance=self.trader.portfolio.current_balance,
                total_trades=self.trader.portfolio.total_trades,
            )

            # Log to structured logging
            log_arbitrage_scan(
                total_bonds=len(bonds),
                opportunities=len(opportunities),
                trades_executed=trades_executed,
                portfolio_balance=self.trader.portfolio.current_balance,
            )

            return opportunities

        except Exception as e:
            logger.error("arbitrage_scan_failed", error=str(e))
            return []

        finally:
            db.close()

    def print_status_report(self):
        """Print current trading status to console."""
        portfolio = self.trader.get_portfolio_summary()
        recent_trades = self.trader.get_recent_trades(limit=5)
        stats = self.trader.get_trade_stats()

        print("\n" + "=" * 80)
        print("ARBITRAGE TRADING BOT - STATUS REPORT")
        print("=" * 80)
        print(f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print()
        print("PORTFOLIO:")
        print(f"  Starting Balance:    ${portfolio['starting_balance']:,.2f}")
        print(f"  Current Balance:     ${portfolio['current_balance']:,.2f}")
        print(f"  Available Balance:   ${portfolio['available_balance']:,.2f}")
        print(f"  Locked Capital:      ${portfolio['locked_capital']:,.2f}")
        print(f"  Net Profit:          ${portfolio['net_profit']:,.2f}")
        print(f"  Total Return:        {portfolio['total_return_pct']:.2f}%")
        print()
        print("TRADING STATS:")
        print(f"  Total Trades:        {portfolio['total_trades']}")
        print(f"  Active Positions:    {portfolio['active_positions']}")
        print(f"  Avg Profit/Trade:    ${stats.get('avg_profit_per_trade', 0):.2f}")
        print(f"  Avg Profit %:        {stats.get('avg_profit_pct', 0):.2f}%")
        print()

        if recent_trades:
            print("RECENT TRADES (Last 5):")
            for i, trade in enumerate(recent_trades[:5], 1):
                print(f"  {i}. {trade['timestamp'][:19]}")
                print(f"     Bond: {trade['bond_id']}")
                print(f"     Strategy: {trade['kalshi_side']} on Kalshi + {trade['poly_side']} on Poly")
                print(f"     Position: {trade['kalshi_size']:.2f} shares @ ${trade['total_cost']:.2f}")
                print(f"     Profit: ${trade['expected_profit']:.2f} ({trade['profit_pct']:.2f}%)")
                print()

        print("=" * 80)
        print()

    def run_continuous(self):
        """Run continuous arbitrage trading loop."""
        logger.info(
            "arbitrage_trader_start",
            scan_interval_sec=self.scan_interval_sec,
        )

        print("\n" + "=" * 80)
        print("ARBITRAGE TRADING BOT STARTED (DRY-RUN MODE)")
        print("=" * 80)
        print(f"Starting Balance: ${self.trader.portfolio.starting_balance:,.2f}")
        print(f"Max Position Size: ${self.trader.max_position_size:,.2f}")
        print(f"Min Profit Threshold: {self.trader.min_profit_threshold * 100:.1f}%")
        print(f"Scan Interval: {self.scan_interval_sec}s")
        print(f"Tier Filter: Tier {self.tier_filter} only")
        print("=" * 80)
        print()

        self.running = True
        scan_count = 0

        while self.running:
            try:
                scan_count += 1

                logger.info(
                    "arbitrage_scan_cycle_start",
                    scan_number=scan_count,
                )

                # Scan for opportunities and execute trades
                opportunities = self.scan_for_opportunities()

                # Print status every scan
                self.print_status_report()

                # Sleep until next scan
                logger.debug(
                    "arbitrage_scan_sleeping",
                    next_scan_in_sec=self.scan_interval_sec,
                )

                time.sleep(self.scan_interval_sec)

            except KeyboardInterrupt:
                logger.info("arbitrage_trader_interrupted")
                print("\n\nTrading bot stopped by user.")
                break

            except Exception as e:
                logger.error(
                    "arbitrage_trader_error",
                    error=str(e),
                    scan_number=scan_count,
                )
                print(f"\n\nERROR: {str(e)}")
                print("Waiting 10 seconds before retry...")
                time.sleep(10)

        self.running = False

        # Final report
        print("\n" + "=" * 80)
        print("FINAL TRADING REPORT")
        print("=" * 80)
        self.print_status_report()

        logger.info(
            "arbitrage_trader_stopped",
            total_scans=scan_count,
            final_balance=self.trader.portfolio.current_balance,
            total_trades=self.trader.portfolio.total_trades,
        )

    def stop(self):
        """Stop the trading loop."""
        logger.info("arbitrage_trader_stop_requested")
        self.running = False


def main():
    """Main entry point for arbitrage trader worker."""
    import argparse

    parser = argparse.ArgumentParser(description="Arbitrage Trading Bot (Dry-Run)")
    parser.add_argument("--balance", type=float, default=5000.00, help="Starting balance in USD")
    parser.add_argument("--max-position", type=float, default=100.00, help="Max position size in USD")
    parser.add_argument("--min-profit", type=float, default=1.0, help="Min profit percent (e.g., 1.0 for 1%%)")
    parser.add_argument("--interval", type=int, default=60, help="Scan interval in seconds")
    parser.add_argument("--tier", type=int, default=1, help="Bond tier filter (1, 2, 3, or None for all)")

    args = parser.parse_args()

    # Create trader
    trader = ArbitrageTrader(
        starting_balance=args.balance,
        max_position_size=args.max_position,
        min_profit_threshold=args.min_profit / 100.0,  # Convert % to decimal
        scan_interval_sec=args.interval,
        tier_filter=args.tier,
    )

    # Run
    try:
        trader.run_continuous()
    except KeyboardInterrupt:
        print("\n\nShutting down gracefully...")
        trader.stop()
    except Exception as e:
        logger.error("arbitrage_trader_fatal_error", error=str(e))
        print(f"\n\nFATAL ERROR: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
