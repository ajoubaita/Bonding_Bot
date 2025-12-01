"""Arbitrage opportunity calculator for cross-platform market pairs.

This module calculates potential arbitrage opportunities between Kalshi and Polymarket
prediction markets that have been matched using the similarity engine.

Arbitrage Types:
1. Direct Spread: Price difference for same outcome across platforms
2. Hedged Position: Buy complementary outcomes when prices sum to > 1

Fee Structure:
- Kalshi: ~2% fee on profits (variable by market)
- Polymarket: ~2% fee on profits (variable by market)
- Estimated total round-trip fee: 4-6%
"""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import structlog

from src.models import Market

logger = structlog.get_logger()


@dataclass
class ArbitrageOpportunity:
    """Arbitrage opportunity details."""

    # Market identifiers
    kalshi_market_id: str
    polymarket_market_id: str
    kalshi_title: str
    polymarket_title: str

    # Opportunity type
    opportunity_type: str  # "direct_spread", "hedged_position", "none"

    # Prices
    kalshi_yes_price: float
    kalshi_no_price: float
    polymarket_yes_price: float
    polymarket_no_price: float

    # Arbitrage metrics
    spread_yes: float  # Kalshi Yes - Polymarket Yes
    spread_no: float   # Kalshi No - Polymarket No
    hedged_sum_k_yes_p_no: float  # Kalshi Yes + Polymarket No
    hedged_sum_k_no_p_yes: float  # Kalshi No + Polymarket Yes

    # Profit calculation
    best_strategy: str  # Description of best strategy
    gross_profit: float  # Before fees
    estimated_fees: float  # Total estimated fees
    net_profit: float  # After fees
    roi_percent: float  # Return on investment %

    # Risk metrics
    liquidity_score: float  # 0-1, based on min liquidity
    volume_score: float     # 0-1, based on min volume
    confidence_score: float  # Overall confidence in opportunity

    # Additional context
    min_liquidity: float
    min_volume: float
    warnings: List[str]  # Any warnings about the opportunity


def extract_price(market: Market, outcome: str) -> Optional[float]:
    """Extract price for a specific outcome from market data.

    Args:
        market: Market model instance
        outcome: Outcome to extract ("Yes" or "No")

    Returns:
        Price as float (0-1 range), or None if not found
    """
    try:
        if not market.outcome_schema:
            return None

        outcomes = market.outcome_schema.get("outcomes", [])

        for outcome_data in outcomes:
            label = outcome_data.get("label", "").lower()
            value = outcome_data.get("value")

            # Match by label or value
            if outcome.lower() in label:
                price = outcome_data.get("price")
                if price is not None:
                    return float(price)

            # Match by boolean value for yes/no markets
            if outcome.lower() == "yes" and value is True:
                price = outcome_data.get("price")
                if price is not None:
                    return float(price)

            if outcome.lower() == "no" and value is False:
                price = outcome_data.get("price")
                if price is not None:
                    return float(price)

        return None

    except Exception as e:
        logger.error(
            "extract_price_failed",
            market_id=market.id,
            outcome=outcome,
            error=str(e),
        )
        return None


def calculate_liquidity_score(liquidity: float) -> float:
    """Calculate liquidity score (0-1).

    Args:
        liquidity: Market liquidity in dollars

    Returns:
        Score from 0-1
    """
    # Score based on liquidity thresholds
    if liquidity >= 50000:  # $50k+
        return 1.0
    elif liquidity >= 10000:  # $10k-50k
        return 0.8
    elif liquidity >= 5000:   # $5k-10k
        return 0.6
    elif liquidity >= 1000:   # $1k-5k
        return 0.4
    elif liquidity >= 100:    # $100-1k
        return 0.2
    else:
        return 0.1


def calculate_volume_score(volume: float) -> float:
    """Calculate volume score (0-1).

    Args:
        volume: Market volume in dollars

    Returns:
        Score from 0-1
    """
    # Score based on volume thresholds
    if volume >= 100000:  # $100k+
        return 1.0
    elif volume >= 50000:  # $50k-100k
        return 0.8
    elif volume >= 10000:  # $10k-50k
        return 0.6
    elif volume >= 5000:   # $5k-10k
        return 0.4
    elif volume >= 1000:   # $1k-5k
        return 0.2
    else:
        return 0.1


def calculate_arbitrage(
    market_k: Market,
    market_p: Market,
    fee_rate: float = 0.05,  # 5% total round-trip fee (conservative estimate)
    min_profit_threshold: float = 0.01,  # Minimum 1% net profit to consider
) -> ArbitrageOpportunity:
    """Calculate arbitrage opportunity between two matched markets.

    Args:
        market_k: Kalshi market
        market_p: Polymarket market
        fee_rate: Total estimated fee rate for round-trip trade (default 5%)
        min_profit_threshold: Minimum net profit threshold to flag opportunity

    Returns:
        ArbitrageOpportunity with all calculated metrics
    """
    logger.info(
        "calculate_arbitrage_start",
        kalshi_id=market_k.id,
        polymarket_id=market_p.id,
    )

    warnings = []

    # Extract prices
    k_yes = extract_price(market_k, "Yes")
    k_no = extract_price(market_k, "No")
    p_yes = extract_price(market_p, "Yes")
    p_no = extract_price(market_p, "No")

    # Validate prices exist
    if k_yes is None or k_no is None:
        warnings.append(f"Missing Kalshi prices (Yes: {k_yes}, No: {k_no})")
        k_yes = k_yes or 0.5
        k_no = k_no or 0.5

    if p_yes is None or p_no is None:
        warnings.append(f"Missing Polymarket prices (Yes: {p_yes}, No: {p_no})")
        p_yes = p_yes or 0.5
        p_no = p_no or 0.5

    # Calculate spreads
    spread_yes = k_yes - p_yes  # Positive means Kalshi higher
    spread_no = k_no - p_no

    # Calculate hedged position sums
    hedged_k_yes_p_no = k_yes + p_no
    hedged_k_no_p_yes = k_no + p_yes

    # Extract liquidity and volume
    k_metadata = market_k.market_metadata or {}
    p_metadata = market_p.market_metadata or {}

    k_liquidity = float(k_metadata.get("liquidity", 0))
    p_liquidity = float(p_metadata.get("liquidity", 0))
    k_volume = float(k_metadata.get("volume", 0))
    p_volume = float(p_metadata.get("volume", 0))

    min_liquidity = min(k_liquidity, p_liquidity)
    min_volume = min(k_volume, p_volume)

    # Calculate risk scores
    liquidity_score = calculate_liquidity_score(min_liquidity)
    volume_score = calculate_volume_score(min_volume)

    # Determine best arbitrage strategy
    opportunity_type = "none"
    best_strategy = "No profitable arbitrage opportunity"
    gross_profit = 0.0
    investment = 1.0  # Normalized to $1 investment

    # Strategy 1: Direct spread on Yes
    if abs(spread_yes) > fee_rate:
        if spread_yes > 0:
            # Buy Polymarket Yes (cheaper), Sell Kalshi Yes (higher)
            gross_profit_yes = spread_yes
            net_profit_yes = gross_profit_yes - (investment * fee_rate)

            if net_profit_yes > gross_profit:
                opportunity_type = "direct_spread"
                best_strategy = f"Buy Polymarket Yes @ ${p_yes:.3f}, Sell Kalshi Yes @ ${k_yes:.3f}"
                gross_profit = gross_profit_yes
        else:
            # Buy Kalshi Yes (cheaper), Sell Polymarket Yes (higher)
            gross_profit_yes = abs(spread_yes)
            net_profit_yes = gross_profit_yes - (investment * fee_rate)

            if net_profit_yes > gross_profit:
                opportunity_type = "direct_spread"
                best_strategy = f"Buy Kalshi Yes @ ${k_yes:.3f}, Sell Polymarket Yes @ ${p_yes:.3f}"
                gross_profit = gross_profit_yes

    # Strategy 2: Direct spread on No
    if abs(spread_no) > fee_rate:
        if spread_no > 0:
            # Buy Polymarket No (cheaper), Sell Kalshi No (higher)
            gross_profit_no = spread_no
            net_profit_no = gross_profit_no - (investment * fee_rate)

            if net_profit_no > gross_profit:
                opportunity_type = "direct_spread"
                best_strategy = f"Buy Polymarket No @ ${p_no:.3f}, Sell Kalshi No @ ${k_no:.3f}"
                gross_profit = gross_profit_no
        else:
            # Buy Kalshi No (cheaper), Sell Polymarket No (higher)
            gross_profit_no = abs(spread_no)
            net_profit_no = gross_profit_no - (investment * fee_rate)

            if net_profit_no > gross_profit:
                opportunity_type = "direct_spread"
                best_strategy = f"Buy Kalshi No @ ${k_no:.3f}, Sell Polymarket No @ ${p_no:.3f}"
                gross_profit = gross_profit_no

    # Strategy 3: Hedged position (Kalshi Yes + Polymarket No)
    if hedged_k_yes_p_no < (1.0 - fee_rate):
        # Buy both, guaranteed win, profit from sum < 1
        gross_profit_hedged = 1.0 - hedged_k_yes_p_no
        investment_hedged = hedged_k_yes_p_no
        net_profit_hedged = gross_profit_hedged - (investment_hedged * fee_rate)

        if net_profit_hedged > gross_profit:
            opportunity_type = "hedged_position"
            best_strategy = f"Buy Kalshi Yes @ ${k_yes:.3f} + Polymarket No @ ${p_no:.3f} (total: ${hedged_k_yes_p_no:.3f})"
            gross_profit = gross_profit_hedged
            investment = investment_hedged

    # Strategy 4: Hedged position (Kalshi No + Polymarket Yes)
    if hedged_k_no_p_yes < (1.0 - fee_rate):
        # Buy both, guaranteed win, profit from sum < 1
        gross_profit_hedged = 1.0 - hedged_k_no_p_yes
        investment_hedged = hedged_k_no_p_yes
        net_profit_hedged = gross_profit_hedged - (investment_hedged * fee_rate)

        if net_profit_hedged > gross_profit:
            opportunity_type = "hedged_position"
            best_strategy = f"Buy Kalshi No @ ${k_no:.3f} + Polymarket Yes @ ${p_yes:.3f} (total: ${hedged_k_no_p_yes:.3f})"
            gross_profit = gross_profit_hedged
            investment = investment_hedged

    # Calculate final metrics
    estimated_fees = investment * fee_rate
    net_profit = gross_profit - estimated_fees
    roi_percent = (net_profit / investment * 100) if investment > 0 else 0

    # Calculate confidence score
    # Base on profit margin, liquidity, and volume
    profit_score = min(net_profit / min_profit_threshold, 1.0) if net_profit > 0 else 0
    confidence_score = (profit_score * 0.5) + (liquidity_score * 0.3) + (volume_score * 0.2)

    # Add warnings
    if min_liquidity < 1000:
        warnings.append(f"Low liquidity: ${min_liquidity:.2f}")

    if min_volume < 5000:
        warnings.append(f"Low volume: ${min_volume:.2f}")

    if net_profit < min_profit_threshold:
        warnings.append(f"Net profit below threshold: {net_profit:.4f} < {min_profit_threshold}")

    opportunity = ArbitrageOpportunity(
        kalshi_market_id=market_k.id,
        polymarket_market_id=market_p.id,
        kalshi_title=market_k.clean_title or market_k.raw_title or "",
        polymarket_title=market_p.clean_title or market_p.raw_title or "",
        opportunity_type=opportunity_type,
        kalshi_yes_price=k_yes,
        kalshi_no_price=k_no,
        polymarket_yes_price=p_yes,
        polymarket_no_price=p_no,
        spread_yes=spread_yes,
        spread_no=spread_no,
        hedged_sum_k_yes_p_no=hedged_k_yes_p_no,
        hedged_sum_k_no_p_yes=hedged_k_no_p_yes,
        best_strategy=best_strategy,
        gross_profit=gross_profit,
        estimated_fees=estimated_fees,
        net_profit=net_profit,
        roi_percent=roi_percent,
        liquidity_score=liquidity_score,
        volume_score=volume_score,
        confidence_score=confidence_score,
        min_liquidity=min_liquidity,
        min_volume=min_volume,
        warnings=warnings,
    )

    logger.info(
        "calculate_arbitrage_complete",
        kalshi_id=market_k.id,
        polymarket_id=market_p.id,
        opportunity_type=opportunity_type,
        net_profit=net_profit,
        roi_percent=roi_percent,
        confidence_score=confidence_score,
    )

    return opportunity
