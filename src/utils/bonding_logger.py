"""Structured logging utilities for bonding and arbitrage analysis.

This module provides structured logging that makes it easy to:
- Analyze bonding decisions offline
- Track arbitrage opportunities over time
- Debug false positives/negatives
- Build labeled datasets for model training
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
import json

logger = structlog.get_logger()


def log_bonding_candidate(
    market_k_id: str,
    market_p_id: str,
    similarity_result: Dict[str, Any],
    was_accepted: bool,
    tier: Optional[int] = None,
    rejection_reason: Optional[str] = None,
) -> None:
    """Log a bonding candidate decision for offline analysis.
    
    This structured log can be used to:
    - Build labeled datasets (accepted = positive, rejected = negative)
    - Analyze false positives/negatives
    - Tune similarity thresholds
    
    Args:
        market_k_id: Kalshi market ID
        market_p_id: Polymarket market ID
        similarity_result: Full similarity calculation result
        was_accepted: Whether bond was accepted
        tier: Tier assigned (if accepted)
        rejection_reason: Reason for rejection (if rejected)
    """
    features = similarity_result.get("features", {})
    
    log_data = {
        "event_type": "bonding_candidate",
        "timestamp": datetime.utcnow().isoformat(),
        "market_kalshi_id": market_k_id,
        "market_polymarket_id": market_p_id,
        "was_accepted": was_accepted,
        "tier": tier,
        "rejection_reason": rejection_reason,
        "similarity_score": similarity_result.get("similarity_score"),
        "p_match": similarity_result.get("p_match"),
        "hard_constraints_violated": similarity_result.get("hard_constraints_violated", False),
        "features": {
            "text_similarity": features.get("text", {}).get("score_text"),
            "entity_similarity": features.get("entity", {}).get("score_entity_final"),
            "time_alignment": features.get("time", {}).get("score_time_final"),
            "outcome_similarity": features.get("outcome", {}).get("score_outcome"),
            "resolution_similarity": features.get("resolution", {}).get("score_resolution"),
            "time_delta_days": features.get("time", {}).get("delta_days"),
        },
    }
    
    # Add market metadata for context
    if "market_k" in similarity_result:
        market_k = similarity_result["market_k"]
        log_data["market_k_metadata"] = {
            "title": market_k.clean_title or market_k.raw_title,
            "category": market_k.category,
            "resolution_date": market_k.time_window.get("resolution_date") if market_k.time_window else None,
        }
    
    if "market_p" in similarity_result:
        market_p = similarity_result["market_p"]
        log_data["market_p_metadata"] = {
            "title": market_p.clean_title or market_p.raw_title,
            "category": market_p.category,
            "resolution_date": market_p.time_window.get("resolution_date") if market_p.time_window else None,
        }
    
    logger.info("bonding_candidate_decision", **log_data)


def log_arbitrage_opportunity(
    bond_id: str,
    market_k_id: str,
    market_p_id: str,
    opportunity: Dict[str, Any],
    was_traded: bool = False,
    trade_result: Optional[Dict[str, Any]] = None,
) -> None:
    """Log an arbitrage opportunity for analysis.
    
    Args:
        bond_id: Bond pair ID
        market_k_id: Kalshi market ID
        market_p_id: Polymarket market ID
        opportunity: Arbitrage opportunity details
        was_traded: Whether trade was executed
        trade_result: Trade execution result (if traded)
    """
    log_data = {
        "event_type": "arbitrage_opportunity",
        "timestamp": datetime.utcnow().isoformat(),
        "bond_id": bond_id,
        "market_kalshi_id": market_k_id,
        "market_polymarket_id": market_p_id,
        "has_arbitrage": opportunity.get("has_arbitrage", False),
        "arbitrage_type": opportunity.get("arbitrage_type"),
        "profit_per_dollar": opportunity.get("profit_per_dollar", 0.0),
        "kalshi_price": opportunity.get("kalshi_price"),
        "polymarket_price": opportunity.get("polymarket_price"),
        "min_volume": opportunity.get("min_volume", 0.0),
        "min_liquidity": opportunity.get("min_liquidity", 0.0),
        "max_position_size": opportunity.get("max_position_size", 0.0),
        "warnings": opportunity.get("warnings", []),
        "price_age_kalshi_sec": opportunity.get("price_age_kalshi_sec"),
        "price_age_poly_sec": opportunity.get("price_age_poly_sec"),
        "was_traded": was_traded,
    }
    
    if trade_result:
        log_data["trade_result"] = trade_result
    
    logger.info("arbitrage_opportunity_detected", **log_data)


def log_api_error(
    platform: str,
    endpoint: str,
    status_code: Optional[int],
    error_message: str,
    retry_count: int = 0,
) -> None:
    """Log API errors for monitoring and debugging.
    
    Args:
        platform: "kalshi" or "polymarket"
        endpoint: API endpoint that failed
        status_code: HTTP status code (if available)
        error_message: Error message
        retry_count: Number of retries attempted
    """
    log_data = {
        "event_type": "api_error",
        "timestamp": datetime.utcnow().isoformat(),
        "platform": platform,
        "endpoint": endpoint,
        "status_code": status_code,
        "error_message": error_message,
        "retry_count": retry_count,
    }
    
    logger.error("api_error", **log_data)


def log_price_update(
    platform: str,
    market_id: str,
    price: float,
    price_type: str = "mid",  # "bid", "ask", or "mid"
    order_book_depth: Optional[float] = None,
) -> None:
    """Log price updates for monitoring.

    Args:
        platform: "kalshi" or "polymarket"
        market_id: Market ID
        price: Updated price
        price_type: Type of price (bid/ask/mid)
        order_book_depth: Available depth at this price
    """
    log_data = {
        "event_type": "price_update",
        "timestamp": datetime.utcnow().isoformat(),
        "platform": platform,
        "market_id": market_id,
        "price": price,
        "price_type": price_type,
        "order_book_depth": order_book_depth,
    }

    logger.debug("price_updated", **log_data)


def log_arbitrage_scan(
    total_bonds: int,
    opportunities: int,
    trades_executed: int,
    portfolio_balance: float,
) -> None:
    """Log arbitrage scan results for monitoring.

    This is called after each scan cycle to track trading activity.

    Args:
        total_bonds: Number of bonds scanned
        opportunities: Number of arbitrage opportunities found
        trades_executed: Number of trades executed
        portfolio_balance: Current portfolio balance
    """
    log_data = {
        "event_type": "arbitrage_scan",
        "timestamp": datetime.utcnow().isoformat(),
        "total_bonds": total_bonds,
        "opportunities_found": opportunities,
        "trades_executed": trades_executed,
        "portfolio_balance": portfolio_balance,
    }

    logger.info("arbitrage_scan_complete", **log_data)


def export_bonding_logs_to_csv(
    log_file_path: str,
    output_csv_path: str,
    event_type: str = "bonding_candidate",
) -> None:
    """Export structured logs to CSV for analysis.
    
    This is a utility function to help build labeled datasets from logs.
    
    Args:
        log_file_path: Path to JSON log file
        output_csv_path: Path to output CSV
        event_type: Event type to export (default: "bonding_candidate")
    """
    import csv
    
    # This would parse JSON logs and export to CSV
    # Implementation depends on log format (JSON lines, etc.)
    logger.info(
        "export_logs_to_csv",
        log_file=log_file_path,
        output_csv=output_csv_path,
        event_type=event_type,
    )
    
    # TODO: Implement CSV export based on actual log format
    pass

