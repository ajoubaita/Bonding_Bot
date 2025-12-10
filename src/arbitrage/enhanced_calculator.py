"""Enhanced arbitrage calculator with bid/ask, order book depth, and dynamic fees.

This module provides production-ready arbitrage detection that:
- Uses actual bid/ask prices (not just mid prices)
- Considers order book depth for position sizing
- Calculates market-specific fees dynamically
- Accounts for gas costs on Polymarket (L2)
- Filters out illiquid markets
- Ranks opportunities by risk-adjusted edge
"""

from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass
from datetime import datetime
import structlog

from src.models import Market

logger = structlog.get_logger()

# Default fee rates (will be overridden by market-specific data)
DEFAULT_KALSHI_FEE_RATE = 0.02  # 2% on profits
DEFAULT_POLYMARKET_FEE_RATE = 0.02  # 2% on profits
DEFAULT_POLYMARKET_GAS_COST_USD = 0.10  # ~$0.10 per trade on Polygon L2


@dataclass
class OrderBookLevel:
    """Single level in order book."""
    price: float
    size: float  # Available size at this price level


@dataclass
class OrderBook:
    """Order book snapshot."""
    bids: List[OrderBookLevel]  # Sorted descending by price
    asks: List[OrderBookLevel]  # Sorted ascending by price
    timestamp: datetime
    market_id: str
    platform: str


@dataclass
class EnhancedArbitrageOpportunity:
    """Enhanced arbitrage opportunity with realistic execution costs."""
    
    # Market identifiers
    kalshi_market_id: str
    polymarket_market_id: str
    kalshi_title: str
    polymarket_title: str
    
    # Opportunity type
    opportunity_type: str  # "direct_spread", "hedged_position", "none"
    direction: str  # "buy_k_sell_p" or "buy_p_sell_k"
    
    # Prices (bid/ask)
    kalshi_bid: float
    kalshi_ask: float
    kalshi_mid: float
    polymarket_bid: float
    polymarket_ask: float
    polymarket_mid: float
    
    # Execution costs
    kalshi_fee_rate: float
    polymarket_fee_rate: float
    polymarket_gas_cost_usd: float
    total_fee_rate: float
    
    # Profitability
    gross_spread: float  # Before fees
    net_profit_per_share: float  # After all costs
    roi_percent: float
    
    # Position sizing (based on order book depth)
    max_position_size: float  # Maximum safe position size
    recommended_position_size: float  # Recommended position
    available_liquidity: float  # Total available at profitable prices
    
    # Risk metrics
    liquidity_score: float  # 0-1
    volume_score: float  # 0-1
    confidence_score: float  # 0-1
    min_edge_percent: float  # Minimum edge above zero
    
    # Market health
    is_illiquid: bool
    has_sufficient_depth: bool
    price_staleness_sec: Optional[int]
    
    # Warnings
    warnings: List[str]
    
    # Trade instructions (structured output)
    trade_instructions: Dict[str, Any]


def get_market_fee_rate(market: Market, platform: str) -> float:
    """Get market-specific fee rate.
    
    Args:
        market: Market object
        platform: "kalshi" or "polymarket"
        
    Returns:
        Fee rate as decimal (e.g., 0.02 for 2%)
    """
    # Check metadata for fee information
    if market.market_metadata:
        fee_rate = market.market_metadata.get("fee_rate")
        if fee_rate is not None:
            return float(fee_rate)
    
    # Default fees by platform
    if platform == "kalshi":
        return DEFAULT_KALSHI_FEE_RATE
    elif platform == "polymarket":
        return DEFAULT_POLYMARKET_FEE_RATE
    else:
        return 0.05  # Conservative 5% default


def estimate_order_book_from_prices(
    market: Market,
    mid_price: float,
    spread_pct: float = 0.01  # 1% default spread
) -> OrderBook:
    """Estimate order book from mid price (fallback when real order book unavailable).
    
    Args:
        market: Market object
        mid_price: Mid price
        spread_pct: Estimated spread percentage
        
    Returns:
        Estimated OrderBook
    """
    spread = mid_price * spread_pct
    
    # Create simple order book with 3 levels
    bids = [
        OrderBookLevel(price=mid_price - spread * i, size=1000.0)
        for i in range(1, 4)
    ]
    asks = [
        OrderBookLevel(price=mid_price + spread * i, size=1000.0)
        for i in range(1, 4)
    ]
    
    return OrderBook(
        bids=bids,
        asks=asks,
        timestamp=market.updated_at or datetime.utcnow(),
        market_id=market.id,
        platform=market.platform,
    )


def get_order_book_depth(
    order_book: OrderBook,
    target_price: float,
    side: str  # "bid" or "ask"
) -> float:
    """Calculate available liquidity at or better than target price.
    
    Args:
        order_book: Order book snapshot
        target_price: Target execution price
        side: "bid" (for selling) or "ask" (for buying)
        
    Returns:
        Total available size at or better than target price
    """
    if side == "bid":
        # For selling, we need bids >= target_price
        total_size = 0.0
        for bid in order_book.bids:
            if bid.price >= target_price:
                total_size += bid.size
            else:
                break
        return total_size
    else:  # ask
        # For buying, we need asks <= target_price
        total_size = 0.0
        for ask in order_book.asks:
            if ask.price <= target_price:
                total_size += ask.size
            else:
                break
        return total_size


def calculate_enhanced_arbitrage(
    market_k: Market,
    market_p: Market,
    order_book_k: Optional[OrderBook] = None,
    order_book_p: Optional[OrderBook] = None,
    min_edge_percent: float = 0.01,  # Minimum 1% edge
    min_liquidity_usd: float = 1000.0,  # Minimum $1k liquidity
) -> EnhancedArbitrageOpportunity:
    """Calculate enhanced arbitrage opportunity with realistic execution costs.
    
    Args:
        market_k: Kalshi market
        market_p: Polymarket market
        order_book_k: Kalshi order book (optional, will estimate if None)
        order_book_p: Polymarket order book (optional, will estimate if None)
        min_edge_percent: Minimum edge above zero to consider
        min_liquidity_usd: Minimum liquidity required
        
    Returns:
        EnhancedArbitrageOpportunity
    """
    logger.info(
        "calculate_enhanced_arbitrage_start",
        kalshi_id=market_k.id,
        polymarket_id=market_p.id,
    )
    
    warnings = []
    
    # Extract prices from outcome_schema
    def get_outcome_price(market: Market, outcome_value: bool) -> Optional[float]:
        """Get price for yes/no outcome."""
        if not market.outcome_schema:
            return None
        outcomes = market.outcome_schema.get("outcomes", [])
        for outcome in outcomes:
            if outcome.get("value") == outcome_value:
                return outcome.get("price")
        return None
    
    k_yes_mid = get_outcome_price(market_k, True)
    k_no_mid = 1.0 - k_yes_mid if k_yes_mid else None
    p_yes_mid = get_outcome_price(market_p, True)
    p_no_mid = 1.0 - p_yes_mid if p_yes_mid else None
    
    if not all([k_yes_mid, p_yes_mid]):
        warnings.append("Missing price data")
        return _create_no_opportunity(market_k, market_p, warnings)
    
    # Get or estimate order books
    if order_book_k is None:
        order_book_k = estimate_order_book_from_prices(market_k, k_yes_mid)
        warnings.append("Using estimated Kalshi order book")
    
    if order_book_p is None:
        order_book_p = estimate_order_book_from_prices(market_p, p_yes_mid)
        warnings.append("Using estimated Polymarket order book")
    
    # Extract bid/ask from order books or fallback to outcome_schema
    if order_book_k and order_book_k.bids:
        k_bid = order_book_k.bids[0].price
    else:
        # Try to get from outcome_schema (stored by price_updater)
        k_outcomes = market_k.outcome_schema.get("outcomes", []) if market_k.outcome_schema else []
        k_bid = next((o.get("bid") for o in k_outcomes if o.get("value") is True), k_yes_mid * 0.995)
    
    if order_book_k and order_book_k.asks:
        k_ask = order_book_k.asks[0].price
    else:
        k_outcomes = market_k.outcome_schema.get("outcomes", []) if market_k.outcome_schema else []
        k_ask = next((o.get("ask") for o in k_outcomes if o.get("value") is True), k_yes_mid * 1.005)
    
    if order_book_p and order_book_p.bids:
        p_bid = order_book_p.bids[0].price
    else:
        p_outcomes = market_p.outcome_schema.get("outcomes", []) if market_p.outcome_schema else []
        p_bid = next((o.get("bid") for o in p_outcomes if o.get("value") is True), p_yes_mid * 0.995)
    
    if order_book_p and order_book_p.asks:
        p_ask = order_book_p.asks[0].price
    else:
        p_outcomes = market_p.outcome_schema.get("outcomes", []) if market_p.outcome_schema else []
        p_ask = next((o.get("ask") for o in p_outcomes if o.get("value") is True), p_yes_mid * 1.005)
    
    # Get fee rates
    k_fee = get_market_fee_rate(market_k, "kalshi")
    p_fee = get_market_fee_rate(market_p, "polymarket")
    gas_cost = DEFAULT_POLYMARKET_GAS_COST_USD
    
    # Calculate both directions
    # Direction 1: Buy Kalshi Yes, Sell Polymarket Yes
    # Cost: k_ask (buy) + fees
    # Revenue: p_bid (sell) - fees
    profit_1 = p_bid - k_ask - (k_ask * k_fee) - (p_bid * p_fee) - (gas_cost / 1.0)  # Normalized per $1
    
    # Direction 2: Buy Polymarket Yes, Sell Kalshi Yes
    # Cost: p_ask (buy) + fees
    # Revenue: k_bid (sell) - fees
    profit_2 = k_bid - p_ask - (p_ask * p_fee) - (k_bid * k_fee) - (gas_cost / 1.0)
    
    # Choose best direction
    if profit_1 > profit_2 and profit_1 > min_edge_percent:
        direction = "buy_k_sell_p"
        net_profit = profit_1
        opportunity_type = "direct_spread"
    elif profit_2 > min_edge_percent:
        direction = "buy_p_sell_k"
        net_profit = profit_2
        opportunity_type = "direct_spread"
    else:
        return _create_no_opportunity(market_k, market_p, ["No profitable arbitrage after costs"])
    
    # Calculate position sizing based on order book depth
    if direction == "buy_k_sell_p":
        # Need to buy at k_ask, sell at p_bid
        k_depth = get_order_book_depth(order_book_k, k_ask, "ask")
        p_depth = get_order_book_depth(order_book_p, p_bid, "bid")
        available_liquidity = min(k_depth, p_depth)
    else:
        # Need to buy at p_ask, sell at k_bid
        k_depth = get_order_book_depth(order_book_k, k_bid, "bid")
        p_depth = get_order_book_depth(order_book_p, p_ask, "ask")
        available_liquidity = min(k_depth, p_depth)
    
    # Position sizing: use 10% of available liquidity or $10k max, whichever is smaller
    max_position = min(available_liquidity * 0.1, 10000.0)
    recommended_position = min(max_position * 0.5, 5000.0)  # Conservative 50% of max
    
    # Check liquidity thresholds
    is_illiquid = available_liquidity < min_liquidity_usd
    has_sufficient_depth = available_liquidity >= min_liquidity_usd * 2
    
    if is_illiquid:
        warnings.append(f"Insufficient liquidity: ${available_liquidity:.2f} < ${min_liquidity_usd:.2f}")
    
    # Calculate risk scores
    k_volume = float(market_k.market_metadata.get("volume", 0) if market_k.market_metadata else 0)
    p_volume = float(market_p.market_metadata.get("volume", 0) if market_p.market_metadata else 0)
    min_volume = min(k_volume, p_volume)
    
    k_liquidity = float(market_k.market_metadata.get("liquidity", 0) if market_k.market_metadata else 0)
    p_liquidity = float(market_p.market_metadata.get("liquidity", 0) if market_p.market_metadata else 0)
    min_liquidity = min(k_liquidity, p_liquidity)
    
    liquidity_score = min(min_liquidity / 50000.0, 1.0) if min_liquidity > 0 else 0.0
    volume_score = min(min_volume / 100000.0, 1.0) if min_volume > 0 else 0.0
    confidence_score = (liquidity_score * 0.4) + (volume_score * 0.3) + (min(net_profit / 0.05, 1.0) * 0.3)
    
    # Price staleness
    price_staleness = None
    if market_k.updated_at and market_p.updated_at:
        staleness_k = (datetime.utcnow() - market_k.updated_at).total_seconds()
        staleness_p = (datetime.utcnow() - market_p.updated_at).total_seconds()
        price_staleness = int(max(staleness_k, staleness_p))
        if price_staleness > 300:  # 5 minutes
            warnings.append(f"Price data is {price_staleness // 60} minutes old")
    
    # Create trade instructions
    trade_instructions = _create_trade_instructions(
        direction, market_k, market_p,
        k_bid, k_ask, p_bid, p_ask,
        recommended_position, net_profit
    )
    
    opportunity = EnhancedArbitrageOpportunity(
        kalshi_market_id=market_k.id,
        polymarket_market_id=market_p.id,
        kalshi_title=market_k.clean_title or market_k.raw_title or "",
        polymarket_title=market_p.clean_title or market_p.raw_title or "",
        opportunity_type=opportunity_type,
        direction=direction,
        kalshi_bid=k_bid,
        kalshi_ask=k_ask,
        kalshi_mid=k_yes_mid,
        polymarket_bid=p_bid,
        polymarket_ask=p_ask,
        polymarket_mid=p_yes_mid,
        kalshi_fee_rate=k_fee,
        polymarket_fee_rate=p_fee,
        polymarket_gas_cost_usd=gas_cost,
        total_fee_rate=k_fee + p_fee,
        gross_spread=abs(k_yes_mid - p_yes_mid),
        net_profit_per_share=net_profit,
        roi_percent=net_profit * 100,
        max_position_size=max_position,
        recommended_position_size=recommended_position,
        available_liquidity=available_liquidity,
        liquidity_score=liquidity_score,
        volume_score=volume_score,
        confidence_score=confidence_score,
        min_edge_percent=min_edge_percent,
        is_illiquid=is_illiquid,
        has_sufficient_depth=has_sufficient_depth,
        price_staleness_sec=price_staleness,
        warnings=warnings,
        trade_instructions=trade_instructions,
    )
    
    logger.info(
        "calculate_enhanced_arbitrage_complete",
        kalshi_id=market_k.id,
        polymarket_id=market_p.id,
        opportunity_type=opportunity_type,
        net_profit=net_profit,
        roi_percent=opportunity.roi_percent,
        recommended_position=recommended_position,
    )
    
    return opportunity


def _create_no_opportunity(
    market_k: Market,
    market_p: Market,
    warnings: List[str]
) -> EnhancedArbitrageOpportunity:
    """Create a 'no opportunity' result."""
    return EnhancedArbitrageOpportunity(
        kalshi_market_id=market_k.id,
        polymarket_market_id=market_p.id,
        kalshi_title=market_k.clean_title or market_k.raw_title or "",
        polymarket_title=market_p.clean_title or market_p.raw_title or "",
        opportunity_type="none",
        direction="",
        kalshi_bid=0.0,
        kalshi_ask=0.0,
        kalshi_mid=0.0,
        polymarket_bid=0.0,
        polymarket_ask=0.0,
        polymarket_mid=0.0,
        kalshi_fee_rate=0.0,
        polymarket_fee_rate=0.0,
        polymarket_gas_cost_usd=0.0,
        total_fee_rate=0.0,
        gross_spread=0.0,
        net_profit_per_share=0.0,
        roi_percent=0.0,
        max_position_size=0.0,
        recommended_position_size=0.0,
        available_liquidity=0.0,
        liquidity_score=0.0,
        volume_score=0.0,
        confidence_score=0.0,
        min_edge_percent=0.0,
        is_illiquid=True,
        has_sufficient_depth=False,
        price_staleness_sec=None,
        warnings=warnings,
        trade_instructions={},
    )


def _create_trade_instructions(
    direction: str,
    market_k: Market,
    market_p: Market,
    k_bid: float,
    k_ask: float,
    p_bid: float,
    p_ask: float,
    position_size: float,
    net_profit: float,
) -> Dict[str, Any]:
    """Create structured trade instructions.
    
    Returns:
        Dictionary with trade instructions in structured format
    """
    if direction == "buy_k_sell_p":
        return {
            "strategy": "direct_spread",
            "legs": [
                {
                    "exchange": "kalshi",
                    "market_id": market_k.id,
                    "side": "buy",
                    "outcome": "yes",
                    "price": k_ask,
                    "size": position_size,
                    "estimated_cost": position_size * k_ask,
                },
                {
                    "exchange": "polymarket",
                    "market_id": market_p.id,
                    "side": "sell",
                    "outcome": "yes",
                    "price": p_bid,
                    "size": position_size,
                    "estimated_revenue": position_size * p_bid,
                },
            ],
            "expected_profit_usd": position_size * net_profit,
            "expected_roi_percent": net_profit * 100,
        }
    else:  # buy_p_sell_k
        return {
            "strategy": "direct_spread",
            "legs": [
                {
                    "exchange": "polymarket",
                    "market_id": market_p.id,
                    "side": "buy",
                    "outcome": "yes",
                    "price": p_ask,
                    "size": position_size,
                    "estimated_cost": position_size * p_ask,
                },
                {
                    "exchange": "kalshi",
                    "market_id": market_k.id,
                    "side": "sell",
                    "outcome": "yes",
                    "price": k_bid,
                    "size": position_size,
                    "estimated_revenue": position_size * k_bid,
                },
            ],
            "expected_profit_usd": position_size * net_profit,
            "expected_roi_percent": net_profit * 100,
        }

