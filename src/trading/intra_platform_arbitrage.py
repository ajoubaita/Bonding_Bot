"""Intra-platform arbitrage detection.

Detects arbitrage opportunities within a single exchange where yes + no prices < $1.
This indicates a market inefficiency that can be exploited for risk-free profit.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import structlog

from src.models import Market

logger = structlog.get_logger()


@dataclass
class IntraPlatformOpportunity:
    """Represents an intra-platform arbitrage opportunity."""

    platform: str  # 'kalshi' or 'polymarket'
    market_id: str
    market_title: str
    yes_price: float
    no_price: float
    price_sum: float
    arbitrage_gap: float  # How much less than $1 (1.00 - price_sum)
    profit_per_dollar: float  # Profit percentage

    # Market metadata
    category: Optional[str] = None
    volume: float = 0.0
    liquidity: float = 0.0
    expires_at: Optional[datetime] = None
    last_updated: Optional[datetime] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary for API response."""
        return {
            "platform": self.platform,
            "market_id": self.market_id,
            "market_title": self.market_title,
            "prices": {
                "yes": round(self.yes_price, 4),
                "no": round(self.no_price, 4),
                "sum": round(self.price_sum, 4),
            },
            "arbitrage": {
                "gap": round(self.arbitrage_gap, 4),
                "profit_per_dollar": round(self.profit_per_dollar, 4),
                "profit_pct": round(self.profit_per_dollar * 100, 2),
            },
            "metadata": {
                "category": self.category,
                "volume": round(self.volume, 2) if self.volume else 0,
                "liquidity": round(self.liquidity, 2) if self.liquidity else 0,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            },
            "strategy": {
                "action": "BUY_BOTH",
                "description": f"Buy YES at ${self.yes_price:.4f} + NO at ${self.no_price:.4f} = ${self.price_sum:.4f} total cost. Guaranteed payout = $1.00. Profit = ${self.arbitrage_gap:.4f} per pair.",
                "risk_level": "ZERO",  # Risk-free arbitrage
            }
        }


class IntraPlatformArbitrageScanner:
    """Scanner for intra-platform arbitrage opportunities."""

    def __init__(self):
        self.logger = structlog.get_logger()

    def scan_market(self, market: Market) -> Optional[IntraPlatformOpportunity]:
        """Scan a single market for intra-platform arbitrage.

        Args:
            market: Market object with yes/no prices

        Returns:
            IntraPlatformOpportunity if arbitrage exists, None otherwise
        """
        # Extract prices
        yes_price = market.yes_price
        no_price = market.no_price

        # Validate prices
        if yes_price is None or no_price is None:
            self.logger.debug(
                "intra_arb_missing_prices",
                market_id=market.market_id,
                platform=market.platform,
            )
            return None

        if yes_price <= 0 or no_price <= 0:
            self.logger.debug(
                "intra_arb_invalid_prices",
                market_id=market.market_id,
                platform=market.platform,
                yes_price=yes_price,
                no_price=no_price,
            )
            return None

        # Calculate price sum
        price_sum = yes_price + no_price

        # Check for arbitrage (sum < $1)
        if price_sum >= 1.0:
            # No arbitrage opportunity
            return None

        # Calculate arbitrage metrics
        arbitrage_gap = 1.0 - price_sum
        profit_per_dollar = arbitrage_gap / price_sum if price_sum > 0 else 0

        self.logger.info(
            "intra_platform_arbitrage_found",
            platform=market.platform,
            market_id=market.market_id,
            yes_price=yes_price,
            no_price=no_price,
            price_sum=price_sum,
            arbitrage_gap=arbitrage_gap,
            profit_pct=round(profit_per_dollar * 100, 2),
        )

        return IntraPlatformOpportunity(
            platform=market.platform,
            market_id=market.market_id,
            market_title=market.title or "Unknown Market",
            yes_price=yes_price,
            no_price=no_price,
            price_sum=price_sum,
            arbitrage_gap=arbitrage_gap,
            profit_per_dollar=profit_per_dollar,
            category=market.category,
            volume=market.volume or 0.0,
            liquidity=market.liquidity or 0.0,
            expires_at=market.close_time,
            last_updated=market.updated_at,
        )

    def scan_markets(
        self,
        markets: List[Market],
        min_profit_threshold: float = 0.0,
        platform_filter: Optional[str] = None,
    ) -> List[IntraPlatformOpportunity]:
        """Scan multiple markets for intra-platform arbitrage.

        Args:
            markets: List of markets to scan
            min_profit_threshold: Minimum profit percentage to include (default 0 = any profit)
            platform_filter: Filter by platform ('kalshi' or 'polymarket', default all)

        Returns:
            List of arbitrage opportunities, sorted by profit descending
        """
        opportunities = []

        for market in markets:
            # Apply platform filter
            if platform_filter and market.platform != platform_filter:
                continue

            # Scan for arbitrage
            opp = self.scan_market(market)

            if opp and opp.profit_per_dollar >= min_profit_threshold:
                opportunities.append(opp)

        # Sort by profit percentage descending
        opportunities.sort(key=lambda x: x.profit_per_dollar, reverse=True)

        self.logger.info(
            "intra_platform_scan_complete",
            total_markets=len(markets),
            opportunities_found=len(opportunities),
            platform_filter=platform_filter,
            min_profit_threshold=min_profit_threshold,
        )

        return opportunities

    def get_statistics(
        self,
        opportunities: List[IntraPlatformOpportunity]
    ) -> Dict:
        """Get statistics about discovered opportunities.

        Args:
            opportunities: List of opportunities

        Returns:
            Statistics dictionary
        """
        if not opportunities:
            return {
                "total_opportunities": 0,
                "by_platform": {"kalshi": 0, "polymarket": 0},
                "avg_profit_pct": 0.0,
                "max_profit_pct": 0.0,
                "total_arbitrage_gap": 0.0,
            }

        kalshi_count = sum(1 for opp in opportunities if opp.platform == 'kalshi')
        poly_count = sum(1 for opp in opportunities if opp.platform == 'polymarket')

        profits = [opp.profit_per_dollar for opp in opportunities]
        gaps = [opp.arbitrage_gap for opp in opportunities]

        return {
            "total_opportunities": len(opportunities),
            "by_platform": {
                "kalshi": kalshi_count,
                "polymarket": poly_count,
            },
            "avg_profit_pct": round(sum(profits) / len(profits) * 100, 2),
            "max_profit_pct": round(max(profits) * 100, 2),
            "total_arbitrage_gap": round(sum(gaps), 4),
            "top_3": [
                {
                    "platform": opp.platform,
                    "market": opp.market_title[:60],
                    "profit_pct": round(opp.profit_per_dollar * 100, 2),
                }
                for opp in opportunities[:3]
            ],
        }
