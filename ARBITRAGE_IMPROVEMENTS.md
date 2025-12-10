# Arbitrage Engine Improvements

This document summarizes the improvements made to the bonding and arbitrage detection system.

## Overview

The improvements focus on:
1. **Better Market Matching**: Enhanced similarity functions with direction detection
2. **Production-Ready Arbitrage Detection**: Real bid/ask prices, order book depth, dynamic fees
3. **Structured Logging**: Better observability and offline analysis
4. **Order Book Integration**: Real order book data for position sizing

## 1. Enhanced Similarity Matching

### Improvements Made

#### Text Cleaning Enhancements (`src/normalization/text_cleaner.py`)
- Added `extract_key_terms()`: Extracts meaningful terms, removes stopwords
- Added `fuzzy_match_ratio()`: Uses SequenceMatcher for fuzzy text matching
- Added `detect_direction_mismatch()`: Detects opposite directions (e.g., "over" vs "under")

#### Hard Constraint Enhancements (`src/similarity/calculator.py`)
- Added direction mismatch detection to hard constraints
- Prevents matching markets with opposite directions (e.g., "BTC over $50k" vs "BTC under $50k")

### Usage

The enhanced text cleaning is automatically used in the normalization pipeline. Direction detection is applied during similarity calculation.

### Example

```python
from src.normalization.text_cleaner import detect_direction_mismatch

# This will detect mismatch
title1 = "Bitcoin will close above $50,000"
title2 = "Bitcoin will close below $50,000"
is_mismatch = detect_direction_mismatch(title1, title2)  # True
```

## 2. Enhanced Arbitrage Calculator

### New Module: `src/arbitrage/enhanced_calculator.py`

This module provides production-ready arbitrage detection with:

#### Key Features

1. **Real Bid/Ask Prices**: Uses actual order book bid/ask instead of mid prices
2. **Order Book Depth**: Calculates available liquidity at profitable prices
3. **Dynamic Fee Calculation**: Market-specific fees instead of hardcoded 5%
4. **Gas Cost Estimation**: Accounts for Polymarket L2 gas costs
5. **Position Sizing**: Based on order book depth, not just liquidity
6. **Structured Trade Instructions**: JSON output ready for trading engine

#### Data Structures

```python
@dataclass
class EnhancedArbitrageOpportunity:
    # Market identifiers
    kalshi_market_id: str
    polymarket_market_id: str
    
    # Prices (bid/ask)
    kalshi_bid: float
    kalshi_ask: float
    polymarket_bid: float
    polymarket_ask: float
    
    # Execution costs
    kalshi_fee_rate: float
    polymarket_fee_rate: float
    polymarket_gas_cost_usd: float
    
    # Profitability
    net_profit_per_share: float
    roi_percent: float
    
    # Position sizing
    max_position_size: float
    recommended_position_size: float
    available_liquidity: float
    
    # Trade instructions (structured)
    trade_instructions: Dict[str, Any]
```

#### Usage

```python
from src.arbitrage.enhanced_calculator import calculate_enhanced_arbitrage

opportunity = calculate_enhanced_arbitrage(
    market_k=kalshi_market,
    market_p=polymarket_market,
    order_book_k=kalshi_order_book,  # Optional
    order_book_p=polymarket_order_book,  # Optional
    min_edge_percent=0.01,  # 1% minimum edge
    min_liquidity_usd=1000.0,  # $1k minimum liquidity
)

if opportunity.opportunity_type != "none":
    print(f"Profit: {opportunity.net_profit_per_share:.4f} per share")
    print(f"Recommended position: ${opportunity.recommended_position_size:.2f}")
    print(f"Trade instructions: {opportunity.trade_instructions}")
```

#### Trade Instructions Format

The `trade_instructions` field provides structured output:

```json
{
  "strategy": "direct_spread",
  "legs": [
    {
      "exchange": "kalshi",
      "market_id": "MARKET-123",
      "side": "buy",
      "outcome": "yes",
      "price": 0.52,
      "size": 5000.0,
      "estimated_cost": 2600.0
    },
    {
      "exchange": "polymarket",
      "market_id": "0xabc...",
      "side": "sell",
      "outcome": "yes",
      "price": 0.55,
      "size": 5000.0,
      "estimated_revenue": 2750.0
    }
  ],
  "expected_profit_usd": 150.0,
  "expected_roi_percent": 5.77
}
```

## 3. Structured Logging

### New Module: `src/utils/bonding_logger.py`

Provides structured logging for:
- Bonding candidate decisions
- Arbitrage opportunities
- API errors
- Price updates

#### Key Functions

1. **`log_bonding_candidate()`**: Logs similarity calculations and acceptance/rejection
2. **`log_arbitrage_opportunity()`**: Logs arbitrage detection and trade execution
3. **`log_api_error()`**: Logs API failures for monitoring
4. **`log_price_update()`**: Logs price updates for tracking

#### Example Log Output

```json
{
  "event_type": "bonding_candidate",
  "timestamp": "2025-01-20T12:00:00Z",
  "market_kalshi_id": "MARKET-123",
  "market_polymarket_id": "0xabc...",
  "was_accepted": true,
  "tier": 1,
  "similarity_score": 0.87,
  "p_match": 0.92,
  "features": {
    "text_similarity": 0.85,
    "entity_similarity": 0.90,
    "time_alignment": 0.95,
    "outcome_similarity": 1.0,
    "resolution_similarity": 0.80
  }
}
```

#### Building Labeled Datasets

The structured logs can be exported to CSV for building labeled datasets:

```python
from src.utils.bonding_logger import export_bonding_logs_to_csv

export_bonding_logs_to_csv(
    log_file_path="logs/bonding.log",
    output_csv_path="labeled_pairs.csv",
    event_type="bonding_candidate",
)
```

## 4. Order Book Integration

### API Client Enhancements

#### Kalshi Client (`src/ingestion/kalshi_client.py`)
- Added `get_market_order_book()`: Extracts bid/ask from market data
- Uses `yes_bid` and `yes_ask` fields from Kalshi API

#### Polymarket Client (`src/ingestion/polymarket_client.py`)
- Added `get_market_order_book()`: Fetches order book from CLOB API
- Falls back gracefully if order book unavailable

### Usage

```python
from src.ingestion.kalshi_client import KalshiClient
from src.ingestion.polymarket_client import PolymarketCLOBClient

kalshi = KalshiClient()
poly_clob = PolymarketCLOBClient()

# Get order books
k_order_book = kalshi.get_market_order_book("MARKET-123")
p_order_book = poly_clob.get_market_order_book("token_id_abc")
```

## 5. Configuration Recommendations

### Environment Variables

Add to `.env`:

```bash
# Fee rates (can be overridden per market in metadata)
KALSHI_DEFAULT_FEE_RATE=0.02
POLYMARKET_DEFAULT_FEE_RATE=0.02
POLYMARKET_GAS_COST_USD=0.10

# Arbitrage thresholds
MIN_EDGE_PERCENT=0.01  # 1% minimum edge
MIN_LIQUIDITY_USD=1000.0  # $1k minimum liquidity
MAX_POSITION_SIZE_USD=10000.0  # $10k max position
```

### Similarity Thresholds

Current thresholds in `src/config.py` are already tuned based on production data. The new direction detection will reduce false positives.

## 6. Migration Guide

### Using Enhanced Arbitrage Calculator

Replace calls to `calculate_arbitrage()` with `calculate_enhanced_arbitrage()`:

**Before:**
```python
from src.arbitrage.calculator import calculate_arbitrage

opportunity = calculate_arbitrage(market_k, market_p)
```

**After:**
```python
from src.arbitrage.enhanced_calculator import calculate_enhanced_arbitrage

opportunity = calculate_enhanced_arbitrage(
    market_k, market_p,
    order_book_k=order_book_k,  # Optional but recommended
    order_book_p=order_book_p,   # Optional but recommended
)
```

### API Route Updates

Update API routes to use enhanced calculator:

```python
from src.arbitrage.enhanced_calculator import calculate_enhanced_arbitrage

@router.get("/arbitrage/{kalshi_id}/{polymarket_id}")
async def get_arbitrage_opportunity(...):
    # Fetch order books
    k_order_book = kalshi_client.get_market_order_book(kalshi_id)
    p_order_book = poly_client.get_market_order_book(polymarket_token_id)
    
    # Calculate enhanced arbitrage
    opportunity = calculate_enhanced_arbitrage(
        market_k, market_p,
        order_book_k=k_order_book,
        order_book_p=p_order_book,
    )
    
    return opportunity
```

## 7. Testing Recommendations

### Unit Tests

1. Test direction mismatch detection:
```python
def test_direction_mismatch():
    assert detect_direction_mismatch("over 50", "under 50") == True
    assert detect_direction_mismatch("over 50", "over 50") == False
```

2. Test enhanced arbitrage calculator:
```python
def test_enhanced_arbitrage():
    opportunity = calculate_enhanced_arbitrage(market_k, market_p)
    assert opportunity.net_profit_per_share > 0
    assert opportunity.trade_instructions["legs"] == 2
```

### Integration Tests

1. Test order book fetching from both APIs
2. Test end-to-end arbitrage detection with real market data
3. Test structured logging output format

## 8. Next Steps

### Immediate Priorities

1. **Integrate Enhanced Calculator**: Update API routes to use `calculate_enhanced_arbitrage()`
2. **Fetch Real Order Books**: Update price updater to fetch and store order book data
3. **Monitor Logs**: Set up log aggregation to analyze bonding decisions
4. **Build Labeled Dataset**: Export logs to CSV and label true/false positives

### Future Enhancements

1. **Machine Learning Model**: Train on labeled dataset to improve similarity scoring
2. **Real-Time Order Book Streaming**: WebSocket integration for live order book updates
3. **Slippage Modeling**: More sophisticated slippage estimation based on order book depth
4. **Risk Management**: Add position sizing based on portfolio risk limits

## 9. Performance Considerations

### Order Book Caching

Order books should be cached and refreshed frequently (every 1-5 seconds for active markets):

```python
from src.utils.cache import cache_order_book

# Cache order book with 5 second TTL
cache_order_book(market_id, order_book, ttl_seconds=5)
```

### Batch Processing

When scanning many markets, batch order book requests:

```python
# Fetch order books in parallel
with ThreadPoolExecutor(max_workers=10) as executor:
    order_books = executor.map(
        lambda m: get_order_book(m.id),
        markets
    )
```

## 10. Monitoring and Alerts

### Key Metrics to Track

1. **Bonding Accuracy**: % of Tier 1 bonds that resolve correctly
2. **False Positive Rate**: % of bonds that are incorrectly matched
3. **Arbitrage Detection Rate**: % of bonds with profitable arbitrage
4. **Average Edge**: Mean net profit per share across opportunities
5. **Order Book Staleness**: Age of order book data

### Alerts

- Alert if Tier 1 bond resolves incorrectly (critical)
- Alert if order book data is >10 seconds old
- Alert if API error rate >5% in 5 minutes
- Alert if no arbitrage opportunities detected for >1 hour (may indicate system issue)

## Summary

These improvements make the arbitrage engine production-ready by:

1. ✅ **Better Matching**: Direction detection reduces false positives
2. ✅ **Realistic Execution**: Bid/ask prices and order book depth for accurate profit calculation
3. ✅ **Dynamic Costs**: Market-specific fees and gas costs
4. ✅ **Structured Output**: Trade instructions ready for execution
5. ✅ **Observability**: Structured logging for analysis and debugging

The system is now ready for production use with proper monitoring and gradual rollout.

