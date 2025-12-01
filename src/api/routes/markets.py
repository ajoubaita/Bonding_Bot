"""Markets endpoints for ingestion and candidate generation."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
import structlog

from src.models import get_db, Market
from src.config import settings

logger = structlog.get_logger()

router = APIRouter()


# Request/Response schemas
class OutcomeSchema(BaseModel):
    """Outcome schema for market outcomes."""
    label: str
    token_id: Optional[str] = None
    value: Optional[bool] = None
    min: Optional[float] = None
    max: Optional[float] = None


class MarketMetadata(BaseModel):
    """Market metadata."""
    liquidity: Optional[float] = None
    volume: Optional[float] = None


class MarketIngestRequest(BaseModel):
    """Single market ingest request."""
    id: str
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    resolution_date: str
    resolution_source: Optional[str] = None
    outcome_type: str  # "yes_no", "discrete_brackets", "scalar_range"
    outcomes: List[OutcomeSchema]
    metadata: Optional[MarketMetadata] = None


class BatchIngestRequest(BaseModel):
    """Batch market ingest request."""
    platform: str = Field(..., pattern="^(kalshi|polymarket)$")
    markets: List[MarketIngestRequest]


class IngestResult(BaseModel):
    """Result for single market ingestion."""
    id: str
    status: str  # "success", "failed", "updated"
    normalized_id: Optional[str] = None
    error: Optional[str] = None


class BatchIngestResponse(BaseModel):
    """Batch ingest response."""
    ingested: int
    failed: int
    results: List[IngestResult]


class QuickSimilarity(BaseModel):
    """Quick similarity scores for candidate."""
    text_score: float
    entity_score: float
    time_score: float
    overall: float


class CandidateMarket(BaseModel):
    """Candidate market for bonding."""
    market_id: str
    platform: str
    title: str
    quick_similarity: QuickSimilarity
    rank: int


class CandidatesResponse(BaseModel):
    """Candidates response."""
    market_id: str
    platform: str
    candidates: List[CandidateMarket]
    total_candidates: int


@router.post("/ingest", response_model=BatchIngestResponse)
async def ingest_markets(
    request: BatchIngestRequest,
    db: Session = Depends(get_db)
):
    """Batch ingest raw markets from either platform.

    Args:
        request: Batch ingest request with platform and markets
        db: Database session

    Returns:
        BatchIngestResponse with ingestion results
    """
    logger.info(
        "ingest_markets_start",
        platform=request.platform,
        count=len(request.markets),
    )

    results = []
    ingested_count = 0
    failed_count = 0

    for market_data in request.markets:
        try:
            # Check if market already exists
            existing = db.query(Market).filter(Market.id == market_data.id).first()

            if existing:
                # Update existing market
                # TODO: Implement normalization pipeline
                existing.raw_title = market_data.title
                existing.raw_description = market_data.description
                existing.updated_at = datetime.utcnow()
                db.commit()

                results.append(IngestResult(
                    id=market_data.id,
                    status="updated",
                    normalized_id=existing.id,
                ))
                ingested_count += 1
            else:
                # Create new market
                # TODO: Implement full normalization pipeline
                # For now, create minimal record
                from datetime import datetime

                new_market = Market(
                    id=market_data.id,
                    platform=request.platform,
                    status="active",
                    raw_title=market_data.title,
                    raw_description=market_data.description,
                    category=market_data.category,
                    resolution_source=market_data.resolution_source,
                    time_window={
                        "resolution_date": market_data.resolution_date,
                    },
                    outcome_schema={
                        "type": market_data.outcome_type,
                        "outcomes": [o.dict() for o in market_data.outcomes],
                    },
                    market_metadata={
                        "ingestion_version": "v1.0.0",
                        "liquidity": market_data.metadata.liquidity if market_data.metadata else None,
                        "volume": market_data.metadata.volume if market_data.metadata else None,
                    },
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )

                db.add(new_market)
                db.commit()

                results.append(IngestResult(
                    id=market_data.id,
                    status="success",
                    normalized_id=new_market.id,
                ))
                ingested_count += 1

        except Exception as e:
            logger.error(
                "ingest_market_failed",
                market_id=market_data.id,
                error=str(e),
            )
            results.append(IngestResult(
                id=market_data.id,
                status="failed",
                error=str(e),
            ))
            failed_count += 1

    logger.info(
        "ingest_markets_complete",
        platform=request.platform,
        ingested=ingested_count,
        failed=failed_count,
    )

    return BatchIngestResponse(
        ingested=ingested_count,
        failed=failed_count,
        results=results,
    )


@router.get("/{platform}/{market_id}/candidates", response_model=CandidatesResponse)
async def get_candidates(
    platform: str,
    market_id: str,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Get cross-platform candidate markets for bonding.

    Args:
        platform: Source platform (kalshi or polymarket)
        market_id: Market ID to find candidates for
        limit: Maximum number of candidates to return
        db: Database session

    Returns:
        CandidatesResponse with candidate markets
    """
    from src.similarity.calculator import calculate_similarity
    from src.similarity.tier_assigner import assign_tier
    from sqlalchemy import text

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

    # Get source market
    source_market = db.query(Market).filter(Market.id == market_id).first()
    if not source_market:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "MARKET_NOT_FOUND",
                    "message": f"Market {market_id} not found",
                }
            },
        )

    # Check if source market has embedding
    if source_market.text_embedding is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "MISSING_EMBEDDING",
                    "message": f"Market {market_id} has no text embedding",
                }
            },
        )

    logger.info(
        "get_candidates_start",
        platform=platform,
        market_id=market_id,
        limit=limit,
    )

    # Determine opposite platform
    target_platform = "polymarket" if platform == "kalshi" else "kalshi"

    # Use pgvector cosine similarity to find top candidates
    # Multiply by limit factor to account for hard constraint filtering
    search_limit = min(limit * 5, settings.candidate_limit * 2)

    similarity_query = text("""
        SELECT
            id,
            raw_title,
            1 - (text_embedding <=> :embedding) as cosine_similarity
        FROM markets
        WHERE platform = :target_platform
        AND text_embedding IS NOT NULL
        AND status = 'active'
        ORDER BY text_embedding <=> :embedding
        LIMIT :limit
    """)

    results = db.execute(
        similarity_query,
        {
            "embedding": str(source_market.text_embedding),
            "target_platform": target_platform,
            "limit": search_limit,
        }
    ).fetchall()

    logger.info(
        "vector_search_complete",
        platform=platform,
        market_id=market_id,
        candidates_found=len(results),
    )

    # Calculate detailed similarity for each candidate
    candidates = []
    for row in results:
        candidate_market = db.query(Market).filter(Market.id == row.id).first()
        if not candidate_market:
            continue

        # Determine which is Kalshi and which is Polymarket
        if platform == "kalshi":
            market_k = source_market
            market_p = candidate_market
        else:
            market_k = candidate_market
            market_p = source_market

        # Calculate detailed similarity
        try:
            similarity_result = calculate_similarity(market_k, market_p)

            # Assign tier
            tier = assign_tier(
                p_match=similarity_result["p_match"],
                features=similarity_result["features"],
                hard_constraints_violated=similarity_result["hard_constraints_violated"]
            )

            # Only include Tier 1 and Tier 2 candidates
            if tier <= 2:
                candidates.append(CandidateMarket(
                    market_id=candidate_market.id,
                    platform=candidate_market.platform,
                    title=candidate_market.raw_title or "",
                    quick_similarity=QuickSimilarity(
                        text_score=similarity_result["features"]["text"]["score_text"],
                        entity_score=similarity_result["features"]["entity"]["score_entity_final"],
                        time_score=similarity_result["features"]["time"]["score_time_final"],
                        overall=similarity_result["similarity_score"],
                    ),
                    rank=len(candidates) + 1,
                ))

        except Exception as e:
            logger.error(
                "calculate_similarity_failed",
                source_id=source_market.id,
                candidate_id=candidate_market.id,
                error=str(e),
            )
            continue

        # Stop once we have enough good candidates
        if len(candidates) >= limit:
            break

    # Sort by overall similarity score
    candidates.sort(key=lambda x: x.quick_similarity.overall, reverse=True)

    # Update ranks
    for i, candidate in enumerate(candidates):
        candidate.rank = i + 1

    logger.info(
        "get_candidates_complete",
        platform=platform,
        market_id=market_id,
        total_candidates=len(candidates),
    )

    return CandidatesResponse(
        market_id=market_id,
        platform=platform,
        candidates=candidates,
        total_candidates=len(candidates),
    )
