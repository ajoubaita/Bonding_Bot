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


class ArbitrageOpportunityResponse(BaseModel):
    """Arbitrage opportunity response."""
    # Market identifiers
    kalshi_market_id: str
    polymarket_market_id: str
    kalshi_title: str
    polymarket_title: str

    # Opportunity type
    opportunity_type: str  # "direct_spread", "hedged_position", "none"

    # Prices
    kalshi_yes_price: float
    kalshi_no_price: float
    polymarket_yes_price: float
    polymarket_no_price: float

    # Arbitrage metrics
    spread_yes: float
    spread_no: float
    hedged_sum_k_yes_p_no: float
    hedged_sum_k_no_p_yes: float

    # Profit calculation
    best_strategy: str
    gross_profit: float
    estimated_fees: float
    net_profit: float
    roi_percent: float

    # Risk metrics
    liquidity_score: float
    volume_score: float
    confidence_score: float

    # Additional context
    min_liquidity: float
    min_volume: float
    warnings: List[str]


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
                hard_constraints_violated=similarity_result["hard_constraints_violated"],
                market_k_id=source_market.id,
                market_p_id=candidate_market.id,
                similarity_result=similarity_result,
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


@router.get("/arbitrage/{kalshi_id}/{polymarket_id}", response_model=ArbitrageOpportunityResponse)
async def calculate_arbitrage_opportunity(
    kalshi_id: str,
    polymarket_id: str,
    fee_rate: float = 0.05,
    db: Session = Depends(get_db)
):
    """Calculate arbitrage opportunity between Kalshi and Polymarket markets.

    Args:
        kalshi_id: Kalshi market ID
        polymarket_id: Polymarket market ID
        fee_rate: Total estimated fee rate (default 5%)
        db: Database session

    Returns:
        ArbitrageOpportunityResponse with detailed arbitrage metrics
    """
    from src.arbitrage import calculate_arbitrage

    logger.info(
        "calculate_arbitrage_opportunity_start",
        kalshi_id=kalshi_id,
        polymarket_id=polymarket_id,
        fee_rate=fee_rate,
    )

    # Get Kalshi market
    kalshi_market = db.query(Market).filter(
        Market.id == kalshi_id,
        Market.platform == "kalshi"
    ).first()

    if not kalshi_market:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "MARKET_NOT_FOUND",
                    "message": f"Kalshi market {kalshi_id} not found",
                }
            },
        )

    # Get Polymarket market
    polymarket_market = db.query(Market).filter(
        Market.id == polymarket_id,
        Market.platform == "polymarket"
    ).first()

    if not polymarket_market:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "MARKET_NOT_FOUND",
                    "message": f"Polymarket market {polymarket_id} not found",
                }
            },
        )

    # Calculate arbitrage opportunity using enhanced calculator
    try:
        from src.arbitrage.enhanced_calculator import calculate_enhanced_arbitrage
        from src.ingestion.kalshi_client import KalshiClient
        from src.ingestion.polymarket_client import PolymarketCLOBClient
        
        # Fetch order books for accurate calculation
        kalshi_client = KalshiClient()
        poly_client = PolymarketCLOBClient()
        
        try:
            k_order_book = kalshi_client.get_market_order_book(kalshi_id)
            p_token_id = polymarket_market.condition_id or polymarket_id
            p_order_book = poly_client.get_market_order_book(p_token_id)
        except Exception as e:
            logger.warning(
                "order_book_fetch_failed",
                kalshi_id=kalshi_id,
                poly_id=polymarket_id,
                error=str(e),
            )
            k_order_book = None
            p_order_book = None
        
        opportunity = calculate_enhanced_arbitrage(
            market_k=kalshi_market,
            market_p=polymarket_market,
            order_book_k=k_order_book,
            order_book_p=p_order_book,
            min_edge_percent=fee_rate,  # Use fee_rate as minimum edge
        )
        
        # Close clients
        kalshi_client.close()
        poly_client.close()

        logger.info(
            "calculate_arbitrage_opportunity_complete",
            kalshi_id=kalshi_id,
            polymarket_id=polymarket_id,
            opportunity_type=opportunity.opportunity_type,
            net_profit=opportunity.net_profit_per_share,
            roi_percent=opportunity.roi_percent,
        )
        
        # Log arbitrage opportunity for analysis
        from src.utils.bonding_logger import log_arbitrage_opportunity
        log_arbitrage_opportunity(
            bond_id=f"{kalshi_id}_{polymarket_id}",
            market_k_id=kalshi_id,
            market_p_id=polymarket_id,
            opportunity={
                "has_arbitrage": opportunity.opportunity_type != "none",
                "arbitrage_type": opportunity.opportunity_type,
                "profit_per_dollar": opportunity.net_profit_per_share,
                "kalshi_price": opportunity.kalshi_mid,
                "polymarket_price": opportunity.polymarket_mid,
                "min_volume": 0.0,  # Will be calculated from markets
                "min_liquidity": opportunity.available_liquidity,
                "max_position_size": opportunity.recommended_position_size,
                "warnings": opportunity.warnings,
                "price_age_kalshi_sec": opportunity.price_staleness_sec,
                "price_age_poly_sec": opportunity.price_staleness_sec,
            },
        )

        # Convert enhanced opportunity to response model
        # Map enhanced calculator fields to response model
        k_yes = opportunity.kalshi_mid
        k_no = 1.0 - k_yes if k_yes else 0.5
        p_yes = opportunity.polymarket_mid
        p_no = 1.0 - p_yes if p_yes else 0.5
        
        return ArbitrageOpportunityResponse(
            kalshi_market_id=opportunity.kalshi_market_id,
            polymarket_market_id=opportunity.polymarket_market_id,
            kalshi_title=opportunity.kalshi_title,
            polymarket_title=opportunity.polymarket_title,
            opportunity_type=opportunity.opportunity_type,
            kalshi_yes_price=k_yes,
            kalshi_no_price=k_no,
            polymarket_yes_price=p_yes,
            polymarket_no_price=p_no,
            spread_yes=k_yes - p_yes,
            spread_no=k_no - p_no,
            hedged_sum_k_yes_p_no=k_yes + p_no,
            hedged_sum_k_no_p_yes=k_no + p_yes,
            best_strategy=opportunity.trade_instructions.get("strategy", ""),
            gross_profit=opportunity.gross_spread,
            estimated_fees=(opportunity.kalshi_fee_rate + opportunity.polymarket_fee_rate) * opportunity.gross_spread,
            net_profit=opportunity.net_profit_per_share,
            roi_percent=opportunity.roi_percent,
            liquidity_score=opportunity.liquidity_score,
            volume_score=opportunity.volume_score,
            confidence_score=opportunity.confidence_score,
            min_liquidity=opportunity.available_liquidity,
            min_volume=0.0,  # Not directly available in enhanced calculator
            warnings=opportunity.warnings,
        )

    except Exception as e:
        logger.error(
            "calculate_arbitrage_opportunity_failed",
            kalshi_id=kalshi_id,
            polymarket_id=polymarket_id,
            error=str(e),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "CALCULATION_FAILED",
                    "message": f"Failed to calculate arbitrage: {str(e)}",
                }
            },
        )
