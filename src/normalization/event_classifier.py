"""Event type and geo scope classification."""

from typing import Dict, List
import structlog

logger = structlog.get_logger()


# Event type classification rules with exclusion logic
EVENT_TYPE_RULES = {
    "entertainment": {
        # FIRST: Entertainment/Awards - check before sports to prevent false positives
        "keywords": [
            # Awards ceremonies
            "oscars", "academy awards", "golden globes", "emmy", "emmys", "grammy", "grammys",
            "tony awards", "bafta", "sag awards", "cannes", "sundance",
            # Award categories
            "best actor", "best actress", "best director", "best picture", "best film",
            "best supporting", "best screenplay", "best original", "best adapted",
            "nominated", "nomination", "win best", "won best",
            # Entertainment industry
            "box office", "opening weekend", "rotten tomatoes", "imdb", "streaming",
        ],
        "categories": ["entertainment", "culture"],
        "entities": ["people"],
        "boost": 3,  # High boost to override sports when these keywords present
        "exclusions": [],  # Entertainment has no exclusions
    },
    "sports": {
        # SECOND: Sports with strong exclusion rules
        "keywords": [
            # Player statistics markers
            "yards", "touchdowns", "points scored", "rushing", "passing", "receiving",
            "rebounds", "assists", "goals", "saves", "strikeouts", "home runs",
            # Scoring/betting terms
            "spread", "o/u", "over", "under", "moneyline",
            # Generic sports terms (with multi-word phrases for specificity)
            "super bowl", "world cup", "championship game", "playoffs", "playoff",
            "game", "match", "vs", "vs.", "wins by", "score",
            # Team types
            "team", "club", "fc", "united",
            # Leagues/competitions
            "nfl", "nba", "mlb", "nhl", "mls", "premier league", "champions league",
            "ncaa", "college football", "college basketball", "fifa",
            # Player positions
            "quarterback", "running back", "wide receiver", "tight end",
            "forward", "guard", "center", "pitcher", "outfielder",
            # Sports-specific verbs
            "draft pick", "traded to", "signed with", "free agent",
        ],
        "categories": ["sports"],
        "entities": ["people"],  # Athletes are people entities
        "boost": 2,  # Boost to prevent election misclassification
        # CRITICAL: Exclude sports if these keywords appear
        "exclusions": [
            # Awards/Entertainment
            "oscars", "oscar", "golden globe", "emmy", "grammy", "best actor", "best actress",
            "best director", "best picture", "nominated", "nomination", "screenplay",
            # Legal/Criminal
            "arrested", "charged", "indicted", "convicted", "sentenced", "prison",
            "lawsuit", "trial", "verdict", "guilty", "acquitted",
            # Political positions
            "elected", "appointed", "cabinet", "secretary", "ambassador",
        ],
    },
    "regulatory": {
        # Legal, criminal, judicial events
        "keywords": [
            # Legal proceedings
            "arrested", "charged", "indicted", "convicted", "sentenced", "prison", "jail",
            "lawsuit", "trial", "verdict", "guilty", "acquitted", "appeal",
            # Regulatory actions
            "approve", "ban", "regulation", "law", "sec", "ftc", "doj", "court",
            "ruling", "subpoena", "investigation", "probe",
            # Government enforcement
            "felony", "crime", "criminal", "prosecutor", "judge",
        ],
        "categories": ["politics", "legal"],
        "entities": ["organizations", "people"],
        "boost": 2,  # Boost to override sports for legal events
        "exclusions": [],
    },
    "election": {
        # Removed "win" to avoid sports false positives
        "keywords": [
            "election", "elect", "president", "presidential", "senate", "congress",
            "vote", "ballot", "governor", "mayor", "representative", "democrat", "republican",
            "primary", "caucus", "midterm", "campaign", "electoral",
        ],
        "categories": ["politics"],
        "entities": ["people"],
        "boost": 1,
        "exclusions": [],
    },
    "price_target": {
        "keywords": [
            "price", "reach", "hit", "above", "below", "dollar", "usd", "btc", "eth",
            "bitcoin", "ethereum", "crypto", "cryptocurrency", "solana", "xrp",
            "market cap", "trading at", "trades above",
        ],
        "categories": ["crypto", "finance", "stocks"],
        "entities": ["tickers"],
        "boost": 1,
        "exclusions": [],
    },
    "rate_decision": {
        "keywords": [
            "rate", "interest", "fed", "fomc", "basis points", "bps", "hike", "cut",
            "federal reserve", "central bank", "monetary policy", "yield",
        ],
        "categories": ["finance", "economics"],
        "entities": ["organizations"],
        "boost": 1,
        "exclusions": [],
    },
    "economic_indicator": {
        "keywords": [
            "gdp", "inflation", "cpi", "unemployment", "jobs", "nonfarm", "payroll",
            "employment", "retail sales", "manufacturing", "pmi", "ism",
        ],
        "categories": ["economics", "finance"],
        "entities": ["organizations"],
        "boost": 1,
        "exclusions": [],
    },
    "geopolitical": {
        "keywords": [
            "war", "conflict", "invasion", "treaty", "sanctions", "military",
            "diplomatic", "nuclear", "missile", "ceasefire", "annexation",
        ],
        "categories": ["politics", "international"],
        "entities": ["countries"],
        "boost": 1,
        "exclusions": [],
    },
    "corporate": {
        "keywords": [
            "earnings", "revenue", "acquisition", "merger", "ceo", "ipo", "stock split",
            "quarterly", "annual report", "dividend", "layoffs", "restructuring",
        ],
        "categories": ["finance", "business"],
        "entities": ["organizations", "people"],
        "boost": 1,
        "exclusions": [],
    },
}


def classify_event_type(category: str, entities: Dict[str, List[str]], title: str) -> str:
    """Classify event type based on category, entities, and title with exclusion logic.

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

        # FIRST: Check exclusions - if any exclusion keyword present, set score to -1000
        exclusions = rules.get("exclusions", [])
        if exclusions:
            has_exclusion = any(excl in title_lower for excl in exclusions)
            if has_exclusion:
                scores[event_type] = -1000
                logger.debug(
                    "event_type_excluded",
                    event_type=event_type,
                    exclusion_detected=True,
                    title_preview=title[:50],
                )
                continue  # Skip to next event type

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

    # Get highest scoring event type (excluding negative scores from exclusions)
    valid_scores = {k: v for k, v in scores.items() if v > 0}

    if valid_scores:
        best_event_type = max(valid_scores, key=valid_scores.get)
        best_score = valid_scores[best_event_type]

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
