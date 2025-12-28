"""Arbitrage opportunity monitoring and ranking system.

Tracks active arbitrage opportunities, ranks by profit potential, and
provides continuous monitoring of the most profitable markets.

Monitors THREE types of arbitrage on bonded markets:
1. Cross-platform: Kalshi vs Polymarket price differences
2. Intra-platform Kalshi: Kalshi YES + NO < $1.00
3. Intra-platform Polymarket: Polymarket YES + NO < $1.00
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
import structlog
from sqlalchemy.orm import Session

from src.models import Bond, Market, get_db
from src.utils.arbitrage import calculate_arbitrage_opportunity
from src.trading.intra_platform_arbitrage import IntraPlatformArbitrageScanner

logger = structlog.get_logger()


@dataclass
class ArbitrageOpportunity:
    """Data class for tracked arbitrage opportunity."""

    bond_id: str  # pair_id (string)
    kalshi_market_id: str
    polymarket_market_id: str
    kalshi_platform_id: str
    polymarket_platform_id: str

    # Arbitrage details
    arbitrage_type: str
    profit_per_dollar: float
    kalshi_price: float
    polymarket_price: float
    max_position_size: float

    # Market metadata
    min_volume: float
    min_liquidity: float
    tier: int

    # Monitoring metadata
    first_detected: datetime
    last_updated: datetime
    price_update_count: int

    # Risk factors
    warnings: List[str]
    price_age_kalshi_sec: Optional[int]
    price_age_poly_sec: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        data = asdict(self)
        # Convert datetime to ISO format
        data["first_detected"] = self.first_detected.isoformat()
        data["last_updated"] = self.last_updated.isoformat()
        return data

    @property
    def estimated_profit_usd(self) -> float:
        """Estimated profit in USD for max position size."""
        return self.max_position_size * self.profit_per_dollar

    @property
    def age_minutes(self) -> float:
        """Age of opportunity in minutes."""
        return (datetime.utcnow() - self.first_detected).total_seconds() / 60

    @property
    def is_stale(self) -> bool:
        """Check if opportunity data is stale (>5 minutes since last update)."""
        return (datetime.utcnow() - self.last_updated).total_seconds() > 300


class ArbitrageMonitor:
    """Monitors and ranks arbitrage opportunities across all bonded markets."""

    def __init__(self, max_opportunities: int = 100):
        """Initialize arbitrage monitor.

        Args:
            max_opportunities: Maximum number of opportunities to track
        """
        self.max_opportunities = max_opportunities
        self.opportunities: Dict[str, ArbitrageOpportunity] = {}  # Keyed by pair_id (string)
        self.last_scan: Optional[datetime] = None

        logger.info(
            "arbitrage_monitor_initialized",
            max_opportunities=max_opportunities,
        )

    def scan_for_opportunities(
        self,
        tier_filter: Optional[int] = None,
        min_profit_threshold: float = 0.01,
    ) -> List[ArbitrageOpportunity]:
        """Scan all bonds for arbitrage opportunities.

        Args:
            tier_filter: Only scan bonds of specific tier (None = all tiers)
            min_profit_threshold: Minimum profit per dollar to track (default 1%)

        Returns:
            List of discovered opportunities sorted by profit
        """
        db = next(get_db())

        try:
            # Query all active bonds
            # Note: arbitrage_metadata doesn't exist on Bond model
            # We'll calculate arbitrage on the fly or store in a separate table
            query = (
                db.query(Bond)
                .filter(Bond.status == "active")
            )

            if tier_filter is not None:
                query = query.filter(Bond.tier == tier_filter)

            bonds = query.all()

            discovered = []
            updated = 0
            new = 0

            for bond in bonds:
                # Get markets for this bond
                kalshi_market = db.query(Market).filter(Market.id == bond.kalshi_market_id).first()
                poly_market = db.query(Market).filter(Market.id == bond.polymarket_market_id).first()
                
                if not kalshi_market or not poly_market:
                    continue
                
                # Calculate arbitrage opportunity on the fly
                from src.utils.arbitrage import calculate_arbitrage_opportunity
                arbitrage = calculate_arbitrage_opportunity(
                    kalshi_market,
                    poly_market,
                    bond.outcome_mapping
                )

                # Skip if no arbitrage or below threshold
                if not arbitrage.get("has_arbitrage"):
                    # Remove from tracking if it was there
                    if bond.pair_id in self.opportunities:
                        del self.opportunities[bond.pair_id]
                    continue

                profit = arbitrage.get("profit_per_dollar", 0.0)
                if profit < min_profit_threshold:
                    if bond.pair_id in self.opportunities:
                        del self.opportunities[bond.pair_id]
                    continue

                # Create or update opportunity
                now = datetime.utcnow()

                if bond.pair_id in self.opportunities:
                    # Update existing opportunity
                    opp = self.opportunities[bond.pair_id]
                    opp.profit_per_dollar = profit
                    opp.kalshi_price = arbitrage.get("kalshi_price", 0.0)
                    opp.polymarket_price = arbitrage.get("polymarket_price", 0.0)
                    opp.max_position_size = arbitrage.get("max_position_size", 0.0)
                    opp.min_volume = arbitrage.get("min_volume", 0.0)
                    opp.min_liquidity = arbitrage.get("min_liquidity", 0.0)
                    opp.warnings = arbitrage.get("warnings", [])
                    opp.price_age_kalshi_sec = arbitrage.get("price_age_kalshi_sec")
                    opp.price_age_poly_sec = arbitrage.get("price_age_poly_sec")
                    opp.last_updated = now
                    opp.price_update_count += 1
                    updated += 1
                else:
                        # Create new opportunity
                    opp = ArbitrageOpportunity(
                        bond_id=bond.pair_id,  # Use pair_id as bond identifier
                        kalshi_market_id=bond.kalshi_market_id,
                        polymarket_market_id=bond.polymarket_market_id,
                        kalshi_platform_id=kalshi_market.id if kalshi_market else bond.kalshi_market_id,
                        polymarket_platform_id=poly_market.condition_id if poly_market and poly_market.condition_id else bond.polymarket_market_id,
                        arbitrage_type=arbitrage.get("arbitrage_type", ""),
                        profit_per_dollar=profit,
                        kalshi_price=arbitrage.get("kalshi_price", 0.0),
                        polymarket_price=arbitrage.get("polymarket_price", 0.0),
                        max_position_size=arbitrage.get("max_position_size", 0.0),
                        min_volume=arbitrage.get("min_volume", 0.0),
                        min_liquidity=arbitrage.get("min_liquidity", 0.0),
                        tier=bond.tier,
                        first_detected=now,
                        last_updated=now,
                        price_update_count=1,
                        warnings=arbitrage.get("warnings", []),
                        price_age_kalshi_sec=arbitrage.get("price_age_kalshi_sec"),
                        price_age_poly_sec=arbitrage.get("price_age_poly_sec"),
                    )
                    self.opportunities[bond.pair_id] = opp
                    new += 1

                discovered.append(opp)

            # Sort by estimated profit (descending)
            discovered.sort(key=lambda x: x.estimated_profit_usd, reverse=True)

            # Limit to max opportunities
            if len(self.opportunities) > self.max_opportunities:
                # Keep only the most profitable ones
                sorted_opps = sorted(
                    self.opportunities.values(),
                    key=lambda x: x.estimated_profit_usd,
                    reverse=True
                )

                # Remove least profitable
                to_remove = sorted_opps[self.max_opportunities:]
                for opp in to_remove:
                    del self.opportunities[opp.bond_id]

            self.last_scan = datetime.utcnow()

            logger.info(
                "arbitrage_scan_complete",
                total_bonds=len(bonds),
                discovered=len(discovered),
                new=new,
                updated=updated,
                tracking=len(self.opportunities),
            )

            return discovered

        except Exception as e:
            logger.error(
                "arbitrage_scan_error",
                error=str(e),
            )
            return []

    def scan_for_all_opportunities(
        self,
        tier_filter: Optional[int] = None,
        min_profit_threshold: float = 0.01,
    ) -> Dict[str, List]:
        """Scan all bonded markets for ALL three types of arbitrage.

        For each bonded market pair, checks:
        1. Cross-platform arbitrage (Kalshi vs Polymarket)
        2. Intra-platform arbitrage on Kalshi side (YES + NO < $1)
        3. Intra-platform arbitrage on Polymarket side (YES + NO < $1)

        This is efficient because we're already monitoring these markets
        with priority price updates.

        Args:
            tier_filter: Only scan bonds of specific tier (None = all tiers)
            min_profit_threshold: Minimum profit per dollar to track (default 1%)

        Returns:
            Dictionary with three lists:
            {
                "cross_platform": [ArbitrageOpportunity, ...],
                "intra_kalshi": [IntraPlatformOpportunity, ...],
                "intra_polymarket": [IntraPlatformOpportunity, ...]
            }
        """
        db = next(get_db())
        intra_scanner = IntraPlatformArbitrageScanner()

        try:
            # Query all active bonds
            query = (
                db.query(Bond)
                .filter(Bond.status == "active")
            )

            if tier_filter is not None:
                query = query.filter(Bond.tier == tier_filter)

            bonds = query.all()

            # Results containers
            cross_platform_opps = []
            intra_kalshi_opps = []
            intra_poly_opps = []

            for bond in bonds:
                # Get markets for this bond
                kalshi_market = db.query(Market).filter(Market.id == bond.kalshi_market_id).first()
                poly_market = db.query(Market).filter(Market.id == bond.polymarket_market_id).first()

                if not kalshi_market or not poly_market:
                    continue

                # 1. Check cross-platform arbitrage
                arbitrage = calculate_arbitrage_opportunity(
                    kalshi_market,
                    poly_market,
                    bond.outcome_mapping
                )

                if arbitrage.get("has_arbitrage"):
                    profit = arbitrage.get("profit_per_dollar", 0.0)
                    if profit >= min_profit_threshold:
                        now = datetime.utcnow()

                        # Update or create cross-platform opportunity
                        if bond.pair_id in self.opportunities:
                            opp = self.opportunities[bond.pair_id]
                            opp.profit_per_dollar = profit
                            opp.kalshi_price = arbitrage.get("kalshi_price", 0.0)
                            opp.polymarket_price = arbitrage.get("polymarket_price", 0.0)
                            opp.max_position_size = arbitrage.get("max_position_size", 0.0)
                            opp.min_volume = arbitrage.get("min_volume", 0.0)
                            opp.min_liquidity = arbitrage.get("min_liquidity", 0.0)
                            opp.warnings = arbitrage.get("warnings", [])
                            opp.price_age_kalshi_sec = arbitrage.get("price_age_kalshi_sec")
                            opp.price_age_poly_sec = arbitrage.get("price_age_poly_sec")
                            opp.last_updated = now
                            opp.price_update_count += 1
                        else:
                            opp = ArbitrageOpportunity(
                                bond_id=bond.pair_id,
                                kalshi_market_id=bond.kalshi_market_id,
                                polymarket_market_id=bond.polymarket_market_id,
                                kalshi_platform_id=kalshi_market.id if kalshi_market else bond.kalshi_market_id,
                                polymarket_platform_id=poly_market.condition_id if poly_market and poly_market.condition_id else bond.polymarket_market_id,
                                arbitrage_type=arbitrage.get("arbitrage_type", ""),
                                profit_per_dollar=profit,
                                kalshi_price=arbitrage.get("kalshi_price", 0.0),
                                polymarket_price=arbitrage.get("polymarket_price", 0.0),
                                max_position_size=arbitrage.get("max_position_size", 0.0),
                                min_volume=arbitrage.get("min_volume", 0.0),
                                min_liquidity=arbitrage.get("min_liquidity", 0.0),
                                tier=bond.tier,
                                first_detected=now,
                                last_updated=now,
                                price_update_count=1,
                                warnings=arbitrage.get("warnings", []),
                                price_age_kalshi_sec=arbitrage.get("price_age_kalshi_sec"),
                                price_age_poly_sec=arbitrage.get("price_age_poly_sec"),
                            )
                            self.opportunities[bond.pair_id] = opp

                        cross_platform_opps.append(opp)
                else:
                    # Remove from tracking if no longer has arbitrage
                    if bond.pair_id in self.opportunities:
                        del self.opportunities[bond.pair_id]

                # 2. Check Kalshi intra-platform arbitrage
                kalshi_intra = intra_scanner.scan_market(kalshi_market)
                if kalshi_intra and kalshi_intra.profit_per_dollar >= min_profit_threshold:
                    intra_kalshi_opps.append(kalshi_intra)

                # 3. Check Polymarket intra-platform arbitrage
                poly_intra = intra_scanner.scan_market(poly_market)
                if poly_intra and poly_intra.profit_per_dollar >= min_profit_threshold:
                    intra_poly_opps.append(poly_intra)

            # Sort all by profit
            cross_platform_opps.sort(key=lambda x: x.estimated_profit_usd, reverse=True)
            intra_kalshi_opps.sort(key=lambda x: x.profit_per_dollar, reverse=True)
            intra_poly_opps.sort(key=lambda x: x.profit_per_dollar, reverse=True)

            logger.info(
                "comprehensive_arbitrage_scan_complete",
                total_bonds=len(bonds),
                cross_platform=len(cross_platform_opps),
                intra_kalshi=len(intra_kalshi_opps),
                intra_polymarket=len(intra_poly_opps),
                total_opportunities=len(cross_platform_opps) + len(intra_kalshi_opps) + len(intra_poly_opps),
            )

            return {
                "cross_platform": cross_platform_opps,
                "intra_kalshi": intra_kalshi_opps,
                "intra_polymarket": intra_poly_opps,
            }

        except Exception as e:
            logger.error(
                "comprehensive_arbitrage_scan_error",
                error=str(e),
            )
            return {
                "cross_platform": [],
                "intra_kalshi": [],
                "intra_polymarket": [],
            }

    def get_top_opportunities(
        self,
        limit: int = 10,
        tier_filter: Optional[int] = None,
        min_age_minutes: float = 0,
    ) -> List[ArbitrageOpportunity]:
        """Get top arbitrage opportunities ranked by profit.

        Args:
            limit: Maximum number of opportunities to return
            tier_filter: Filter by tier (None = all tiers)
            min_age_minutes: Minimum age to include (filter out very new opportunities)

        Returns:
            List of top opportunities sorted by estimated profit
        """
        opportunities = list(self.opportunities.values())

        # Apply filters
        if tier_filter is not None:
            opportunities = [o for o in opportunities if o.tier == tier_filter]

        if min_age_minutes > 0:
            opportunities = [o for o in opportunities if o.age_minutes >= min_age_minutes]

        # Sort by estimated profit
        opportunities.sort(key=lambda x: x.estimated_profit_usd, reverse=True)

        return opportunities[:limit]

    def get_opportunity(self, bond_id: str) -> Optional[ArbitrageOpportunity]:
        """Get specific opportunity by bond ID.

        Args:
            bond_id: Bond pair_id to lookup

        Returns:
            ArbitrageOpportunity or None if not found
        """
        return self.opportunities.get(bond_id)

    def remove_stale_opportunities(self, max_age_minutes: float = 10) -> int:
        """Remove opportunities that haven't been updated recently.

        Args:
            max_age_minutes: Maximum age since last update

        Returns:
            Number of opportunities removed
        """
        now = datetime.utcnow()
        to_remove = []

        for bond_id, opp in self.opportunities.items():
            age = (now - opp.last_updated).total_seconds() / 60
            if age > max_age_minutes:
                to_remove.append(bond_id)

        for bond_id in to_remove:
            del self.opportunities[bond_id]

        if to_remove:
            logger.info(
                "stale_opportunities_removed",
                count=len(to_remove),
                max_age_minutes=max_age_minutes,
            )

        return len(to_remove)

    def get_monitoring_stats(self) -> Dict[str, Any]:
        """Get monitoring statistics.

        Returns:
            Dictionary with monitoring stats
        """
        opportunities = list(self.opportunities.values())

        if not opportunities:
            return {
                "total_opportunities": 0,
                "tier1_count": 0,
                "tier2_count": 0,
                "tier3_count": 0,
                "total_estimated_profit": 0.0,
                "avg_profit_per_dollar": 0.0,
                "last_scan": None,
            }

        tier1 = [o for o in opportunities if o.tier == 1]
        tier2 = [o for o in opportunities if o.tier == 2]
        tier3 = [o for o in opportunities if o.tier == 3]

        total_profit = sum(o.estimated_profit_usd for o in opportunities)
        avg_profit = sum(o.profit_per_dollar for o in opportunities) / len(opportunities)

        return {
            "total_opportunities": len(opportunities),
            "tier1_count": len(tier1),
            "tier2_count": len(tier2),
            "tier3_count": len(tier3),
            "total_estimated_profit": total_profit,
            "avg_profit_per_dollar": avg_profit,
            "top_opportunity_profit": opportunities[0].estimated_profit_usd if opportunities else 0.0,
            "last_scan": self.last_scan.isoformat() if self.last_scan else None,
        }

    def get_markets_to_monitor(self, limit: int = 50) -> Dict[str, List[str]]:
        """Get market IDs that should be monitored with priority.

        This returns the platform-specific IDs of the markets with the
        best arbitrage opportunities, so the price_updater can prioritize them.

        Args:
            limit: Maximum number of market pairs to return

        Returns:
            Dictionary with kalshi and polymarket platform IDs:
            {
                "kalshi_ids": ["market1", "market2", ...],
                "polymarket_ids": ["market3", "market4", ...]
            }
        """
        # Get top opportunities
        top = self.get_top_opportunities(limit=limit)

        kalshi_ids = []
        polymarket_ids = []

        for opp in top:
            if opp.kalshi_platform_id:
                kalshi_ids.append(opp.kalshi_platform_id)
            if opp.polymarket_platform_id:
                polymarket_ids.append(opp.polymarket_platform_id)

        logger.debug(
            "priority_markets_identified",
            kalshi_count=len(kalshi_ids),
            polymarket_count=len(polymarket_ids),
        )

        return {
            "kalshi_ids": kalshi_ids,
            "polymarket_ids": polymarket_ids,
        }


# Global monitor instance
_global_monitor: Optional[ArbitrageMonitor] = None


def get_monitor() -> ArbitrageMonitor:
    """Get global arbitrage monitor instance.

    Returns:
        ArbitrageMonitor singleton instance
    """
    global _global_monitor

    if _global_monitor is None:
        _global_monitor = ArbitrageMonitor(max_opportunities=100)

    return _global_monitor
