#!/usr/bin/env python3
"""Run market polling service."""

import sys
from pathlib import Path
import signal

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.workers.market_poller import MarketPoller
import structlog

logger = structlog.get_logger()

# Global poller instance
poller = None


def signal_handler(sig, frame):
    """Handle shutdown signal."""
    logger.info("shutdown_signal_received", signal=sig)
    if poller:
        poller.stop()
    sys.exit(0)


def main():
    """Run market poller."""
    global poller

    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    logger.info("market_poller_starting")

    try:
        poller = MarketPoller()

        # Run initial poll
        logger.info("market_poller_initial_poll")
        result = poller.poll_once()
        logger.info("market_poller_initial_poll_complete", result=result)

        # Start continuous polling
        logger.info("market_poller_continuous_start")
        poller.run_continuous()

    except Exception as e:
        logger.error("market_poller_failed", error=str(e))
        sys.exit(1)
    finally:
        if poller:
            poller.close()

    logger.info("market_poller_stopped")


if __name__ == "__main__":
    main()
