"""Resolution source similarity feature calculator."""

from typing import Dict, Set
import structlog

from src.models import Market

logger = structlog.get_logger()


# Mapping of similar resolution sources
SIMILAR_SOURCES: Dict[str, Set[str]] = {
    "bls": {"bureau_of_labor_statistics", "bls", "labor_statistics"},
    "fomc": {"federal_reserve", "fomc", "fed", "federal_open_market_committee"},
    "coingecko": {"coingecko", "coin_gecko"},
    "coinmarketcap": {"coinmarketcap", "coin_market_cap", "cmc"},
    "ap": {"associated_press", "ap"},
    "nyt": {"new_york_times", "nyt", "ny_times"},
    "cnn": {"cnn", "cable_news_network"},
    "fox": {"fox_news", "fox"},
    "nasdaq": {"nasdaq"},
    "nyse": {"nyse", "new_york_stock_exchange"},
}


def normalize_source(source: str) -> str:
    """Normalize resolution source string.

    Args:
        source: Resolution source string

    Returns:
        Normalized source (lowercased, underscored)
    """
    if not source:
        return "unknown"

    # Lowercase and replace spaces with underscores
    normalized = source.lower().strip().replace(" ", "_").replace("-", "_")

    # Map to canonical form
    for canonical, variants in SIMILAR_SOURCES.items():
        if normalized in variants:
            return canonical

    return normalized


def are_sources_similar(source1: str, source2: str) -> bool:
    """Check if two sources are similar.

    Args:
        source1: First source
        source2: Second source

    Returns:
        True if sources are similar
    """
    if not source1 or not source2:
        return False

    norm1 = normalize_source(source1)
    norm2 = normalize_source(source2)

    # Exact match
    if norm1 == norm2:
        return True

    # Check if both belong to same similar group
    for canonical, variants in SIMILAR_SOURCES.items():
        if norm1 in variants and norm2 in variants:
            return True

    return False


def calculate_resolution_similarity(market_k: Market, market_p: Market) -> dict:
    """Calculate resolution source similarity between two markets.

    Args:
        market_k: Kalshi market
        market_p: Polymarket market

    Returns:
        Dictionary with resolution similarity score:
        {
            "score_resolution": float,  # Resolution source similarity [0, 1]
        }
    """
    result = {
        "score_resolution": 0.3,  # Default neutral score
    }

    try:
        source_k = market_k.resolution_source
        source_p = market_p.resolution_source

        # Both unknown
        if not source_k and not source_p:
            result["score_resolution"] = 0.5  # Neutral
            return result

        # One unknown
        if not source_k or not source_p:
            result["score_resolution"] = 0.3  # Slightly negative
            return result

        # Normalize sources
        norm_k = normalize_source(source_k)
        norm_p = normalize_source(source_p)

        # Exact match
        if norm_k == norm_p and norm_k != "unknown":
            result["score_resolution"] = 1.0

        # Similar sources
        elif are_sources_similar(source_k, source_p):
            result["score_resolution"] = 0.7

        # Different sources
        else:
            result["score_resolution"] = 0.3  # Risky

        logger.debug(
            "resolution_similarity_calculated",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            source_k=norm_k,
            source_p=norm_p,
            score=result["score_resolution"],
        )

    except Exception as e:
        logger.error(
            "resolution_similarity_error",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            error=str(e),
        )

    return result
