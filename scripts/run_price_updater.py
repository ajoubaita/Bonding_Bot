#!/usr/bin/env python3
"""Run the price updater service."""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.workers.price_updater import PriceUpdater
from src.config import settings

if __name__ == "__main__":
    # Get update interval from settings (default 60 seconds)
    interval = getattr(settings, 'price_update_interval_sec', 60)

    updater = PriceUpdater()

    try:
        updater.run_continuous(interval_seconds=interval)
    except KeyboardInterrupt:
        print("\nShutting down price updater...")
    finally:
        updater.close()
