"""Arbitrage opportunity detection and profit calculation."""

from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()

# Price staleness threshold (5 minutes)
PRICE_STALENESS_THRESHOLD_SEC = 300


def get_market_price(market: Any, side: str = "mid") -> Tuple[Optional[float], bool, str]:
    """Extract price from market outcome_schema with staleness check.

    Args:
        market: Market object with outcome_schema and updated_at
        side: "bid", "ask", or "mid" (default)

    Returns:
        Tuple of (price, is_stale, warning_message):
        - price: Price as float [0, 1], or None if not available
        - is_stale: True if price is older than PRICE_STALENESS_THRESHOLD_SEC
        - warning_message: Human-readable warning if issues detected
    """
    # Check if outcome_schema exists (where price_updater writes prices)
    if not market.outcome_schema:
        return None, True, "No outcome_schema found"

    # Check price staleness using updated_at timestamp
    is_stale = False
    warning = ""

    if market.updated_at:
        age_seconds = (datetime.utcnow() - market.updated_at).total_seconds()
        if age_seconds > PRICE_STALENESS_THRESHOLD_SEC:
            is_stale = True
            age_minutes = int(age_seconds / 60)
            warning = f"Price data is {age_minutes} minutes old (threshold: 5 min)"
    else:
        is_stale = True
        warning = "No updated_at timestamp available"

    # Extract price from outcome_schema (where price_updater writes it)
    outcomes = market.outcome_schema.get("outcomes", [])
    if not outcomes:
        return None, True, "No outcomes in outcome_schema"

    # For binary markets, find YES outcome price
    # For other markets, use first outcome price
    yes_price = None
    for outcome in outcomes:
        # Binary market: look for value=True (YES outcome)
        if outcome.get("value") is True:
            yes_price = outcome.get("price")
            break

    # If no YES outcome found, use first outcome
    if yes_price is None and outcomes:
        yes_price = outcomes[0].get("price")

    if yes_price is None:
        return None, True, "No price found in outcomes"

    # Handle bid/ask/mid logic
    if side == "mid":
        # For now, we only have mid prices from price_updater
        # TODO: Add bid/ask spread calculation when available
        return float(yes_price), is_stale, warning

    elif side == "bid":
        # Estimate bid as mid - 0.5% spread
        # TODO: Replace with actual bid when available from API
        bid_price = float(yes_price) * 0.995
        return bid_price, is_stale, warning

    elif side == "ask":
        # Estimate ask as mid + 0.5% spread
        # TODO: Replace with actual ask when available from API
        ask_price = float(yes_price) * 1.005
        return ask_price, is_stale, warning

    return float(yes_price), is_stale, warning


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
    """Calculate arbitrage opportunity between two bonded markets with slippage consideration.

    This identifies if there's a profitable price difference where you can:
    - Buy YES on one platform and sell YES on the other (if spread > fees)

    Args:
        market_k: Kalshi market
        market_p: Polymarket market
        outcome_mapping: Mapping of outcomes between platforms

    Returns:
        Dictionary with arbitrage analysis:
        {
            "has_arbitrage": bool,
            "arbitrage_type": "buy_k_yes_sell_p_yes" | "buy_p_yes_sell_k_yes" | null,
            "profit_per_dollar": float,  # Expected profit per $1 invested (after slippage)
            "kalshi_price": float,
            "polymarket_price": float,
            "min_volume": float,  # Minimum volume of the two markets
            "min_liquidity": float,  # Minimum liquidity
            "max_position_size": float,  # Recommended max position
            "explanation": str,
            "warnings": list,  # Price staleness and other warnings
            "price_age_kalshi_sec": int,  # Age of Kalshi price in seconds
            "price_age_poly_sec": int,  # Age of Polymarket price in seconds
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
        "warnings": [],
        "price_age_kalshi_sec": None,
        "price_age_poly_sec": None,
    }

    try:
        # Get prices with staleness checking (returns tuple: price, is_stale, warning)
        # For buying, we use ASK price (must pay higher)
        # For selling, we use BID price (receive lower)

        # Check mid prices first for staleness
        price_k_mid, is_stale_k, warning_k = get_market_price(market_k, side="mid")
        price_p_mid, is_stale_p, warning_p = get_market_price(market_p, side="mid")

        # Add staleness warnings
        if is_stale_k:
            result["warnings"].append(f"Kalshi: {warning_k}")
        if is_stale_p:
            result["warnings"].append(f"Polymarket: {warning_p}")

        # Calculate price age in seconds
        if market_k.updated_at:
            result["price_age_kalshi_sec"] = int((datetime.utcnow() - market_k.updated_at).total_seconds())
        if market_p.updated_at:
            result["price_age_poly_sec"] = int((datetime.utcnow() - market_p.updated_at).total_seconds())

        # Reject stale prices
        if is_stale_k or is_stale_p:
            result["explanation"] = f"Price data is stale: {'; '.join(result['warnings'])}"
            logger.warning(
                "arbitrage_stale_prices",
                kalshi_id=market_k.id,
                poly_id=market_p.id,
                kalshi_age_sec=result["price_age_kalshi_sec"],
                poly_age_sec=result["price_age_poly_sec"],
            )
            return result

        if price_k_mid is None or price_p_mid is None:
            result["explanation"] = "Price data not available"
            return result

        result["kalshi_price"] = price_k_mid
        result["polymarket_price"] = price_p_mid

        # Get volume and liquidity
        volume_k = get_market_volume(market_k)
        volume_p = get_market_volume(market_p)
        result["min_volume"] = min(volume_k, volume_p)

        liquidity_k = get_market_liquidity(market_k)
        liquidity_p = get_market_liquidity(market_p)
        result["min_liquidity"] = min(liquidity_k, liquidity_p)

        # Calculate arbitrage opportunities with slippage consideration
        # Use bid/ask prices for realistic execution costs

        # Opportunity 1: Buy YES on Kalshi, sell YES on Polymarket
        # Cost: Ask price on Kalshi (higher)
        # Revenue: Bid price on Polymarket (lower)
        ask_k, _, _ = get_market_price(market_k, side="ask")
        bid_p, _, _ = get_market_price(market_p, side="bid")

        if ask_k and bid_p and bid_p > ask_k:
            profit_1 = bid_p - ask_k  # Profit after slippage
            result["has_arbitrage"] = True
            result["arbitrage_type"] = "buy_k_yes_sell_p_yes"
            result["profit_per_dollar"] = profit_1
            result["explanation"] = (
                f"Buy YES on Kalshi @ ${ask_k:.4f} (ask), "
                f"sell YES on Polymarket @ ${bid_p:.4f} (bid). "
                f"Profit: ${profit_1:.4f} per share after slippage."
            )

        # Opportunity 2: Buy YES on Polymarket, sell YES on Kalshi
        # Cost: Ask price on Polymarket (higher)
        # Revenue: Bid price on Kalshi (lower)
        bid_k, _, _ = get_market_price(market_k, side="bid")
        ask_p, _, _ = get_market_price(market_p, side="ask")

        if bid_k and ask_p and bid_k > ask_p:
            profit_2 = bid_k - ask_p  # Profit after slippage

            # Only replace if better than opportunity 1
            if not result["has_arbitrage"] or profit_2 > result["profit_per_dollar"]:
                result["has_arbitrage"] = True
                result["arbitrage_type"] = "buy_p_yes_sell_k_yes"
                result["profit_per_dollar"] = profit_2
                result["explanation"] = (
                    f"Buy YES on Polymarket @ ${ask_p:.4f} (ask), "
                    f"sell YES on Kalshi @ ${bid_k:.4f} (bid). "
                    f"Profit: ${profit_2:.4f} per share after slippage."
                )

        # If no arbitrage after slippage, explain why
        if not result["has_arbitrage"]:
            result["explanation"] = (
                f"No profitable arbitrage after slippage. "
                f"Kalshi: ${price_k_mid:.4f}, Polymarket: ${price_p_mid:.4f}. "
                f"Spread too small to cover bid/ask costs."
            )
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
            kalshi_price=price_k_mid,
            poly_price=price_p_mid,
            max_position=result["max_position_size"],
            warnings=result["warnings"],
        )

    except Exception as e:
        logger.error(
            "arbitrage_calculation_error",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            error=str(e),
        )
        result["explanation"] = f"Error calculating arbitrage: {str(e)}"
        result["warnings"].append(f"Calculation error: {str(e)}")

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
