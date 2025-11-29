#!/usr/bin/env python3
"""Initialize database and create tables."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.models import Base, engine
import structlog

logger = structlog.get_logger()


def init_database():
    """Initialize database with schema."""
    try:
        logger.info("database_init_start")

        # Create all tables
        Base.metadata.create_all(bind=engine)

        logger.info("database_init_complete", tables=list(Base.metadata.tables.keys()))

        print("✓ Database initialized successfully")
        print(f"✓ Created tables: {', '.join(Base.metadata.tables.keys())}")

    except Exception as e:
        logger.error("database_init_failed", error=str(e))
        print(f"✗ Database initialization failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    init_database()
