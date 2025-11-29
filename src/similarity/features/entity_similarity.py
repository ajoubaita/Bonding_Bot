"""Entity similarity feature calculator."""

from typing import Set, Dict, List
import structlog

from src.models import Market

logger = structlog.get_logger()


def jaccard_similarity(set1: Set, set2: Set) -> float:
    """Calculate Jaccard similarity between two sets.

    Args:
        set1: First set
        set2: Second set

    Returns:
        Jaccard similarity [0, 1]
    """
    if not set1 and not set2:
        return 1.0  # Both empty = perfect match

    if not set1 or not set2:
        return 0.0  # One empty, one not = no match

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    if union == 0:
        return 0.0

    return intersection / union


def normalize_entity(entity: str) -> str:
    """Normalize entity for comparison.

    Args:
        entity: Entity string

    Returns:
        Normalized entity (lowercased, stripped)
    """
    return entity.lower().strip()


def extract_entity_sets(entities: Dict[str, List[str]]) -> Dict[str, Set[str]]:
    """Extract and normalize entity sets from entities dict.

    Args:
        entities: Dictionary of entity lists by type

    Returns:
        Dictionary of normalized entity sets by type
    """
    if not entities:
        return {
            "tickers": set(),
            "people": set(),
            "organizations": set(),
            "countries": set(),
            "misc": set(),
        }

    return {
        "tickers": {normalize_entity(e) for e in entities.get("tickers", [])},
        "people": {normalize_entity(e) for e in entities.get("people", [])},
        "organizations": {normalize_entity(e) for e in entities.get("organizations", [])},
        "countries": {normalize_entity(e) for e in entities.get("countries", [])},
        "misc": {normalize_entity(e) for e in entities.get("misc", [])},
    }


def calculate_entity_similarity(market_k: Market, market_p: Market) -> dict:
    """Calculate entity similarity features between two markets.

    Args:
        market_k: Kalshi market
        market_p: Polymarket market

    Returns:
        Dictionary with entity similarity scores:
        {
            "score_entity": float,        # Base Jaccard score [0, 1]
            "score_entity_final": float,  # Final score with bonuses [0, 1]
            "bonus_ticker": float,        # Ticker exact match bonus [0, 1]
            "bonus_person": float,        # Person exact match bonus [0, 1]
            "bonus_org": float,           # Organization overlap bonus [0, 1]
        }
    """
    result = {
        "score_entity": 0.0,
        "score_entity_final": 0.0,
        "bonus_ticker": 0.0,
        "bonus_person": 0.0,
        "bonus_org": 0.0,
    }

    try:
        # Extract entity sets
        entities_k = extract_entity_sets(market_k.entities)
        entities_p = extract_entity_sets(market_p.entities)

        # Flatten all entities
        all_k = set()
        all_p = set()
        for entity_type in ["tickers", "people", "organizations", "countries", "misc"]:
            all_k.update(entities_k[entity_type])
            all_p.update(entities_p[entity_type])

        # Calculate base Jaccard similarity
        score_entity = jaccard_similarity(all_k, all_p)

        # Calculate type-specific bonuses
        bonus_ticker = 0.0
        if entities_k["tickers"] and entities_p["tickers"]:
            if entities_k["tickers"] == entities_p["tickers"]:
                bonus_ticker = 1.0  # Exact match
            elif entities_k["tickers"] & entities_p["tickers"]:
                bonus_ticker = 0.5  # Partial overlap

        bonus_person = 0.0
        if entities_k["people"] and entities_p["people"]:
            if entities_k["people"] == entities_p["people"]:
                bonus_person = 1.0  # Exact match
            elif entities_k["people"] & entities_p["people"]:
                bonus_person = 0.5  # Partial overlap

        bonus_org = 0.0
        if entities_k["organizations"] and entities_p["organizations"]:
            if entities_k["organizations"] & entities_p["organizations"]:
                bonus_org = 0.5  # Any overlap

        # Calculate final score with bonuses
        score_entity_final = min(
            1.0,
            score_entity + 0.2 * bonus_ticker + 0.15 * bonus_person + 0.1 * bonus_org
        )

        result = {
            "score_entity": float(score_entity),
            "score_entity_final": float(score_entity_final),
            "bonus_ticker": float(bonus_ticker),
            "bonus_person": float(bonus_person),
            "bonus_org": float(bonus_org),
        }

        logger.debug(
            "entity_similarity_calculated",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            score=score_entity_final,
            bonuses={
                "ticker": bonus_ticker,
                "person": bonus_person,
                "org": bonus_org,
            },
        )

    except Exception as e:
        logger.error(
            "entity_similarity_error",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            error=str(e),
        )

    return result
