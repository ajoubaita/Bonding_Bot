"""Bond validation worker for post-resolution accuracy tracking."""

from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import structlog

from src.models import Bond, Market, get_db
from src.utils.metrics import record_bond_validation, get_metrics
from src.ingestion.kalshi_client import KalshiClient
from src.ingestion.polymarket_client import PolymarketClient

logger = structlog.get_logger()


class BondValidator:
    """Validator for checking bond accuracy after resolution."""

    def __init__(self):
        """Initialize bond validator."""
        self.kalshi_client = KalshiClient()
        self.poly_client = PolymarketClient()

    def get_market_resolution(self, market_id: str, platform: str) -> Optional[Dict[str, Any]]:
        """Get resolution result for a market.

        Args:
            market_id: Market ID
            platform: Platform ("kalshi" or "polymarket")

        Returns:
            Resolution data or None
        """
        try:
            if platform == "kalshi":
                market_data = self.kalshi_client.get_market(market_id)
                result = market_data.get("result")

                if result:
                    return {
                        "resolved": True,
                        "outcome": "yes" if result.lower() == "yes" else "no",
                        "settlement_value": result,
                    }

            elif platform == "polymarket":
                # Check CLOB for resolution
                simplified_markets = self.poly_client.clob.get_simplified_markets()

                for market in simplified_markets:
                    if market.get("condition_id") == market_id:
                        if market.get("closed"):
                            # Find winning outcome
                            for token in market.get("tokens", []):
                                if token.get("winner"):
                                    return {
                                        "resolved": True,
                                        "outcome": token.get("outcome", "").lower(),
                                        "settlement_value": token.get("outcome"),
                                    }

        except Exception as e:
            logger.error(
                "get_market_resolution_failed",
                market_id=market_id,
                platform=platform,
                error=str(e),
            )

        return None

    def validate_bond(self, bond: Bond, db: Session) -> Dict[str, Any]:
        """Validate a single bond by checking if outcomes matched.

        Args:
            bond: Bond to validate
            db: Database session

        Returns:
            Validation result
        """
        logger.info("validate_bond_start", pair_id=bond.pair_id)

        # Get markets
        kalshi_market = db.query(Market).filter(Market.id == bond.kalshi_market_id).first()
        poly_market = db.query(Market).filter(Market.id == bond.polymarket_market_id).first()

        if not kalshi_market or not poly_market:
            logger.error("validate_bond_markets_not_found", pair_id=bond.pair_id)
            return {"error": "Markets not found"}

        # Get resolutions
        kalshi_resolution = self.get_market_resolution(bond.kalshi_market_id, "kalshi")
        poly_resolution = self.get_market_resolution(bond.polymarket_market_id, "polymarket")

        if not kalshi_resolution or not poly_resolution:
            logger.info(
                "validate_bond_not_resolved",
                pair_id=bond.pair_id,
                kalshi_resolved=kalshi_resolution is not None,
                poly_resolved=poly_resolution is not None,
            )
            return {
                "validated": False,
                "reason": "Not all markets resolved",
            }

        # Check if outcomes match
        kalshi_outcome = kalshi_resolution.get("outcome", "").lower()
        poly_outcome = poly_resolution.get("outcome", "").lower()

        # Map outcomes using outcome_mapping
        outcome_mapping = bond.outcome_mapping

        # Check if they match based on mapping
        matches = False
        if kalshi_outcome == "yes" and poly_outcome == "yes":
            matches = True
        elif kalshi_outcome == "no" and poly_outcome == "no":
            matches = True

        # Record validation
        record_bond_validation(bond.tier, success=matches)

        result = {
            "validated": True,
            "pair_id": bond.pair_id,
            "tier": bond.tier,
            "p_match": bond.p_match,
            "kalshi_outcome": kalshi_outcome,
            "poly_outcome": poly_outcome,
            "outcomes_match": matches,
            "kalshi_settlement": kalshi_resolution.get("settlement_value"),
            "poly_settlement": poly_resolution.get("settlement_value"),
        }

        logger.info(
            "validate_bond_complete",
            pair_id=bond.pair_id,
            tier=bond.tier,
            outcomes_match=matches,
        )

        # If mismatch on Tier 1, this is CRITICAL
        if bond.tier == 1 and not matches:
            logger.critical(
                "TIER_1_BOND_MISMATCH",
                pair_id=bond.pair_id,
                p_match=bond.p_match,
                kalshi_outcome=kalshi_outcome,
                poly_outcome=poly_outcome,
                feature_breakdown=bond.feature_breakdown,
            )

        return result

    def validate_all_resolved_bonds(self, lookback_days: int = 7) -> List[Dict[str, Any]]:
        """Validate all bonds for markets resolved in the last N days.

        Args:
            lookback_days: Number of days to look back

        Returns:
            List of validation results
        """
        logger.info("validate_all_resolved_bonds_start", lookback_days=lookback_days)

        results = []
        cutoff_date = datetime.utcnow() - timedelta(days=lookback_days)

        db = next(get_db())

        try:
            # Get all active bonds
            bonds = db.query(Bond).filter(
                Bond.status == "active",
                Bond.created_at >= cutoff_date,
            ).all()

            logger.info("validate_all_resolved_bonds_found", count=len(bonds))

            for bond in bonds:
                try:
                    result = self.validate_bond(bond, db)
                    results.append(result)

                    # If validated, update bond status
                    if result.get("validated"):
                        bond.status = "validated"
                        bond.last_validated = datetime.utcnow()
                        db.commit()

                except Exception as e:
                    logger.error(
                        "validate_bond_failed",
                        pair_id=bond.pair_id,
                        error=str(e),
                    )

        finally:
            db.close()

        # Calculate accuracy metrics
        validated = [r for r in results if r.get("validated")]
        matched = [r for r in validated if r.get("outcomes_match")]

        accuracy = len(matched) / len(validated) if validated else 0.0

        logger.info(
            "validate_all_resolved_bonds_complete",
            total_bonds=len(bonds),
            validated=len(validated),
            matched=len(matched),
            accuracy=accuracy,
        )

        # Store accuracy metric
        metrics = get_metrics()
        metrics.record_gauge("bond_validation_accuracy", accuracy)

        return results

    def get_validation_report(self) -> Dict[str, Any]:
        """Get validation accuracy report.

        Returns:
            Validation report with metrics
        """
        metrics = get_metrics()

        tier1_success = metrics.get_counter("bonds_validated_total", {"tier": "1", "success": "true"})
        tier1_failure = metrics.get_counter("bonds_validated_total", {"tier": "1", "success": "false"})
        tier2_success = metrics.get_counter("bonds_validated_total", {"tier": "2", "success": "true"})
        tier2_failure = metrics.get_counter("bonds_validated_total", {"tier": "2", "success": "false"})

        tier1_total = tier1_success + tier1_failure
        tier2_total = tier2_success + tier2_failure

        tier1_accuracy = tier1_success / tier1_total if tier1_total > 0 else 0.0
        tier2_accuracy = tier2_success / tier2_total if tier2_total > 0 else 0.0

        report = {
            "tier1": {
                "total_validated": tier1_total,
                "successful": tier1_success,
                "failed": tier1_failure,
                "accuracy": tier1_accuracy,
                "target_accuracy": 0.995,  # 99.5% target
                "meets_target": tier1_accuracy >= 0.995,
            },
            "tier2": {
                "total_validated": tier2_total,
                "successful": tier2_success,
                "failed": tier2_failure,
                "accuracy": tier2_accuracy,
                "target_accuracy": 0.95,  # 95% target
                "meets_target": tier2_accuracy >= 0.95,
            },
            "overall_accuracy": metrics.get_gauge("bond_validation_accuracy"),
            "timestamp": datetime.utcnow().isoformat(),
        }

        logger.info(
            "validation_report_generated",
            tier1_accuracy=tier1_accuracy,
            tier2_accuracy=tier2_accuracy,
            tier1_meets_target=report["tier1"]["meets_target"],
        )

        return report

    def close(self):
        """Close API clients."""
        self.kalshi_client.close()
        self.poly_client.close()
