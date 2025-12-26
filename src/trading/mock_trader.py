"""Mock trading system for dry-run arbitrage execution.

This module simulates trading on bonded markets to test arbitrage strategies
without risking real money. Tracks PnL and trade history.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict
from decimal import Decimal
import json
import structlog
from pathlib import Path

logger = structlog.get_logger()


@dataclass
class MockTrade:
    """Represents a mock trade execution."""

    trade_id: str
    timestamp: datetime
    bond_id: str

    # Trade details
    strategy: str  # "dual_position" (buy YES and NO)
    kalshi_market_id: str
    poly_market_id: str

    # Positions taken
    kalshi_side: str  # "YES" or "NO"
    kalshi_price: float
    kalshi_size: float

    poly_side: str  # "YES" or "NO" (opposite of Kalshi)
    poly_price: float
    poly_size: float

    # Trade economics
    total_cost: float
    guaranteed_payout: float  # Always $1.00 per share for matched positions
    expected_profit: float
    profit_pct: float

    # Market metadata
    tier: int
    similarity_score: float

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class Portfolio:
    """Tracks mock trading portfolio."""

    starting_balance: float = 5000.00
    current_balance: float = 5000.00
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.00
    total_fees: float = 0.00

    # Position tracking
    active_positions: int = 0
    locked_capital: float = 0.00

    # Performance metrics
    win_rate: float = 0.00
    avg_profit_per_trade: float = 0.00
    total_return_pct: float = 0.00
    sharpe_ratio: float = 0.00

    created_at: datetime = None
    last_updated: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.utcnow()
        if self.last_updated is None:
            self.last_updated = datetime.utcnow()

    def update_metrics(self):
        """Recalculate performance metrics."""
        self.last_updated = datetime.utcnow()

        if self.total_trades > 0:
            self.win_rate = self.winning_trades / self.total_trades
            self.avg_profit_per_trade = self.total_profit / self.total_trades

        self.total_return_pct = ((self.current_balance - self.starting_balance) / self.starting_balance) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "starting_balance": self.starting_balance,
            "current_balance": self.current_balance,
            "available_balance": self.current_balance - self.locked_capital,
            "locked_capital": self.locked_capital,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": self.win_rate,
            "total_profit": self.total_profit,
            "total_fees": self.total_fees,
            "net_profit": self.total_profit - self.total_fees,
            "avg_profit_per_trade": self.avg_profit_per_trade,
            "total_return_pct": self.total_return_pct,
            "active_positions": self.active_positions,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


class MockTrader:
    """Simulates arbitrage trading in dry-run mode."""

    def __init__(
        self,
        starting_balance: float = 5000.00,
        max_position_size: float = 100.00,
        min_profit_threshold: float = 0.01,  # 1% minimum profit
        trade_log_path: str = "/tmp/bonding_bot_trades.json",
        portfolio_path: str = "/tmp/bonding_bot_portfolio.json",
    ):
        """Initialize mock trader.

        Args:
            starting_balance: Starting capital in USD
            max_position_size: Maximum size per trade in USD
            min_profit_threshold: Minimum profit % to execute trade (0.01 = 1%)
            trade_log_path: Path to save trade history
            portfolio_path: Path to save portfolio state
        """
        self.max_position_size = max_position_size
        self.min_profit_threshold = min_profit_threshold
        self.trade_log_path = Path(trade_log_path)
        self.portfolio_path = Path(portfolio_path)

        # Load or create portfolio
        self.portfolio = self._load_portfolio(starting_balance)

        # Load trade history
        self.trades: List[MockTrade] = self._load_trades()

        logger.info(
            "mock_trader_initialized",
            starting_balance=self.portfolio.starting_balance,
            current_balance=self.portfolio.current_balance,
            total_trades=len(self.trades),
            max_position_size=max_position_size,
        )

    def _load_portfolio(self, starting_balance: float) -> Portfolio:
        """Load portfolio from disk or create new."""
        if self.portfolio_path.exists():
            try:
                with open(self.portfolio_path, 'r') as f:
                    data = json.load(f)
                    portfolio = Portfolio(**{
                        k: v for k, v in data.items()
                        if k in Portfolio.__dataclass_fields__
                    })
                    # Convert datetime strings back
                    if isinstance(portfolio.created_at, str):
                        portfolio.created_at = datetime.fromisoformat(portfolio.created_at)
                    if isinstance(portfolio.last_updated, str):
                        portfolio.last_updated = datetime.fromisoformat(portfolio.last_updated)

                    logger.info("portfolio_loaded", path=str(self.portfolio_path))
                    return portfolio
            except Exception as e:
                logger.error("portfolio_load_error", error=str(e))

        # Create new portfolio
        return Portfolio(starting_balance=starting_balance)

    def _save_portfolio(self):
        """Save portfolio to disk."""
        try:
            with open(self.portfolio_path, 'w') as f:
                json.dump(self.portfolio.to_dict(), f, indent=2)
            logger.debug("portfolio_saved", path=str(self.portfolio_path))
        except Exception as e:
            logger.error("portfolio_save_error", error=str(e))

    def _load_trades(self) -> List[MockTrade]:
        """Load trade history from disk."""
        if self.trade_log_path.exists():
            try:
                with open(self.trade_log_path, 'r') as f:
                    data = json.load(f)
                    trades = []
                    for trade_dict in data:
                        # Convert timestamp string back to datetime
                        if isinstance(trade_dict.get("timestamp"), str):
                            trade_dict["timestamp"] = datetime.fromisoformat(trade_dict["timestamp"])
                        trades.append(MockTrade(**trade_dict))

                    logger.info("trades_loaded", count=len(trades), path=str(self.trade_log_path))
                    return trades
            except Exception as e:
                logger.error("trades_load_error", error=str(e))

        return []

    def _save_trades(self):
        """Save trade history to disk."""
        try:
            with open(self.trade_log_path, 'w') as f:
                trades_data = [trade.to_dict() for trade in self.trades]
                json.dump(trades_data, f, indent=2)
            logger.debug("trades_saved", count=len(self.trades), path=str(self.trade_log_path))
        except Exception as e:
            logger.error("trades_save_error", error=str(e))

    def execute_arbitrage_trade(
        self,
        bond_id: str,
        kalshi_market_id: str,
        poly_market_id: str,
        kalshi_yes_price: float,
        poly_yes_price: float,
        tier: int = 1,
        similarity_score: float = 0.0,
    ) -> Optional[MockTrade]:
        """Execute a dual-position arbitrage trade (buy YES + NO).

        Strategy: Buy YES on one platform and NO on the other.
        When the market resolves, one position wins $1.00, the other loses.
        Profit = $1.00 - (cost of YES + cost of NO)

        Args:
            bond_id: Bond pair_id
            kalshi_market_id: Kalshi market ID
            poly_market_id: Polymarket market ID
            kalshi_yes_price: Kalshi YES price [0, 1]
            poly_yes_price: Polymarket YES price [0, 1]
            tier: Bond tier (for logging)
            similarity_score: Bond similarity score (for logging)

        Returns:
            MockTrade object if executed, None if skipped
        """
        # Calculate NO prices (complement of YES)
        kalshi_no_price = 1.0 - kalshi_yes_price
        poly_no_price = 1.0 - poly_yes_price

        # Find the best arbitrage opportunity:
        # Option 1: Buy Kalshi YES + Poly NO
        cost_option1 = kalshi_yes_price + poly_no_price
        profit_option1 = 1.0 - cost_option1

        # Option 2: Buy Poly YES + Kalshi NO
        cost_option2 = poly_yes_price + kalshi_no_price
        profit_option2 = 1.0 - cost_option2

        # Choose the more profitable option
        if profit_option1 >= profit_option2:
            total_cost = cost_option1
            expected_profit = profit_option1
            kalshi_side = "YES"
            kalshi_price = kalshi_yes_price
            poly_side = "NO"
            poly_price = poly_no_price
            strategy_desc = "Buy Kalshi YES + Poly NO"
        else:
            total_cost = cost_option2
            expected_profit = profit_option2
            kalshi_side = "NO"
            kalshi_price = kalshi_no_price
            poly_side = "YES"
            poly_price = poly_yes_price
            strategy_desc = "Buy Poly YES + Kalshi NO"

        profit_pct = (expected_profit / total_cost) * 100 if total_cost > 0 else 0

        # Check if trade meets minimum profit threshold
        if profit_pct < (self.min_profit_threshold * 100):
            logger.debug(
                "trade_rejected_low_profit",
                bond_id=bond_id,
                profit_pct=profit_pct,
                threshold_pct=self.min_profit_threshold * 100,
            )
            return None

        # Determine position size (limited by balance and max position size)
        available_balance = self.portfolio.current_balance - self.portfolio.locked_capital
        max_shares = min(
            available_balance / total_cost,  # Balance limit
            self.max_position_size / total_cost  # Position size limit
        )

        # Round down to 2 decimals
        position_size = round(max_shares, 2)

        if position_size < 1.0:
            logger.warning(
                "trade_rejected_insufficient_balance",
                bond_id=bond_id,
                required=total_cost,
                available=available_balance,
            )
            return None

        # Create trade object
        trade_id = f"trade_{bond_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"

        trade = MockTrade(
            trade_id=trade_id,
            timestamp=datetime.utcnow(),
            bond_id=bond_id,
            strategy="dual_position",
            kalshi_market_id=kalshi_market_id,
            poly_market_id=poly_market_id,
            kalshi_side=kalshi_side,
            kalshi_price=kalshi_price,
            kalshi_size=position_size,
            poly_side=poly_side,
            poly_price=poly_price,
            poly_size=position_size,
            total_cost=total_cost * position_size,
            guaranteed_payout=1.0 * position_size,  # $1 per share
            expected_profit=expected_profit * position_size,
            profit_pct=profit_pct,
            tier=tier,
            similarity_score=similarity_score,
        )

        # Update portfolio
        self.portfolio.locked_capital += trade.total_cost
        self.portfolio.active_positions += 1
        self.portfolio.total_trades += 1

        # Record trade
        self.trades.append(trade)

        # Log the execution
        logger.info(
            "mock_trade_executed",
            trade_id=trade_id,
            bond_id=bond_id,
            strategy=strategy_desc,
            kalshi_side=kalshi_side,
            kalshi_price=kalshi_price,
            poly_side=poly_side,
            poly_price=poly_price,
            position_size=position_size,
            total_cost=trade.total_cost,
            expected_profit=trade.expected_profit,
            profit_pct=profit_pct,
            tier=tier,
        )

        # Save state
        self._save_trades()
        self._save_portfolio()

        return trade

    def settle_trade(self, trade_id: str, winning_side: str):
        """Settle a completed trade and realize profit.

        Args:
            trade_id: Trade ID to settle
            winning_side: "kalshi" or "polymarket" (which side won)
        """
        # Find trade
        trade = next((t for t in self.trades if t.trade_id == trade_id), None)
        if not trade:
            logger.error("settle_trade_not_found", trade_id=trade_id)
            return

        # Calculate realized profit
        realized_profit = trade.expected_profit  # Guaranteed by dual position

        # Update portfolio
        self.portfolio.locked_capital -= trade.total_cost
        self.portfolio.current_balance += trade.guaranteed_payout
        self.portfolio.total_profit += realized_profit
        self.portfolio.active_positions -= 1
        self.portfolio.winning_trades += 1

        # Update metrics
        self.portfolio.update_metrics()

        logger.info(
            "trade_settled",
            trade_id=trade_id,
            realized_profit=realized_profit,
            new_balance=self.portfolio.current_balance,
        )

        # Save state
        self._save_portfolio()

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """Get current portfolio state."""
        return self.portfolio.to_dict()

    def get_recent_trades(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent trades."""
        recent = self.trades[-limit:] if len(self.trades) > limit else self.trades
        return [trade.to_dict() for trade in reversed(recent)]

    def get_trade_stats(self) -> Dict[str, Any]:
        """Get trading statistics."""
        if not self.trades:
            return {
                "total_trades": 0,
                "total_profit": 0.0,
                "avg_profit_per_trade": 0.0,
                "best_trade_profit": 0.0,
                "worst_trade_profit": 0.0,
            }

        profits = [t.expected_profit for t in self.trades]

        return {
            "total_trades": len(self.trades),
            "total_profit": sum(profits),
            "avg_profit_per_trade": sum(profits) / len(profits),
            "avg_profit_pct": sum(t.profit_pct for t in self.trades) / len(self.trades),
            "best_trade_profit": max(profits),
            "worst_trade_profit": min(profits),
            "trades_by_tier": {
                "tier1": sum(1 for t in self.trades if t.tier == 1),
                "tier2": sum(1 for t in self.trades if t.tier == 2),
                "tier3": sum(1 for t in self.trades if t.tier == 3),
            }
        }
