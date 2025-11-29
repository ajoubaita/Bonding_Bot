"""Arbitrage opportunity detection and profit calculation."""

from typing import Dict, Any, Optional
import structlog

logger = structlog.get_logger()


def get_market_price(market: Any, side: str = "mid") -> Optional[float]:
    """Extract price from market metadata.

    Args:
        market: Market object with market_metadata
        side: "bid", "ask", or "mid" (default)

    Returns:
        Price as float [0, 1], or None if not available
    """
    if not market.market_metadata:
        return None

    # Try different price fields
    if side == "mid":
        # Try mid price first
        if "mid_price" in market.market_metadata:
            return market.market_metadata["mid_price"]
        # Fall back to average of bid/ask
        bid = market.market_metadata.get("bid_price")
        ask = market.market_metadata.get("ask_price")
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        # Fall back to last price
        return market.market_metadata.get("last_price")

    elif side == "bid":
        return market.market_metadata.get("bid_price")

    elif side == "ask":
        return market.market_metadata.get("ask_price")

    return None


def get_market_volume(market: Any) -> float:
    """Extract trading volume from market metadata.

    Args:
        market: Market object with market_metadata

    Returns:
        Volume in dollars (or 0 if not available)
    """
    if not market.market_metadata:
        return 0.0

    volume = market.market_metadata.get("volume", 0.0)
    return float(volume) if volume else 0.0


def get_market_liquidity(market: Any) -> float:
    """Extract liquidity from market metadata.

    Args:
        market: Market object with market_metadata

    Returns:
        Liquidity in dollars (or 0 if not available)
    """
    if not market.market_metadata:
        return 0.0

    liquidity = market.market_metadata.get("liquidity", 0.0)
    return float(liquidity) if liquidity else 0.0


def calculate_arbitrage_opportunity(
    market_k: Any,
    market_p: Any,
    outcome_mapping: Dict[str, str]
) -> Dict[str, Any]:
    """Calculate arbitrage opportunity between two bonded markets.

    This identifies if there's a profitable price difference where you can:
    - Buy YES on one platform and NO on the other (if YES_k + NO_p < 1.0)
    - Or vice versa

    Args:
        market_k: Kalshi market
        market_p: Polymarket market
        outcome_mapping: Mapping of outcomes between platforms

    Returns:
        Dictionary with arbitrage analysis:
        {
            "has_arbitrage": bool,
            "arbitrage_type": "buy_k_yes_sell_p_no" | "buy_p_yes_sell_k_no" | null,
            "profit_per_dollar": float,  # Expected profit per $1 invested
            "kalshi_price": float,
            "polymarket_price": float,
            "min_volume": float,  # Minimum volume of the two markets
            "min_liquidity": float,  # Minimum liquidity
            "max_position_size": float,  # Recommended max position
            "explanation": str,
        }
    """
    result = {
        "has_arbitrage": False,
        "arbitrage_type": None,
        "profit_per_dollar": 0.0,
        "kalshi_price": None,
        "polymarket_price": None,
        "min_volume": 0.0,
        "min_liquidity": 0.0,
        "max_position_size": 0.0,
        "explanation": "No arbitrage opportunity detected",
    }

    try:
        # Get prices
        price_k = get_market_price(market_k, side="mid")
        price_p = get_market_price(market_p, side="mid")

        if price_k is None or price_p is None:
            result["explanation"] = "Price data not available"
            return result

        result["kalshi_price"] = price_k
        result["polymarket_price"] = price_p

        # Get volume and liquidity
        volume_k = get_market_volume(market_k)
        volume_p = get_market_volume(market_p)
        result["min_volume"] = min(volume_k, volume_p)

        liquidity_k = get_market_liquidity(market_k)
        liquidity_p = get_market_liquidity(market_p)
        result["min_liquidity"] = min(liquidity_k, liquidity_p)

        # Calculate arbitrage opportunities
        # Opportunity 1: Buy YES on Kalshi, sell YES on Polymarket (if P_poly > P_kalshi)
        if price_p > price_k:
            profit_1 = price_p - price_k  # Profit if YES wins
            # This works because:
            # - Buy YES on Kalshi for price_k, win $1 if YES
            # - Sell YES on Polymarket for price_p (short YES = long NO), pay $1 if YES
            # - Net: price_p - price_k profit regardless of outcome
            result["has_arbitrage"] = True
            result["arbitrage_type"] = "buy_k_yes_sell_p_yes"
            result["profit_per_dollar"] = profit_1
            result["explanation"] = f"Buy YES on Kalshi @ ${price_k:.3f}, sell YES on Polymarket @ ${price_p:.3f}. Profit: ${profit_1:.3f} per share."

        # Opportunity 2: Buy YES on Polymarket, sell YES on Kalshi (if P_kalshi > P_poly)
        elif price_k > price_p:
            profit_2 = price_k - price_p
            result["has_arbitrage"] = True
            result["arbitrage_type"] = "buy_p_yes_sell_k_yes"
            result["profit_per_dollar"] = profit_2
            result["explanation"] = f"Buy YES on Polymarket @ ${price_p:.3f}, sell YES on Kalshi @ ${price_k:.3f}. Profit: ${profit_2:.3f} per share."

        else:
            result["explanation"] = f"Prices are equal (Kalshi: ${price_k:.3f}, Polymarket: ${price_p:.3f}). No arbitrage."
            return result

        # Calculate max position size (conservative: 2% of min liquidity)
        if result["min_liquidity"] > 0:
            result["max_position_size"] = result["min_liquidity"] * 0.02
        else:
            # Fall back to volume-based estimate (0.5% of daily volume)
            result["max_position_size"] = result["min_volume"] * 0.005

        # Log the opportunity
        logger.info(
            "arbitrage_detected",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            arbitrage_type=result["arbitrage_type"],
            profit_per_dollar=result["profit_per_dollar"],
            kalshi_price=price_k,
            poly_price=price_p,
            max_position=result["max_position_size"],
        )

    except Exception as e:
        logger.error(
            "arbitrage_calculation_error",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            error=str(e),
        )
        result["explanation"] = f"Error calculating arbitrage: {str(e)}"

    return result


def filter_by_minimum_volume(markets: list, min_volume: float = 10000.0) -> list:
    """Filter markets by minimum trading volume.

    Args:
        markets: List of Market objects
        min_volume: Minimum volume in dollars (default $10k)

    Returns:
        Filtered list of markets with volume >= min_volume
    """
    filtered = []

    for market in markets:
        volume = get_market_volume(market)
        if volume >= min_volume:
            filtered.append(market)
        else:
            logger.debug(
                "market_filtered_low_volume",
                market_id=market.id,
                volume=volume,
                min_required=min_volume,
            )

    return filtered


def calculate_roi(
    profit_per_dollar: float,
    holding_period_days: int = 7
) -> Dict[str, float]:
    """Calculate ROI metrics for arbitrage.

    Args:
        profit_per_dollar: Profit per $1 invested
        holding_period_days: Expected days until resolution

    Returns:
        Dictionary with ROI metrics
    """
    # Simple ROI
    roi = profit_per_dollar

    # Annualized ROI (assuming reinvestment)
    if holding_period_days > 0:
        periods_per_year = 365 / holding_period_days
        annualized_roi = (1 + roi) ** periods_per_year - 1
    else:
        annualized_roi = 0.0

    return {
        "roi": roi,
        "roi_percent": roi * 100,
        "annualized_roi": annualized_roi,
        "annualized_roi_percent": annualized_roi * 100,
        "holding_period_days": holding_period_days,
    }
