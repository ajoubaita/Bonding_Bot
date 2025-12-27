"""API endpoints for arbitrage opportunity monitoring."""

from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Optional
from sqlalchemy.orm import Session
import structlog

from src.trading.arbitrage_monitor import get_monitor
from src.trading.intra_platform_arbitrage import IntraPlatformArbitrageScanner
from src.models import get_db, Market

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


@router.get("/intra-platform")
async def get_intra_platform_opportunities(
    db: Session = Depends(get_db),
    platform: Optional[str] = Query(default=None, description="Filter by platform (kalshi or polymarket)"),
    min_profit_pct: float = Query(default=0.0, ge=0, le=100, description="Minimum profit percentage"),
    limit: int = Query(default=50, ge=1, le=500, description="Maximum number of opportunities to return"),
):
    """Get intra-platform arbitrage opportunities where yes + no < $1.

    This detects risk-free arbitrage within a single exchange where buying both
    YES and NO outcomes costs less than the guaranteed $1 payout.

    Example: YES = $0.45, NO = $0.52. Sum = $0.97. Buy both for $0.97, get $1.00 payout = $0.03 profit (3.1% ROI)

    Args:
        platform: Filter by platform ('kalshi' or 'polymarket', default all)
        min_profit_pct: Minimum profit percentage to include (default 0 = any profit)
        limit: Maximum opportunities to return (1-500, default 50)

    Returns:
        List of intra-platform arbitrage opportunities with profit estimates
    """
    try:
        # Validate platform
        if platform and platform not in ['kalshi', 'polymarket']:
            raise HTTPException(status_code=400, detail="Platform must be 'kalshi' or 'polymarket'")

        # Get all markets with fresh prices
        query = db.query(Market).filter(
            Market.yes_price.isnot(None),
            Market.no_price.isnot(None),
            Market.yes_price > 0,
            Market.no_price > 0,
        )

        if platform:
            query = query.filter(Market.platform == platform)

        markets = query.all()

        # Scan for opportunities
        scanner = IntraPlatformArbitrageScanner()
        opportunities = scanner.scan_markets(
            markets=markets,
            min_profit_threshold=min_profit_pct / 100.0,  # Convert percentage to decimal
            platform_filter=platform,
        )

        # Limit results
        opportunities = opportunities[:limit]

        # Get statistics
        stats = scanner.get_statistics(opportunities)

        logger.info(
            "intra_platform_scan_complete",
            platform=platform,
            min_profit_pct=min_profit_pct,
            total_markets_scanned=len(markets),
            opportunities_found=len(opportunities),
        )

        return {
            "count": len(opportunities),
            "statistics": stats,
            "opportunities": [opp.to_dict() for opp in opportunities],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("intra_platform_opportunities_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))
