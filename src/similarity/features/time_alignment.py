"""Time alignment feature calculator."""

from datetime import datetime, timedelta
from typing import Optional, Tuple
import math
import structlog

from src.models import Market

logger = structlog.get_logger()


def parse_iso_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 date string to datetime.

    Args:
        date_str: ISO 8601 date string

    Returns:
        Datetime object or None if parsing fails
    """
    if not date_str:
        return None

    try:
        # Handle both with and without timezone
        if date_str.endswith('Z'):
            date_str = date_str[:-1] + '+00:00'
        return datetime.fromisoformat(date_str.replace('Z', '+00:00'))
    except Exception:
        return None


def get_resolution_date(market: Market) -> Optional[datetime]:
    """Extract resolution date from market.

    Args:
        market: Market object

    Returns:
        Resolution date as datetime or None
    """
    if not market.time_window:
        return None

    resolution_date_str = market.time_window.get("resolution_date")
    return parse_iso_date(resolution_date_str)


def get_time_window(market: Market) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Extract time window from market.

    Args:
        market: Market object

    Returns:
        Tuple of (start, end) datetimes
    """
    if not market.time_window:
        return None, None

    start_str = market.time_window.get("start")
    end_str = market.time_window.get("end")

    start = parse_iso_date(start_str)
    end = parse_iso_date(end_str)

    return start, end


def get_granularity_tau(market: Market) -> int:
    """Get tau (decay parameter) based on time granularity.

    Args:
        market: Market object

    Returns:
        Tau in days
    """
    if not market.time_window:
        return 7  # Default

    granularity = market.time_window.get("granularity", "week")

    tau_map = {
        "day": 3,
        "week": 7,
        "month": 14,
        "quarter": 21,
        "year": 30,
    }

    return tau_map.get(granularity, 7)


def calculate_time_alignment(market_k: Market, market_p: Market) -> dict:
    """Calculate time alignment features between two markets.

    Args:
        market_k: Kalshi market
        market_p: Polymarket market

    Returns:
        Dictionary with time alignment scores:
        {
            "score_time_final": float,  # Final combined score [0, 1]
            "score_time": float,        # Resolution date score [0, 1]
            "score_window": float,      # Observation window score [0, 1]
            "delta_days": int,          # Days between resolution dates
        }
    """
    result = {
        "score_time_final": 0.0,
        "score_time": 0.0,
        "score_window": 0.0,
        "delta_days": 999,
    }

    try:
        # Get resolution dates
        res_k = get_resolution_date(market_k)
        res_p = get_resolution_date(market_p)

        if not res_k or not res_p:
            logger.warning(
                "time_alignment_missing_dates",
                kalshi_id=market_k.id,
                poly_id=market_p.id,
                kalshi_date=res_k,
                poly_date=res_p,
            )
            return result

        # Calculate delta in days
        delta = abs((res_k - res_p).days)
        result["delta_days"] = delta

        # Get tau based on granularity (use max of both markets)
        tau_k = get_granularity_tau(market_k)
        tau_p = get_granularity_tau(market_p)
        tau = max(tau_k, tau_p)

        # Calculate exponential decay score
        score_time = math.exp(-delta / tau)

        # Calculate observation window overlap
        start_k, end_k = get_time_window(market_k)
        start_p, end_p = get_time_window(market_p)

        score_window = 0.0
        if start_k and end_k and start_p and end_p:
            # Calculate overlap
            overlap_start = max(start_k, start_p)
            overlap_end = min(end_k, end_p)

            if overlap_end > overlap_start:
                overlap_days = (overlap_end - overlap_start).days

                # Calculate union
                union_start = min(start_k, start_p)
                union_end = max(end_k, end_p)
                union_days = (union_end - union_start).days

                if union_days > 0:
                    score_window = overlap_days / union_days
        else:
            # If no explicit windows, use resolution date similarity
            score_window = score_time

        # Combined score (weight resolution date more heavily)
        score_time_final = 0.6 * score_time + 0.4 * score_window

        result = {
            "score_time_final": float(score_time_final),
            "score_time": float(score_time),
            "score_window": float(score_window),
            "delta_days": delta,
        }

        logger.debug(
            "time_alignment_calculated",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            delta_days=delta,
            score=score_time_final,
        )

    except Exception as e:
        logger.error(
            "time_alignment_error",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            error=str(e),
        )

    return result
