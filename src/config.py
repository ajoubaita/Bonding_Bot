"""Configuration management for Bonding Bot.

Uses pydantic BaseSettings to load configuration from environment variables.
"""

from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field, validator


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Database Configuration
    database_url: str = Field(
        default="postgresql://bonding_user:bonding_pass@localhost:5432/bonding_agent",
        description="PostgreSQL connection URL"
    )

    # Redis Configuration
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL"
    )

    # API Authentication
    bonding_api_key: str = Field(
        default="dev-key-change-in-production",
        description="Internal API key for service-to-service auth"
    )

    # External API Endpoints
    kalshi_api_base: str = Field(
        default="https://api.elections.kalshi.com/trade-api/v2",
        description="Kalshi API base URL (v2)"
    )
    kalshi_api_key: Optional[str] = Field(
        default=None,
        description="Kalshi API key for authentication"
    )
    polymarket_gamma_api_base: str = Field(
        default="https://gamma-api.polymarket.com",
        description="Polymarket Gamma API base URL"
    )
    polymarket_clob_api_base: str = Field(
        default="https://clob.polymarket.com",
        description="Polymarket CLOB API base URL"
    )
    polymarket_api_key: Optional[str] = Field(
        default=None,
        description="Polymarket API key for authentication"
    )

    # ML Models
    embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence transformer model for embeddings"
    )
    spacy_model: str = Field(
        default="en_core_web_sm",
        description="spaCy model for NER"
    )

    # Performance Settings
    candidate_limit: int = Field(
        default=50,
        description="Max candidates per market (increased from 20 for better matching)"
    )
    similarity_calc_timeout_ms: int = Field(
        default=50,
        description="Timeout for per-pair similarity calculation (ms)"
    )
    bond_registry_cache_ttl_sec: int = Field(
        default=60,
        description="Cache TTL for bond registry (seconds)"
    )
    api_rate_limit_per_min: int = Field(
        default=100,
        description="API rate limit per client per minute"
    )

    # Polling Intervals
    kalshi_poll_interval_sec: int = Field(
        default=60,
        description="Kalshi market polling interval (seconds)"
    )
    polymarket_poll_interval_sec: int = Field(
        default=60,
        description="Polymarket market polling interval (seconds)"
    )

    # Price Update Intervals (LATENCY OPTIMIZATION)
    price_update_interval_sec: int = Field(
        default=10,
        description="Price update interval for bonded markets (seconds) - reduced from 60s for faster arbitrage detection"
    )

    # Feature Weights (must sum to 1.0)
    weight_text: float = Field(
        default=0.35,
        description="Weight for text similarity feature"
    )
    weight_entity: float = Field(
        default=0.25,
        description="Weight for entity similarity feature"
    )
    weight_time: float = Field(
        default=0.15,
        description="Weight for time alignment feature"
    )
    weight_outcome: float = Field(
        default=0.20,
        description="Weight for outcome similarity feature"
    )
    weight_resolution: float = Field(
        default=0.05,
        description="Weight for resolution source similarity feature"
    )

    # Tier Thresholds - EMERGENCY FIX (Dec 24, 2025)
    # AUDIT FOUND: 80-85% false positive rate in Tier 1 bonds!
    # Issue: p_match is severely miscalibrated, allowing similarity_score of 0.48-0.59
    # Action: Dramatically raise ALL thresholds to prevent catastrophic trading losses

    # CRITICAL: Aggregate similarity_score threshold (weighted average of all features)
    tier1_min_similarity_score: float = Field(
        default=0.80,
        description="MINIMUM aggregate similarity score for Tier 1 (was allowing 0.48-0.59!)"
    )
    tier2_min_similarity_score: float = Field(
        default=0.70,
        description="MINIMUM aggregate similarity score for Tier 2"
    )

    tier1_p_match_threshold: float = Field(
        default=0.95,
        description="Raised from 0.85 - p_match was assigning 0.96 to false positives"
    )
    tier2_p_match_threshold: float = Field(
        default=0.90,
        description="Raised from 0.80 - p_match is badly miscalibrated"
    )

    # Tier 1 Additional Requirements - STRICTER ENFORCEMENT
    # ALL of these must pass in addition to aggregate similarity_score and p_match
    tier1_min_text_score: float = Field(default=0.90)  # RAISED from 0.85 - text must match very closely
    tier1_min_entity_score: float = Field(default=0.70)  # NEW - entity overlap required
    tier1_min_outcome_score: float = Field(default=0.98)  # RAISED from 0.95 - outcomes must be nearly identical
    tier1_min_time_score: float = Field(default=0.50)  # RAISED from 0.01 - time windows must align
    tier1_min_resolution_score: float = Field(default=0.20)  # Keep at 0.20 (many markets don't have this)

    # Tier 2 Additional Requirements
    tier2_min_text_score: float = Field(default=0.80)  # RAISED from 0.75
    tier2_min_entity_score: float = Field(default=0.50)  # NEW - entity overlap required
    tier2_min_outcome_score: float = Field(default=0.90)  # RAISED from 0.85
    tier2_min_time_score: float = Field(default=0.30)  # RAISED from 0.01

    # Hard Constraint Thresholds
    # CRITICAL FIX: Tightened to reject low-quality candidates earlier
    hard_constraint_min_text_score: float = Field(default=0.70)  # Raised from 0.50
    hard_constraint_min_entity_score: float = Field(default=0.0)  # Many valid matches have 0 entity overlap
    hard_constraint_max_time_delta_days: int = Field(default=90)  # Reduced from 150 - tighter time window

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)"
    )
    log_format: str = Field(
        default="json",
        description="Log format (json or text)"
    )

    # Environment
    environment: str = Field(
        default="development",
        description="Environment (development, staging, production)"
    )

    @validator("weight_text", "weight_entity", "weight_time", "weight_outcome", "weight_resolution")
    def weights_must_be_positive(cls, v):
        """Ensure all weights are positive."""
        if v < 0:
            raise ValueError("Feature weights must be non-negative")
        return v

    def validate_weights_sum(self) -> None:
        """Validate that feature weights sum to 1.0."""
        total = (
            self.weight_text
            + self.weight_entity
            + self.weight_time
            + self.weight_outcome
            + self.weight_resolution
        )
        if abs(total - 1.0) > 0.001:  # Allow small floating point error
            raise ValueError(
                f"Feature weights must sum to 1.0, got {total}. "
                f"Adjust weights in environment variables."
            )

    class Config:
        """Pydantic config."""
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()

# Validate weights on import
settings.validate_weights_sum()
