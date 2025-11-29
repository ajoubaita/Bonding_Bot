"""Bond model for bonded market pairs."""

from datetime import datetime
from typing import Dict, Any
from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Index, CheckConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from src.models.database import Base


class Bond(Base):
    """Bonded market pair (Kalshi + Polymarket)."""

    __tablename__ = "bonds"

    # Primary key
    pair_id = Column(String, primary_key=True)

    # Foreign keys to markets
    kalshi_market_id = Column(String, ForeignKey("markets.id"), nullable=False, index=True)
    polymarket_market_id = Column(String, ForeignKey("markets.id"), nullable=False, index=True)

    # Tier (1, 2, or 3)
    tier = Column(Integer, CheckConstraint("tier IN (1, 2, 3)"), nullable=False, index=True)

    # Similarity scores
    p_match = Column(Float, nullable=False)  # Match probability [0, 1]
    similarity_score = Column(Float, nullable=False)  # Weighted similarity score [0, 1]

    # Outcome mapping (JSONB)
    outcome_mapping = Column(JSONB, nullable=False)
    # Format: {"kalshi_yes": "polymarket_token_abc", "kalshi_no": "polymarket_token_def"}

    # Feature breakdown (JSONB)
    feature_breakdown = Column(JSONB, nullable=False)
    # Format: {"text_similarity": 0.87, "entity_similarity": 0.92, ...}

    # Status
    status = Column(String, default="active", nullable=False, index=True)
    # Values: "active", "paused", "retired"

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_validated = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships (optional, for eager loading)
    # kalshi_market = relationship("Market", foreign_keys=[kalshi_market_id])
    # polymarket_market = relationship("Market", foreign_keys=[polymarket_market_id])

    # Indexes
    __table_args__ = (
        Index('idx_bonds_tier', 'tier'),
        Index('idx_bonds_status', 'status'),
        Index('idx_bonds_kalshi', 'kalshi_market_id'),
        Index('idx_bonds_poly', 'polymarket_market_id'),
        Index('idx_bonds_active_tier', 'tier', 'status'),  # Composite for common query
    )

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return {
            "pair_id": self.pair_id,
            "kalshi_market_id": self.kalshi_market_id,
            "polymarket_market_id": self.polymarket_market_id,
            "tier": self.tier,
            "p_match": self.p_match,
            "similarity_score": self.similarity_score,
            "outcome_mapping": self.outcome_mapping,
            "feature_breakdown": self.feature_breakdown,
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_validated": self.last_validated.isoformat() if self.last_validated else None,
        }

    def __repr__(self) -> str:
        """String representation."""
        return f"<Bond(pair_id={self.pair_id}, tier={self.tier}, p_match={self.p_match:.3f}, status={self.status})>"
