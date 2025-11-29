"""Pairs endpoints for bond management."""

from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import structlog

from src.models import get_db, Bond, Market
from src.config import settings

logger = structlog.get_logger()

router = APIRouter()


# Request/Response schemas
class FeatureBreakdown(BaseModel):
    """Feature breakdown for similarity score."""
    text_similarity: float
    entity_similarity: float
    time_alignment: float
    outcome_similarity: float
    resolution_similarity: float


class BondPair(BaseModel):
    """Bonded market pair."""
    pair_id: str
    counterparty_market_id: str
    counterparty_platform: str
    tier: int
    p_match: float
    similarity_score: float
    outcome_mapping: Dict[str, str]
    feature_breakdown: FeatureBreakdown
    created_at: str
    last_validated: str


class PairsResponse(BaseModel):
    """Response for get pairs endpoint."""
    market_id: str
    platform: str
    bonds: List[BondPair]
    total_bonds: int


class TradingParams(BaseModel):
    """Trading parameters for a bond."""
    max_notional: float
    max_position_pct: float


class BondRegistryEntry(BaseModel):
    """Single bond in registry."""
    pair_id: str
    kalshi_market_id: str
    polymarket_condition_id: str
    tier: int
    p_match: float
    outcome_mapping: Dict[str, str]
    trading_params: TradingParams
    created_at: str


class BondRegistryResponse(BaseModel):
    """Full bond registry response."""
    bonds: List[BondRegistryEntry]
    total: int
    pagination: Dict[str, Any]


class RecomputeRequest(BaseModel):
    """Request to recompute similarities."""
    mode: str = Field(..., pattern="^(all|incremental|specific)$")
    market_ids: Optional[List[str]] = None
    blocking: bool = False
    force_refresh: bool = False


class RecomputeResults(BaseModel):
    """Results from recompute job."""
    processed: int
    new_bonds: int
    updated_bonds: int
    demoted_bonds: int
    failed: int


class RecomputeResponse(BaseModel):
    """Response for recompute request."""
    job_id: str
    status: str  # "queued", "running", "completed"
    estimated_duration_seconds: Optional[int] = None
    duration_seconds: Optional[int] = None
    markets_to_process: Optional[int] = None
    results: Optional[RecomputeResults] = None


@router.get("/{platform}/{market_id}", response_model=PairsResponse)
async def get_bonded_pairs(
    platform: str,
    market_id: str,
    include_tier: str = Query("1,2", description="Comma-separated tier numbers"),
    db: Session = Depends(get_db)
):
    """Get all bonded pairs for a specific market.

    Args:
        platform: Platform (kalshi or polymarket)
        market_id: Market ID
        include_tier: Comma-separated tier numbers (default: "1,2")
        db: Database session

    Returns:
        PairsResponse with bonded pairs
    """
    # Validate platform
    if platform not in ["kalshi", "polymarket"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_PLATFORM",
                    "message": "Platform must be 'kalshi' or 'polymarket'",
                }
            },
        )

    # Parse tier filter
    try:
        tiers = [int(t.strip()) for t in include_tier.split(",")]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "INVALID_TIER",
                    "message": "Tier must be comma-separated integers",
                }
            },
        )

    # Get market
    market = db.query(Market).filter(Market.id == market_id).first()
    if not market:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "MARKET_NOT_FOUND",
                    "message": f"Market {market_id} not found",
                }
            },
        )

    # Query bonds
    query = db.query(Bond).filter(
        Bond.status == "active",
        Bond.tier.in_(tiers),
    )

    if platform == "kalshi":
        query = query.filter(Bond.kalshi_market_id == market_id)
    else:
        query = query.filter(Bond.polymarket_market_id == market_id)

    bonds = query.all()

    # Format response
    bond_pairs = []
    for bond in bonds:
        counterparty_id = bond.polymarket_market_id if platform == "kalshi" else bond.kalshi_market_id
        counterparty_platform = "polymarket" if platform == "kalshi" else "kalshi"

        bond_pairs.append(BondPair(
            pair_id=bond.pair_id,
            counterparty_market_id=counterparty_id,
            counterparty_platform=counterparty_platform,
            tier=bond.tier,
            p_match=bond.p_match,
            similarity_score=bond.similarity_score,
            outcome_mapping=bond.outcome_mapping,
            feature_breakdown=FeatureBreakdown(**bond.feature_breakdown),
            created_at=bond.created_at.isoformat(),
            last_validated=bond.last_validated.isoformat(),
        ))

    logger.info(
        "get_bonded_pairs",
        platform=platform,
        market_id=market_id,
        tiers=tiers,
        found=len(bond_pairs),
    )

    return PairsResponse(
        market_id=market_id,
        platform=platform,
        bonds=bond_pairs,
        total_bonds=len(bond_pairs),
    )


@router.get("/bond_registry", response_model=BondRegistryResponse)
async def get_bond_registry(
    tier: Optional[int] = Query(None, description="Filter by tier"),
    status_filter: str = Query("active", description="Filter by status"),
    limit: int = Query(100, description="Page size"),
    offset: int = Query(0, description="Page offset"),
    db: Session = Depends(get_db)
):
    """Get full bond registry for trading engine.

    Args:
        tier: Filter by tier (optional)
        status_filter: Filter by status (default: active)
        limit: Page size
        offset: Page offset
        db: Database session

    Returns:
        BondRegistryResponse with all active bonds
    """
    # Build query
    query = db.query(Bond).filter(Bond.status == status_filter)
    if tier is not None:
        query = query.filter(Bond.tier == tier)

    # Get total count
    total = query.count()

    # Apply pagination
    bonds = query.offset(offset).limit(limit).all()

    # Format response
    registry_entries = []
    for bond in bonds:
        # Get polymarket condition_id
        poly_market = db.query(Market).filter(Market.id == bond.polymarket_market_id).first()
        poly_condition_id = poly_market.condition_id if poly_market else None

        # Calculate trading params based on tier
        if bond.tier == 1:
            max_notional = 10000  # TODO: Make configurable
            max_position_pct = 0.10
        elif bond.tier == 2:
            max_notional = 2000
            max_position_pct = 0.05
        else:
            max_notional = 0
            max_position_pct = 0

        registry_entries.append(BondRegistryEntry(
            pair_id=bond.pair_id,
            kalshi_market_id=bond.kalshi_market_id,
            polymarket_condition_id=poly_condition_id or bond.polymarket_market_id,
            tier=bond.tier,
            p_match=bond.p_match,
            outcome_mapping=bond.outcome_mapping,
            trading_params=TradingParams(
                max_notional=max_notional,
                max_position_pct=max_position_pct,
            ),
            created_at=bond.created_at.isoformat(),
        ))

    logger.info(
        "get_bond_registry",
        tier=tier,
        status=status_filter,
        total=total,
        returned=len(registry_entries),
    )

    return BondRegistryResponse(
        bonds=registry_entries,
        total=total,
        pagination={
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(registry_entries) < total,
        },
    )


@router.post("/recompute", response_model=RecomputeResponse)
async def recompute_similarities(
    request: RecomputeRequest,
    db: Session = Depends(get_db)
):
    """Trigger similarity recalculation.

    Args:
        request: Recompute request
        db: Database session

    Returns:
        RecomputeResponse with job details
    """
    import uuid

    job_id = f"recompute_job_{uuid.uuid4().hex[:8]}"

    # Validate request
    if request.mode == "specific" and not request.market_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "MISSING_MARKET_IDS",
                    "message": "market_ids required for mode=specific",
                }
            },
        )

    # TODO: Implement actual recompute logic via Celery
    # For now, return mock response

    logger.info(
        "recompute_similarities",
        job_id=job_id,
        mode=request.mode,
        blocking=request.blocking,
        force_refresh=request.force_refresh,
    )

    if request.blocking:
        # Blocking mode - return completed result
        return RecomputeResponse(
            job_id=job_id,
            status="completed",
            duration_seconds=0,
            results=RecomputeResults(
                processed=0,
                new_bonds=0,
                updated_bonds=0,
                demoted_bonds=0,
                failed=0,
            ),
        )
    else:
        # Async mode - return queued status
        return RecomputeResponse(
            job_id=job_id,
            status="queued",
            estimated_duration_seconds=120,
            markets_to_process=0,
        )
