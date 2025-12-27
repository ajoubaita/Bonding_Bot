#!/bin/bash
# Setup script for daily P/L logging cronjob
# This script helps you set up a local cronjob to run the daily P/L logger at 12:01 AM

set -e

# Configuration
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_BIN="$(which python3)"
LOG_DIR="/var/log/bonding_bot/daily_pnl"
CRON_LOG="/var/log/bonding_bot/cron_pnl.log"

echo "============================================================"
echo "Bonding Bot - Daily P/L Cronjob Setup"
echo "============================================================"
echo ""
echo "Project Root: $PROJECT_ROOT"
echo "Python Binary: $PYTHON_BIN"
echo "Log Directory: $LOG_DIR"
echo "Cron Log File: $CRON_LOG"
echo ""

# Create log directories
echo "[1/4] Creating log directories..."
mkdir -p "$LOG_DIR"
mkdir -p "$(dirname "$CRON_LOG")"
echo "✓ Log directories created"
echo ""

# Generate the cron command
CRON_COMMAND="1 0 * * * cd $PROJECT_ROOT && $PYTHON_BIN scripts/daily_pnl_logger.py --output-dir $LOG_DIR >> $CRON_LOG 2>&1"

echo "[2/4] Generated cron command:"
echo "$CRON_COMMAND"
echo ""

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -q "daily_pnl_logger.py"; then
    echo "[3/4] WARNING: A P/L logging cronjob already exists!"
    echo ""
    echo "Current cronjob:"
    crontab -l | grep "daily_pnl_logger.py"
    echo ""
    read -p "Do you want to replace it? (y/n): " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted. No changes made."
        exit 0
    fi
    # Remove existing cron job
    crontab -l 2>/dev/null | grep -v "daily_pnl_logger.py" | crontab -
    echo "✓ Removed existing cronjob"
else
    echo "[3/4] No existing P/L cronjob found"
fi
echo ""

# Add new cron job
echo "[4/4] Adding new cronjob..."
(crontab -l 2>/dev/null; echo "$CRON_COMMAND") | crontab -
echo "✓ Cronjob added successfully"
echo ""

echo "============================================================"
echo "SETUP COMPLETE!"
echo "============================================================"
echo ""
echo "The daily P/L logger will run at 12:01 AM every day."
echo ""
echo "Useful commands:"
echo "  - View cronjobs:     crontab -l"
echo "  - View cron logs:    tail -f $CRON_LOG"
echo "  - View P/L files:    ls -lh $LOG_DIR"
echo "  - Remove cronjob:    crontab -e (then delete the line)"
echo "  - Test manually:     python3 scripts/daily_pnl_logger.py"
echo ""
echo "Note: Logs are written to $CRON_LOG"
echo "      P/L files are saved to $LOG_DIR/pnl_YYYY-MM-DD.json"
echo ""
