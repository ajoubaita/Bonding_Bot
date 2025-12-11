"""Event type and geo scope classification."""

from typing import Dict, List
import structlog

logger = structlog.get_logger()


# Event type classification rules
EVENT_TYPE_RULES = {
    "sports": {
        # Put sports FIRST with higher priority and more specific keywords
        "keywords": [
            # Player statistics markers
            "yards", "touchdowns", "points scored", "rushing", "passing", "receiving",
            "rebounds", "assists", "goals", "saves", "strikeouts", "home runs",
            # Scoring/betting terms
            "spread", "o/u", "over", "under", "moneyline",
            # Generic sports terms (with multi-word phrases for specificity)
            "super bowl", "world cup", "championship", "playoffs", "playoff",
            "game", "match", "vs", "vs.", "wins by", "score",
            # Team types
            "team", "club", "fc", "united",
            # Leagues/competitions
            "nfl", "nba", "mlb", "nhl", "mls", "premier league", "champions league",
            "ncaa", "college football", "college basketball",
            # Player positions
            "quarterback", "running back", "wide receiver", "tight end",
            "forward", "guard", "center", "pitcher", "outfielder",
        ],
        "categories": ["sports"],
        "entities": ["people"],  # Athletes are people entities
        "boost": 2,  # Give sports higher weight to prevent election misclassification
    },
    "election": {
        # Removed "win" to avoid sports false positives
        "keywords": ["election", "elect", "president", "presidential", "senate", "congress",
                     "vote", "ballot", "governor", "mayor", "representative", "democrat", "republican"],
        "categories": ["politics"],
        "entities": ["people"],
    },
    "price_target": {
        "keywords": ["price", "reach", "hit", "above", "below", "dollar", "usd", "btc", "eth",
                     "bitcoin", "ethereum", "crypto", "cryptocurrency", "solana", "xrp"],
        "categories": ["crypto", "finance", "stocks"],
        "entities": ["tickers"],
    },
    "rate_decision": {
        "keywords": ["rate", "interest", "fed", "fomc", "basis points", "bps", "hike", "cut",
                     "federal reserve", "central bank", "monetary policy"],
        "categories": ["finance", "economics"],
        "entities": ["organizations"],
    },
    "economic_indicator": {
        "keywords": ["gdp", "inflation", "cpi", "unemployment", "jobs", "nonfarm", "payroll",
                     "employment", "retail sales", "manufacturing"],
        "categories": ["economics", "finance"],
        "entities": ["organizations"],
    },
    "geopolitical": {
        "keywords": ["war", "conflict", "invasion", "treaty", "sanctions", "military",
                     "diplomatic", "nuclear", "missile"],
        "categories": ["politics", "international"],
        "entities": ["countries"],
    },
    "corporate": {
        "keywords": ["earnings", "revenue", "acquisition", "merger", "ceo", "ipo", "stock split",
                     "quarterly", "annual report", "dividend"],
        "categories": ["finance", "business"],
        "entities": ["organizations", "people"],
    },
    "regulatory": {
        "keywords": ["approve", "ban", "regulation", "law", "sec", "ftc", "doj", "court",
                     "lawsuit", "ruling", "verdict", "appeal"],
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

        # Apply boost multiplier if specified
        boost = rules.get("boost", 1)
        score = score * boost

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
