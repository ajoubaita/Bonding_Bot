"""Event type and geo scope classification."""

from typing import Dict, List
import structlog

logger = structlog.get_logger()


# Event type classification rules
EVENT_TYPE_RULES = {
    "election": {
        "keywords": ["election", "elect", "win", "president", "senate", "congress", "vote", "ballot"],
        "categories": ["politics"],
        "entities": ["people"],
    },
    "price_target": {
        "keywords": ["price", "reach", "hit", "above", "below", "dollar", "usd", "btc", "eth"],
        "categories": ["crypto", "finance", "stocks"],
        "entities": ["tickers"],
    },
    "rate_decision": {
        "keywords": ["rate", "interest", "fed", "fomc", "basis points", "bps", "hike", "cut"],
        "categories": ["finance", "economics"],
        "entities": ["organizations"],
    },
    "economic_indicator": {
        "keywords": ["gdp", "inflation", "cpi", "unemployment", "jobs", "nonfarm", "payroll"],
        "categories": ["economics", "finance"],
        "entities": ["organizations"],
    },
    "sports": {
        "keywords": ["super bowl", "world cup", "championship", "win", "finals", "playoffs"],
        "categories": ["sports"],
        "entities": ["misc"],
    },
    "geopolitical": {
        "keywords": ["war", "conflict", "invasion", "treaty", "sanctions", "military"],
        "categories": ["politics", "international"],
        "entities": ["countries"],
    },
    "corporate": {
        "keywords": ["earnings", "revenue", "acquisition", "merger", "ceo", "ipo", "stock split"],
        "categories": ["finance", "business"],
        "entities": ["organizations", "people"],
    },
    "regulatory": {
        "keywords": ["approve", "ban", "regulation", "law", "sec", "ftc", "doj", "court"],
        "categories": ["politics", "legal"],
        "entities": ["organizations"],
    },
}


def classify_event_type(category: str, entities: Dict[str, List[str]], title: str) -> str:
    """Classify event type based on category, entities, and title.

    Args:
        category: Market category
        entities: Extracted entities dictionary
        title: Clean market title

    Returns:
        Event type string
    """
    title_lower = title.lower()
    category_lower = category.lower()

    # Score each event type
    scores = {}

    for event_type, rules in EVENT_TYPE_RULES.items():
        score = 0

        # Check category match
        if category_lower in rules.get("categories", []):
            score += 3

        # Check keyword match
        keywords = rules.get("keywords", [])
        keyword_matches = sum(1 for keyword in keywords if keyword in title_lower)
        score += keyword_matches * 2

        # Check entity type match
        required_entity_types = rules.get("entities", [])
        for entity_type in required_entity_types:
            if entities.get(entity_type):
                score += 1

        scores[event_type] = score

    # Get highest scoring event type
    if scores:
        best_event_type = max(scores, key=scores.get)
        best_score = scores[best_event_type]

        if best_score > 0:
            logger.debug(
                "event_type_classified",
                event_type=best_event_type,
                score=best_score,
                title_preview=title[:50],
            )
            return best_event_type

    # Default
    logger.debug(
        "event_type_classified_default",
        category=category,
        title_preview=title[:50],
    )
    return "general"


def determine_geo_scope(entities: Dict[str, List[str]], title: str) -> str:
    """Determine geographic scope of market.

    Args:
        entities: Extracted entities dictionary
        title: Clean market title

    Returns:
        Geo scope ("global", "US", "EU", "specific_country", etc.)
    """
    title_lower = title.lower()
    countries = [c.lower() for c in entities.get("countries", [])]

    # Check for US-specific
    us_indicators = ["us", "usa", "united states", "america", "american"]
    if any(indicator in title_lower for indicator in us_indicators):
        return "US"

    if any(country in ["us", "usa", "united states"] for country in countries):
        return "US"

    # Check for EU-specific
    eu_indicators = ["eu", "europe", "european"]
    if any(indicator in title_lower for indicator in eu_indicators):
        return "EU"

    # Check for specific country
    if len(countries) == 1:
        return countries[0].upper()

    # Check for multiple countries or global
    if len(countries) > 1:
        return "multi_country"

    # Check for global indicators
    global_indicators = ["global", "world", "worldwide", "international"]
    if any(indicator in title_lower for indicator in global_indicators):
        return "global"

    # Default to US (most common for prediction markets)
    return "US"
