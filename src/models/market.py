"""Market model for normalized market data."""

from datetime import datetime
from typing import Optional, Dict, Any
from sqlalchemy import Column, String, Text, JSON, DateTime, Float, Index
from sqlalchemy.dialects.postgresql import JSONB
from pgvector.sqlalchemy import Vector
from src.models.database import Base


class Market(Base):
    """Normalized market data from Kalshi or Polymarket."""

    __tablename__ = "markets"

    # Primary key
    id = Column(String, primary_key=True)  # Platform-specific market ID

    # Platform identifier
    platform = Column(String, nullable=False, index=True)  # "kalshi" or "polymarket"
    condition_id = Column(String, nullable=True, index=True)  # Polymarket condition ID

    # Status
    status = Column(String, nullable=False, index=True)  # "active", "closed", "resolved"

    # Raw text
    raw_title = Column(Text, nullable=True)
    raw_description = Column(Text, nullable=True)

    # Cleaned text
    clean_title = Column(Text, nullable=True)
    clean_description = Column(Text, nullable=True)

    # Classification
    category = Column(String, nullable=True, index=True)  # "politics", "crypto", etc.
    event_type = Column(String, nullable=True)  # "election", "price_target", etc.

    # Entities (JSONB for flexible structure)
    entities = Column(JSONB, nullable=True)
    # Format: {"tickers": [...], "people": [...], "organizations": [...], "countries": [...], "misc": [...]}

    # Geographic scope
    geo_scope = Column(String, nullable=True)  # "global", "US", "EU", etc.

    # Time information (JSONB for flexible structure)
    time_window = Column(JSONB, nullable=True)
    # Format: {"start": ISO8601, "end": ISO8601, "resolution_date": ISO8601, "granularity": "day|week|month"}

    # Resolution information
    resolution_source = Column(String, nullable=True)  # "BLS", "FOMC", "CoinGecko", etc.

    # Outcome schema (JSONB)
    outcome_schema = Column(JSONB, nullable=True)
    # Format varies by type:
    # yes_no: {"type": "yes_no", "polarity": "positive|negative", "outcomes": [...]}
    # discrete_brackets: {"type": "discrete_brackets", "unit": "dollars", "brackets": [...]}
    # scalar_range: {"type": "scalar_range", "min": X, "max": Y, "unit": "..."}

    # Text embedding (384-dimensional vector from all-MiniLM-L6-v2)
    text_embedding = Column(Vector(384), nullable=True)

    # Market metadata (JSONB) - renamed from 'metadata' to avoid SQLAlchemy conflict
    market_metadata = Column(JSONB, nullable=True)
    # Format: {"created_at": ISO8601, "last_updated": ISO8601, "ingestion_version": "v1.0.0", "liquidity": float, "volume": float}

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Indexes
    __table_args__ = (
        Index('idx_markets_platform', 'platform'),
        Index('idx_markets_category', 'category'),
        Index('idx_markets_status', 'status'),
        Index('idx_markets_condition_id', 'condition_id'),
        # Vector similarity index (created via migration)
        # Index('idx_markets_embedding', 'text_embedding', postgresql_using='ivfflat', postgresql_ops={'text_embedding': 'vector_cosine_ops'}),
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "platform": self.platform,
            "condition_id": self.condition_id,
            "status": self.status,
            "raw_title": self.raw_title,
            "raw_description": self.raw_description,
            "clean_title": self.clean_title,
            "clean_description": self.clean_description,
            "category": self.category,
            "event_type": self.event_type,
            "entities": self.entities,
            "geo_scope": self.geo_scope,
            "time_window": self.time_window,
            "resolution_source": self.resolution_source,
            "outcome_schema": self.outcome_schema,
            "market_metadata": self.market_metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        """String representation."""
        return f"<Market(id={self.id}, platform={self.platform}, title={self.clean_title[:50]})>"
