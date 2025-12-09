"""Risk management for trade execution.

SAFETY FIRST: This module enforces risk limits before any trade execution.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
import structlog

from src.config import settings

logger = structlog.get_logger()


@dataclass
class RiskLimits:
    """Risk limits for trading."""

    # Position limits
    max_position_size_usd: float = 1000.0  # Max $1000 per position
    max_daily_volume_usd: float = 10000.0  # Max $10k daily volume
    max_total_exposure_usd: float = 5000.0  # Max $5k total exposure

    # Market limits
    max_positions_per_market: int = 1  # Max 1 position per market
    max_open_positions: int = 10  # Max 10 open positions total

    # Profit/Loss limits
    max_daily_loss_usd: float = 500.0  # Max $500 daily loss
    min_profit_threshold: float = 0.01  # Min 1% profit after fees

    # Time limits
    max_order_age_seconds: int = 300  # Cancel orders older than 5 min
    cooldown_after_loss_seconds: int = 3600  # 1 hour cooldown after loss

    # Tier-specific limits
    tier1_max_position_usd: float = 1000.0  # Tier 1 auto-bond limit
    tier2_max_position_usd: float = 200.0  # Tier 2 cautious bond limit
    tier3_max_position_usd: float = 0.0  # Tier 3 reject - no trading


class RiskManager:
    """Manages risk limits and validates trades before execution."""

    def __init__(self, limits: Optional[RiskLimits] = None):
        """Initialize risk manager.

        Args:
            limits: Custom risk limits (uses defaults if not provided)
        """
        self.limits = limits or RiskLimits()
        self.daily_volume = 0.0
        self.daily_pnl = 0.0
        self.open_positions: List[Dict[str, Any]] = []
        self.last_reset = datetime.utcnow()
        self.last_loss_time: Optional[datetime] = None

        logger.info(
            "risk_manager_initialized",
            max_position=self.limits.max_position_size_usd,
            max_daily_volume=self.limits.max_daily_volume_usd,
            max_exposure=self.limits.max_total_exposure_usd,
        )

    def reset_daily_limits(self):
        """Reset daily counters (call at midnight UTC)."""
        now = datetime.utcnow()
        if now.date() > self.last_reset.date():
            self.daily_volume = 0.0
            self.daily_pnl = 0.0
            self.last_reset = now
            logger.info("daily_limits_reset", date=now.date())

    def validate_trade(
        self,
        position_size_usd: float,
        profit_estimate: float,
        tier: int,
        kalshi_market_id: str,
        polymarket_market_id: str,
    ) -> Dict[str, Any]:
        """Validate trade against risk limits.

        Args:
            position_size_usd: Size of position in USD
            profit_estimate: Estimated profit per dollar
            tier: Similarity tier (1=auto, 2=cautious, 3=reject)
            kalshi_market_id: Kalshi market ID
            polymarket_market_id: Polymarket market ID

        Returns:
            Dictionary with validation result:
            {
                "approved": bool,
                "reason": str,
                "adjusted_size": float,  # May be reduced to fit limits
                "warnings": List[str],
            }
        """
        self.reset_daily_limits()

        result = {
            "approved": False,
            "reason": "",
            "adjusted_size": position_size_usd,
            "warnings": [],
        }

        # Check 1: Tier 3 rejection
        if tier == 3:
            result["reason"] = "Tier 3 (Reject) - Not approved for trading"
            logger.warning(
                "trade_rejected_tier3",
                kalshi_id=kalshi_market_id,
                poly_id=polymarket_market_id,
            )
            return result

        # Check 2: Cooldown after loss
        if self.last_loss_time:
            cooldown_remaining = (
                self.last_loss_time +
                timedelta(seconds=self.limits.cooldown_after_loss_seconds) -
                datetime.utcnow()
            ).total_seconds()

            if cooldown_remaining > 0:
                result["reason"] = f"Cooldown active: {int(cooldown_remaining/60)} minutes remaining"
                result["warnings"].append("Recent loss - trading temporarily disabled")
                logger.warning(
                    "trade_rejected_cooldown",
                    cooldown_remaining_sec=cooldown_remaining,
                )
                return result

        # Check 3: Profit threshold
        if profit_estimate < self.limits.min_profit_threshold:
            result["reason"] = f"Profit {profit_estimate:.2%} below minimum {self.limits.min_profit_threshold:.2%}"
            logger.info(
                "trade_rejected_low_profit",
                profit=profit_estimate,
                min_required=self.limits.min_profit_threshold,
            )
            return result

        # Check 4: Tier-specific position limit
        tier_max = {
            1: self.limits.tier1_max_position_usd,
            2: self.limits.tier2_max_position_usd,
            3: self.limits.tier3_max_position_usd,
        }[tier]

        if position_size_usd > tier_max:
            result["adjusted_size"] = tier_max
            result["warnings"].append(f"Position reduced from ${position_size_usd:.0f} to ${tier_max:.0f} (Tier {tier} limit)")
            position_size_usd = tier_max

        # Check 5: Absolute position limit
        if position_size_usd > self.limits.max_position_size_usd:
            result["adjusted_size"] = self.limits.max_position_size_usd
            result["warnings"].append(f"Position reduced to ${self.limits.max_position_size_usd:.0f} (absolute limit)")
            position_size_usd = self.limits.max_position_size_usd

        # Check 6: Daily volume limit
        if self.daily_volume + position_size_usd > self.limits.max_daily_volume_usd:
            max_allowed = self.limits.max_daily_volume_usd - self.daily_volume
            if max_allowed <= 0:
                result["reason"] = f"Daily volume limit reached (${self.daily_volume:.0f} / ${self.limits.max_daily_volume_usd:.0f})"
                logger.warning(
                    "trade_rejected_daily_volume",
                    daily_volume=self.daily_volume,
                    limit=self.limits.max_daily_volume_usd,
                )
                return result

            result["adjusted_size"] = max_allowed
            result["warnings"].append(f"Position reduced to ${max_allowed:.0f} (daily volume limit)")
            position_size_usd = max_allowed

        # Check 7: Total exposure limit
        current_exposure = sum(p["size_usd"] for p in self.open_positions)
        if current_exposure + position_size_usd > self.limits.max_total_exposure_usd:
            max_allowed = self.limits.max_total_exposure_usd - current_exposure
            if max_allowed <= 0:
                result["reason"] = f"Total exposure limit reached (${current_exposure:.0f} / ${self.limits.max_total_exposure_usd:.0f})"
                logger.warning(
                    "trade_rejected_exposure",
                    current_exposure=current_exposure,
                    limit=self.limits.max_total_exposure_usd,
                )
                return result

            result["adjusted_size"] = max_allowed
            result["warnings"].append(f"Position reduced to ${max_allowed:.0f} (exposure limit)")
            position_size_usd = max_allowed

        # Check 8: Max open positions
        if len(self.open_positions) >= self.limits.max_open_positions:
            result["reason"] = f"Max open positions reached ({len(self.open_positions)} / {self.limits.max_open_positions})"
            logger.warning(
                "trade_rejected_max_positions",
                open_positions=len(self.open_positions),
                limit=self.limits.max_open_positions,
            )
            return result

        # Check 9: Duplicate market position
        for position in self.open_positions:
            if (position["kalshi_market_id"] == kalshi_market_id or
                position["polymarket_market_id"] == polymarket_market_id):
                result["reason"] = "Position already exists for this market"
                logger.warning(
                    "trade_rejected_duplicate",
                    kalshi_id=kalshi_market_id,
                    poly_id=polymarket_market_id,
                )
                return result

        # Check 10: Daily loss limit
        if self.daily_pnl < -self.limits.max_daily_loss_usd:
            result["reason"] = f"Daily loss limit reached (${self.daily_pnl:.0f} / -${self.limits.max_daily_loss_usd:.0f})"
            logger.warning(
                "trade_rejected_daily_loss",
                daily_pnl=self.daily_pnl,
                limit=-self.limits.max_daily_loss_usd,
            )
            return result

        # All checks passed
        result["approved"] = True
        result["reason"] = "All risk checks passed"
        result["adjusted_size"] = position_size_usd

        logger.info(
            "trade_approved",
            kalshi_id=kalshi_market_id,
            poly_id=polymarket_market_id,
            position_size=position_size_usd,
            tier=tier,
            profit_estimate=profit_estimate,
            warnings=result["warnings"],
        )

        return result

    def record_trade_opened(
        self,
        kalshi_market_id: str,
        polymarket_market_id: str,
        size_usd: float,
        expected_profit: float,
    ):
        """Record a new trade opening.

        Args:
            kalshi_market_id: Kalshi market ID
            polymarket_market_id: Polymarket market ID
            size_usd: Position size in USD
            expected_profit: Expected profit in USD
        """
        position = {
            "kalshi_market_id": kalshi_market_id,
            "polymarket_market_id": polymarket_market_id,
            "size_usd": size_usd,
            "expected_profit": expected_profit,
            "opened_at": datetime.utcnow(),
            "status": "open",
        }

        self.open_positions.append(position)
        self.daily_volume += size_usd

        logger.info(
            "trade_opened_recorded",
            kalshi_id=kalshi_market_id,
            poly_id=polymarket_market_id,
            size=size_usd,
            open_positions=len(self.open_positions),
            daily_volume=self.daily_volume,
        )

    def record_trade_closed(
        self,
        kalshi_market_id: str,
        polymarket_market_id: str,
        realized_pnl: float,
    ):
        """Record a trade closing.

        Args:
            kalshi_market_id: Kalshi market ID
            polymarket_market_id: Polymarket market ID
            realized_pnl: Realized profit/loss in USD
        """
        # Find and remove position
        for i, position in enumerate(self.open_positions):
            if (position["kalshi_market_id"] == kalshi_market_id and
                position["polymarket_market_id"] == polymarket_market_id):
                self.open_positions.pop(i)
                break

        self.daily_pnl += realized_pnl

        # Track losses for cooldown
        if realized_pnl < 0:
            self.last_loss_time = datetime.utcnow()
            logger.warning(
                "trade_loss_recorded",
                kalshi_id=kalshi_market_id,
                poly_id=polymarket_market_id,
                pnl=realized_pnl,
                daily_pnl=self.daily_pnl,
            )
        else:
            logger.info(
                "trade_profit_recorded",
                kalshi_id=kalshi_market_id,
                poly_id=polymarket_market_id,
                pnl=realized_pnl,
                daily_pnl=self.daily_pnl,
            )

    def get_risk_status(self) -> Dict[str, Any]:
        """Get current risk status.

        Returns:
            Dictionary with risk metrics
        """
        self.reset_daily_limits()

        current_exposure = sum(p["size_usd"] for p in self.open_positions)

        return {
            "daily_volume": self.daily_volume,
            "daily_volume_limit": self.limits.max_daily_volume_usd,
            "daily_volume_used_pct": (self.daily_volume / self.limits.max_daily_volume_usd) * 100,
            "daily_pnl": self.daily_pnl,
            "daily_loss_limit": -self.limits.max_daily_loss_usd,
            "current_exposure": current_exposure,
            "exposure_limit": self.limits.max_total_exposure_usd,
            "exposure_used_pct": (current_exposure / self.limits.max_total_exposure_usd) * 100,
            "open_positions": len(self.open_positions),
            "max_open_positions": self.limits.max_open_positions,
            "cooldown_active": bool(
                self.last_loss_time and
                (datetime.utcnow() - self.last_loss_time).total_seconds() <
                self.limits.cooldown_after_loss_seconds
            ),
            "last_reset": self.last_reset.isoformat(),
        }
