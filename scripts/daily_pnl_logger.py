#!/usr/bin/env python3
"""Daily P/L logging script for Bonding Bot.

Aggregates daily trading activity and calculates consolidated P/L.
Designed to run daily at 12:01 AM via cronjob.

Usage:
    # Log P/L for previous day (default)
    python3 scripts/daily_pnl_logger.py

    # Log P/L for specific date
    python3 scripts/daily_pnl_logger.py --date 2025-01-27

    # Specify custom output directory
    python3 scripts/daily_pnl_logger.py --output-dir /var/log/bonding_bot/daily_pnl
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List
import argparse


def load_trades(trades_path: Path) -> List[Dict[str, Any]]:
    """Load trade history from JSON file.

    Args:
        trades_path: Path to trades JSON file

    Returns:
        List of trade dictionaries
    """
    if not trades_path.exists():
        print(f"Warning: Trades file not found at {trades_path}")
        return []

    try:
        with open(trades_path, 'r') as f:
            trades = json.load(f)
        return trades
    except Exception as e:
        print(f"Error loading trades: {e}")
        return []


def load_portfolio(portfolio_path: Path) -> Dict[str, Any]:
    """Load current portfolio state from JSON file.

    Args:
        portfolio_path: Path to portfolio JSON file

    Returns:
        Portfolio dictionary
    """
    if not portfolio_path.exists():
        print(f"Warning: Portfolio file not found at {portfolio_path}")
        return {}

    try:
        with open(portfolio_path, 'r') as f:
            portfolio = json.load(f)
        return portfolio
    except Exception as e:
        print(f"Error loading portfolio: {e}")
        return {}


def filter_trades_by_date(trades: List[Dict[str, Any]], target_date: str) -> List[Dict[str, Any]]:
    """Filter trades executed on a specific date.

    Args:
        trades: List of all trades
        target_date: Target date in YYYY-MM-DD format

    Returns:
        List of trades from target date
    """
    daily_trades = []

    for trade in trades:
        timestamp_str = trade.get("timestamp", "")
        if not timestamp_str:
            continue

        # Parse timestamp and extract date
        try:
            timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
            trade_date = timestamp.date().isoformat()

            if trade_date == target_date:
                daily_trades.append(trade)
        except Exception as e:
            print(f"Warning: Could not parse timestamp {timestamp_str}: {e}")
            continue

    return daily_trades


def calculate_daily_pnl(daily_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate P/L metrics for a single day.

    Args:
        daily_trades: List of trades from a single day

    Returns:
        Dictionary with daily P/L metrics
    """
    if not daily_trades:
        return {
            "total_trades": 0,
            "total_profit": 0.0,
            "total_cost": 0.0,
            "avg_profit_per_trade": 0.0,
            "avg_profit_pct": 0.0,
            "best_trade_profit": 0.0,
            "worst_trade_profit": 0.0,
            "total_shares_traded": 0.0,
            "trades_by_tier": {
                "tier1": 0,
                "tier2": 0,
                "tier3": 0,
            },
            "trade_details": [],
        }

    # Aggregate metrics
    total_trades = len(daily_trades)
    total_profit = sum(t.get("expected_profit", 0.0) for t in daily_trades)
    total_cost = sum(t.get("total_cost", 0.0) for t in daily_trades)
    total_shares = sum(t.get("kalshi_size", 0.0) for t in daily_trades)

    profits = [t.get("expected_profit", 0.0) for t in daily_trades]
    profit_pcts = [t.get("profit_pct", 0.0) for t in daily_trades]

    avg_profit_per_trade = total_profit / total_trades if total_trades > 0 else 0.0
    avg_profit_pct = sum(profit_pcts) / total_trades if total_trades > 0 else 0.0

    best_trade_profit = max(profits) if profits else 0.0
    worst_trade_profit = min(profits) if profits else 0.0

    # Count by tier
    tier_counts = {
        "tier1": sum(1 for t in daily_trades if t.get("tier") == 1),
        "tier2": sum(1 for t in daily_trades if t.get("tier") == 2),
        "tier3": sum(1 for t in daily_trades if t.get("tier") == 3),
    }

    # Summarize trade details
    trade_details = []
    for trade in daily_trades:
        trade_details.append({
            "trade_id": trade.get("trade_id"),
            "timestamp": trade.get("timestamp"),
            "bond_id": trade.get("bond_id"),
            "strategy": f"{trade.get('kalshi_side')} Kalshi + {trade.get('poly_side')} Poly",
            "position_size": trade.get("kalshi_size", 0.0),
            "total_cost": trade.get("total_cost", 0.0),
            "expected_profit": trade.get("expected_profit", 0.0),
            "profit_pct": trade.get("profit_pct", 0.0),
            "tier": trade.get("tier"),
        })

    return {
        "total_trades": total_trades,
        "total_profit": round(total_profit, 2),
        "total_cost": round(total_cost, 2),
        "avg_profit_per_trade": round(avg_profit_per_trade, 2),
        "avg_profit_pct": round(avg_profit_pct, 2),
        "best_trade_profit": round(best_trade_profit, 2),
        "worst_trade_profit": round(worst_trade_profit, 2),
        "total_shares_traded": round(total_shares, 2),
        "trades_by_tier": tier_counts,
        "trade_details": trade_details,
    }


def generate_daily_summary(
    target_date: str,
    daily_pnl: Dict[str, Any],
    portfolio: Dict[str, Any],
) -> Dict[str, Any]:
    """Generate consolidated daily summary.

    Args:
        target_date: Target date in YYYY-MM-DD format
        daily_pnl: Daily P/L metrics
        portfolio: Current portfolio state

    Returns:
        Consolidated daily summary
    """
    return {
        "date": target_date,
        "generated_at": datetime.utcnow().isoformat(),
        "daily_pnl": daily_pnl,
        "portfolio_snapshot": {
            "current_balance": portfolio.get("current_balance", 0.0),
            "starting_balance": portfolio.get("starting_balance", 0.0),
            "net_profit": portfolio.get("net_profit", 0.0),
            "total_return_pct": portfolio.get("total_return_pct", 0.0),
            "total_trades": portfolio.get("total_trades", 0),
            "win_rate": portfolio.get("win_rate", 0.0),
            "active_positions": portfolio.get("active_positions", 0),
            "locked_capital": portfolio.get("locked_capital", 0.0),
        },
    }


def save_daily_summary(summary: Dict[str, Any], output_dir: Path, target_date: str):
    """Save daily summary to JSON file.

    Args:
        summary: Daily summary dictionary
        output_dir: Directory to save the file
        target_date: Target date for filename
    """
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename: pnl_YYYY-MM-DD.json
    filename = f"pnl_{target_date}.json"
    output_path = output_dir / filename

    try:
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)

        print(f"✓ Daily P/L summary saved to: {output_path}")
        print(f"  Date: {target_date}")
        print(f"  Total Trades: {summary['daily_pnl']['total_trades']}")
        print(f"  Total Profit: ${summary['daily_pnl']['total_profit']:.2f}")
        print(f"  Avg Profit/Trade: ${summary['daily_pnl']['avg_profit_per_trade']:.2f}")
        print(f"  Portfolio Balance: ${summary['portfolio_snapshot']['current_balance']:.2f}")

    except Exception as e:
        print(f"Error saving daily summary: {e}")
        sys.exit(1)


def main():
    """Main entry point for daily P/L logger."""
    parser = argparse.ArgumentParser(
        description="Daily P/L Logger for Bonding Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Log P/L for previous day (default)
  python3 scripts/daily_pnl_logger.py

  # Log P/L for specific date
  python3 scripts/daily_pnl_logger.py --date 2025-01-27

  # Specify custom output directory
  python3 scripts/daily_pnl_logger.py --output-dir /var/log/bonding_bot/daily_pnl
        """
    )

    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date in YYYY-MM-DD format (default: previous day)"
    )

    parser.add_argument(
        "--trades-path",
        type=str,
        default="/tmp/bonding_bot_trades.json",
        help="Path to trades JSON file (default: /tmp/bonding_bot_trades.json)"
    )

    parser.add_argument(
        "--portfolio-path",
        type=str,
        default="/tmp/bonding_bot_portfolio.json",
        help="Path to portfolio JSON file (default: /tmp/bonding_bot_portfolio.json)"
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="/var/log/bonding_bot/daily_pnl",
        help="Output directory for daily P/L files (default: /var/log/bonding_bot/daily_pnl)"
    )

    args = parser.parse_args()

    # Determine target date (default: previous day)
    if args.date:
        target_date = args.date
    else:
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        target_date = yesterday.isoformat()

    print(f"\n{'='*80}")
    print("BONDING BOT - DAILY P/L LOGGER")
    print(f"{'='*80}")
    print(f"Target Date: {target_date}")
    print(f"Trades Path: {args.trades_path}")
    print(f"Portfolio Path: {args.portfolio_path}")
    print(f"Output Directory: {args.output_dir}")
    print(f"{'='*80}\n")

    # Load data
    trades_path = Path(args.trades_path)
    portfolio_path = Path(args.portfolio_path)
    output_dir = Path(args.output_dir)

    print("Loading trade history...")
    all_trades = load_trades(trades_path)
    print(f"  Loaded {len(all_trades)} total trades")

    print("Loading portfolio state...")
    portfolio = load_portfolio(portfolio_path)
    print(f"  Current Balance: ${portfolio.get('current_balance', 0.0):.2f}")

    # Filter trades for target date
    print(f"\nFiltering trades for {target_date}...")
    daily_trades = filter_trades_by_date(all_trades, target_date)
    print(f"  Found {len(daily_trades)} trades on {target_date}")

    # Calculate daily P/L
    print("\nCalculating daily P/L metrics...")
    daily_pnl = calculate_daily_pnl(daily_trades)

    # Generate summary
    print("Generating daily summary...")
    summary = generate_daily_summary(target_date, daily_pnl, portfolio)

    # Save to file
    print("\nSaving daily summary...")
    save_daily_summary(summary, output_dir, target_date)

    print(f"\n{'='*80}")
    print("DAILY P/L LOGGING COMPLETE")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
