"""API endpoints for arbitrage opportunity monitoring."""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import structlog

from src.trading.arbitrage_monitor import get_monitor

logger = structlog.get_logger()

router = APIRouter(prefix="/arbitrage", tags=["arbitrage"])


@router.get("/opportunities")
async def get_opportunities(
    limit: int = Query(default=10, ge=1, le=100, description="Number of opportunities to return"),
    tier: Optional[int] = Query(default=None, ge=1, le=3, description="Filter by tier (1-3)"),
    min_age_minutes: float = Query(default=0, ge=0, description="Minimum age in minutes"),
):
    """Get top arbitrage opportunities ranked by profit potential.

    Returns the most profitable arbitrage opportunities currently being tracked,
    sorted by estimated profit in descending order.

    Args:
        limit: Maximum number of opportunities to return (1-100, default 10)
        tier: Filter by similarity tier (1=auto, 2=cautious, 3=reject, default all)
        min_age_minutes: Minimum age to filter out very new opportunities (default 0)

    Returns:
        List of arbitrage opportunities with profit estimates, prices, and metadata
    """
    try:
        monitor = get_monitor()

        # Trigger fresh scan
        monitor.scan_for_opportunities(tier_filter=tier)

        # Get top opportunities
        opportunities = monitor.get_top_opportunities(
            limit=limit,
            tier_filter=tier,
            min_age_minutes=min_age_minutes,
        )

        return {
            "count": len(opportunities),
            "opportunities": [opp.to_dict() for opp in opportunities],
        }

    except Exception as e:
        logger.error("get_opportunities_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/opportunities/{bond_id}")
async def get_opportunity(bond_id: int):
    """Get specific arbitrage opportunity by bond ID.

    Args:
        bond_id: Database ID of the bond

    Returns:
        Arbitrage opportunity details or 404 if not found
    """
    try:
        monitor = get_monitor()
        opportunity = monitor.get_opportunity(bond_id)

        if not opportunity:
            raise HTTPException(
                status_code=404,
                detail=f"No active arbitrage opportunity for bond {bond_id}"
            )

        return opportunity.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error("get_opportunity_error", bond_id=bond_id, error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/scan")
async def trigger_scan(
    tier: Optional[int] = Query(default=None, ge=1, le=3, description="Filter by tier"),
    min_profit: float = Query(default=0.01, ge=0, le=1, description="Minimum profit threshold"),
):
    """Manually trigger arbitrage opportunity scan.

    Scans all bonded markets for arbitrage opportunities and updates the monitoring system.

    Args:
        tier: Only scan bonds of specific tier (default all)
        min_profit: Minimum profit per dollar to track (default 0.01 = 1%)

    Returns:
        Scan results and updated statistics
    """
    try:
        monitor = get_monitor()

        # Trigger scan
        opportunities = monitor.scan_for_opportunities(
            tier_filter=tier,
            min_profit_threshold=min_profit,
        )

        # Get statistics
        stats = monitor.get_monitoring_stats()

        return {
            "scan_result": {
                "discovered": len(opportunities),
                "tracking_total": stats["total_opportunities"],
            },
            "stats": stats,
            "top_10": [opp.to_dict() for opp in opportunities[:10]],
        }

    except Exception as e:
        logger.error("trigger_scan_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_stats():
    """Get arbitrage monitoring statistics.

    Returns:
        Overall statistics about tracked opportunities, profit estimates, and tier breakdown
    """
    try:
        monitor = get_monitor()

        # Remove stale opportunities first
        monitor.remove_stale_opportunities(max_age_minutes=10)

        # Get statistics
        stats = monitor.get_monitoring_stats()

        return stats

    except Exception as e:
        logger.error("get_stats_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/priority-markets")
async def get_priority_markets(
    limit: int = Query(default=50, ge=1, le=200, description="Number of market pairs to return"),
):
    """Get market IDs that should be monitored with priority.

    Returns the platform-specific market IDs for the best arbitrage opportunities,
    allowing the price_updater to prioritize these markets for frequent updates.

    Args:
        limit: Maximum number of market pairs (default 50, max 200)

    Returns:
        Dictionary with kalshi_ids and polymarket_ids arrays
    """
    try:
        monitor = get_monitor()

        # Get priority market IDs
        markets = monitor.get_markets_to_monitor(limit=limit)

        return {
            "limit": limit,
            "kalshi_markets": len(markets["kalshi_ids"]),
            "polymarket_markets": len(markets["polymarket_ids"]),
            **markets,
        }

    except Exception as e:
        logger.error("get_priority_markets_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/stale")
async def remove_stale(
    max_age_minutes: float = Query(default=10, ge=1, le=60, description="Maximum age in minutes"),
):
    """Remove stale opportunities that haven't been updated recently.

    Args:
        max_age_minutes: Maximum age since last update (default 10 minutes)

    Returns:
        Number of opportunities removed
    """
    try:
        monitor = get_monitor()
        removed = monitor.remove_stale_opportunities(max_age_minutes=max_age_minutes)

        return {
            "removed": removed,
            "max_age_minutes": max_age_minutes,
        }

    except Exception as e:
        logger.error("remove_stale_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
