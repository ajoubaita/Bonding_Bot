"""Trade execution orchestration for arbitrage opportunities.

Coordinates risk management, order placement, and trade lifecycle.
"""

from typing import Dict, Any, Optional
from datetime import datetime
import structlog

from src.trading.risk_manager import RiskManager
from src.trading.order_manager import OrderManager, OrderSide
from src.models import Bond
from src.models import get_db

logger = structlog.get_logger()


class TradeExecutor:
    """Orchestrates trade execution with risk management and order placement."""

    def __init__(self, risk_manager: Optional[RiskManager] = None):
        """Initialize trade executor.

        Args:
            risk_manager: Custom risk manager (uses default if not provided)
        """
        self.risk_manager = risk_manager or RiskManager()
        self.order_manager = OrderManager()

        logger.info(
            "trade_executor_initialized",
            max_position=self.risk_manager.limits.max_position_size_usd,
            max_daily_volume=self.risk_manager.limits.max_daily_volume_usd,
        )

    def execute_arbitrage(
        self,
        bond_id: int,
        position_size_usd: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Execute arbitrage trade for a bonded market pair.

        This is the main entry point for executing arbitrage trades.
        It handles the full lifecycle:
        1. Validate bond has arbitrage opportunity
        2. Check risk limits
        3. Place orders on both platforms
        4. Track execution
        5. Update positions

        Args:
            bond_id: Database ID of the bond to trade
            position_size_usd: Override position size (uses max allowed if not provided)

        Returns:
            Dictionary with execution result:
            {
                "success": bool,
                "trade_id": str,
                "bond_id": int,
                "position_size": float,
                "expected_profit": float,
                "kalshi_order": dict,
                "polymarket_order": dict,
                "message": str,
                "warnings": list,
            }
        """
        result = {
            "success": False,
            "trade_id": None,
            "bond_id": bond_id,
            "position_size": 0.0,
            "expected_profit": 0.0,
            "kalshi_order": None,
            "polymarket_order": None,
            "message": "",
            "warnings": [],
        }

        try:
            # Step 1: Load bond from database
            db = next(get_db())
            bond = db.query(Bond).filter(Bond.id == bond_id).first()

            if not bond:
                result["message"] = f"Bond {bond_id} not found"
                logger.error("bond_not_found", bond_id=bond_id)
                return result

            # Step 2: Validate bond has arbitrage opportunity
            if not bond.arbitrage_metadata:
                result["message"] = "Bond has no arbitrage metadata"
                logger.warning("bond_no_arbitrage", bond_id=bond_id)
                return result

            arbitrage = bond.arbitrage_metadata
            if not arbitrage.get("has_arbitrage"):
                result["message"] = "Bond has no arbitrage opportunity"
                logger.info("bond_no_arbitrage_opportunity", bond_id=bond_id)
                return result

            # Extract arbitrage details
            arbitrage_type = arbitrage.get("arbitrage_type")
            profit_per_dollar = arbitrage.get("profit_per_dollar", 0.0)
            max_position = arbitrage.get("max_position_size", 0.0)
            kalshi_price = arbitrage.get("kalshi_price", 0.0)
            poly_price = arbitrage.get("polymarket_price", 0.0)

            # Determine position size
            if position_size_usd is None:
                position_size_usd = max_position

            # Step 3: Validate with risk manager
            risk_validation = self.risk_manager.validate_trade(
                position_size_usd=position_size_usd,
                profit_estimate=profit_per_dollar,
                tier=bond.tier,
                kalshi_market_id=bond.kalshi_market.id,
                polymarket_market_id=bond.polymarket_market.id,
            )

            if not risk_validation["approved"]:
                result["message"] = f"Risk check failed: {risk_validation['reason']}"
                result["warnings"] = risk_validation["warnings"]
                logger.warning(
                    "trade_rejected_risk",
                    bond_id=bond_id,
                    reason=risk_validation["reason"],
                )
                return result

            # Use adjusted size from risk manager
            approved_size = risk_validation["adjusted_size"]
            result["position_size"] = approved_size
            result["warnings"] = risk_validation["warnings"]

            # Calculate expected profit
            expected_profit = approved_size * profit_per_dollar
            result["expected_profit"] = expected_profit

            logger.info(
                "executing_arbitrage_trade",
                bond_id=bond_id,
                arbitrage_type=arbitrage_type,
                position_size=approved_size,
                expected_profit=expected_profit,
                tier=bond.tier,
            )

            # Step 4: Place orders on both platforms
            # Extract market IDs and token IDs
            kalshi_market_id = bond.kalshi_market.platform_id
            polymarket_token_id = self._get_polymarket_token_id(bond)

            if not polymarket_token_id:
                result["message"] = "Could not determine Polymarket token ID"
                logger.error("missing_poly_token_id", bond_id=bond_id)
                return result

            # Place orders
            order_result = self.order_manager.place_arbitrage_orders(
                kalshi_market_id=kalshi_market_id,
                polymarket_token_id=polymarket_token_id,
                arbitrage_type=arbitrage_type,
                position_size_usd=approved_size,
                kalshi_price=kalshi_price,
                polymarket_price=poly_price,
            )

            result["kalshi_order"] = order_result.get("kalshi_order")
            result["polymarket_order"] = order_result.get("polymarket_order")

            # Step 5: Check if both orders succeeded
            if order_result.get("success"):
                # Record trade with risk manager
                self.risk_manager.record_trade_opened(
                    kalshi_market_id=bond.kalshi_market.id,
                    polymarket_market_id=bond.polymarket_market.id,
                    size_usd=approved_size,
                    expected_profit=expected_profit,
                )

                # Generate trade ID
                trade_id = f"trade_{bond_id}_{int(datetime.utcnow().timestamp())}"
                result["trade_id"] = trade_id
                result["success"] = True
                result["message"] = "Trade executed successfully"

                logger.info(
                    "trade_executed_success",
                    trade_id=trade_id,
                    bond_id=bond_id,
                    position_size=approved_size,
                    expected_profit=expected_profit,
                )

            else:
                result["message"] = f"Order placement failed: {order_result.get('message')}"
                logger.error(
                    "trade_execution_failed",
                    bond_id=bond_id,
                    order_message=order_result.get("message"),
                )

        except Exception as e:
            result["message"] = f"Trade execution error: {str(e)}"
            logger.error(
                "trade_execution_exception",
                bond_id=bond_id,
                error=str(e),
            )

        return result

    def close_trade(
        self,
        trade_id: str,
        realized_pnl: float,
        kalshi_market_id: str,
        polymarket_market_id: str,
    ):
        """Record trade closure and realized P&L.

        Args:
            trade_id: Trade identifier
            realized_pnl: Actual profit/loss in USD
            kalshi_market_id: Kalshi market ID
            polymarket_market_id: Polymarket market ID
        """
        try:
            self.risk_manager.record_trade_closed(
                kalshi_market_id=kalshi_market_id,
                polymarket_market_id=polymarket_market_id,
                realized_pnl=realized_pnl,
            )

            logger.info(
                "trade_closed",
                trade_id=trade_id,
                realized_pnl=realized_pnl,
                kalshi_id=kalshi_market_id,
                poly_id=polymarket_market_id,
            )

        except Exception as e:
            logger.error(
                "trade_close_error",
                trade_id=trade_id,
                error=str(e),
            )

    def get_trading_status(self) -> Dict[str, Any]:
        """Get current trading system status.

        Returns:
            Dictionary with system status and risk metrics
        """
        risk_status = self.risk_manager.get_risk_status()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "risk_status": risk_status,
            "order_manager": {
                "kalshi_api_configured": bool(self.order_manager.kalshi_api_key),
                "polymarket_api_configured": bool(self.order_manager.polymarket_api_key),
            },
            "limits": {
                "max_position_size": self.risk_manager.limits.max_position_size_usd,
                "max_daily_volume": self.risk_manager.limits.max_daily_volume_usd,
                "max_total_exposure": self.risk_manager.limits.max_total_exposure_usd,
                "tier1_max_position": self.risk_manager.limits.tier1_max_position_usd,
                "tier2_max_position": self.risk_manager.limits.tier2_max_position_usd,
            },
        }

    def _get_polymarket_token_id(self, bond: Bond) -> Optional[str]:
        """Extract Polymarket token ID from bond.

        Args:
            bond: Bond object

        Returns:
            Token ID or None if not found
        """
        try:
            # Check if polymarket market has outcome_schema
            poly_market = bond.polymarket_market
            if not poly_market.outcome_schema:
                return None

            # Get YES outcome token ID (for binary markets)
            outcomes = poly_market.outcome_schema.get("outcomes", [])
            for outcome in outcomes:
                if outcome.get("value") is True:  # YES outcome
                    return outcome.get("token_id")

            # If no YES outcome, use first outcome
            if outcomes:
                return outcomes[0].get("token_id")

            return None

        except Exception as e:
            logger.error(
                "token_id_extraction_error",
                bond_id=bond.id,
                error=str(e),
            )
            return None

    def execute_tier1_bonds(self, limit: int = 10) -> Dict[str, Any]:
        """Auto-execute all Tier 1 bonds with arbitrage opportunities.

        This method scans for Tier 1 bonds (highest confidence matches) that
        have profitable arbitrage opportunities and executes them automatically.

        Args:
            limit: Maximum number of trades to execute (default 10)

        Returns:
            Summary of execution results
        """
        results = {
            "total_scanned": 0,
            "total_executed": 0,
            "total_rejected": 0,
            "trades": [],
            "errors": [],
        }

        try:
            # Query Tier 1 bonds with arbitrage opportunities
            db = next(get_db())
            bonds = (
                db.query(Bond)
                .filter(Bond.tier == 1)
                .filter(Bond.arbitrage_metadata.isnot(None))
                .limit(limit)
                .all()
            )

            results["total_scanned"] = len(bonds)

            for bond in bonds:
                # Check if bond has arbitrage
                arbitrage = bond.arbitrage_metadata or {}
                if not arbitrage.get("has_arbitrage"):
                    continue

                # Execute trade
                trade_result = self.execute_arbitrage(bond_id=bond.id)

                if trade_result["success"]:
                    results["total_executed"] += 1
                    results["trades"].append({
                        "bond_id": bond.id,
                        "trade_id": trade_result["trade_id"],
                        "position_size": trade_result["position_size"],
                        "expected_profit": trade_result["expected_profit"],
                    })
                else:
                    results["total_rejected"] += 1
                    results["errors"].append({
                        "bond_id": bond.id,
                        "reason": trade_result["message"],
                    })

            logger.info(
                "tier1_auto_execution_complete",
                scanned=results["total_scanned"],
                executed=results["total_executed"],
                rejected=results["total_rejected"],
            )

        except Exception as e:
            logger.error(
                "tier1_auto_execution_error",
                error=str(e),
            )
            results["errors"].append({
                "error": str(e),
            })

        return results
