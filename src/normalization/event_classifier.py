"""Event type and geo scope classification."""

from typing import Dict, List, Optional
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
            # NFL Teams (all 32 teams - city names and nicknames)
            "buffalo bills", "miami dolphins", "new england patriots", "new york jets",
            "baltimore ravens", "cincinnati bengals", "cleveland browns", "pittsburgh steelers",
            "houston texans", "indianapolis colts", "jacksonville jaguars", "tennessee titans",
            "denver broncos", "kansas city chiefs", "las vegas raiders", "los angeles chargers",
            "dallas cowboys", "new york giants", "philadelphia eagles", "washington commanders",
            "chicago bears", "detroit lions", "green bay packers", "minnesota vikings",
            "atlanta falcons", "carolina panthers", "new orleans saints", "tampa bay buccaneers",
            "arizona cardinals", "los angeles rams", "san francisco 49ers", "seattle seahawks",
            # NFL city shortcuts (match city-only references)
            "buffalo", "miami", "new england", "baltimore", "cincinnati", "cleveland", "pittsburgh",
            "houston", "indianapolis", "jacksonville", "tennessee", "denver", "kansas city",
            "las vegas", "dallas", "philadelphia", "washington", "chicago", "detroit",
            "green bay", "minnesota", "atlanta", "carolina", "new orleans", "tampa bay",
            "arizona", "seattle", "san francisco",
            # NBA Teams (all 30 teams)
            "boston celtics", "brooklyn nets", "new york knicks", "philadelphia 76ers", "toronto raptors",
            "chicago bulls", "cleveland cavaliers", "detroit pistons", "indiana pacers", "milwaukee bucks",
            "atlanta hawks", "charlotte hornets", "miami heat", "orlando magic", "washington wizards",
            "denver nuggets", "minnesota timberwolves", "oklahoma city thunder", "portland trail blazers", "utah jazz",
            "golden state warriors", "los angeles clippers", "los angeles lakers", "phoenix suns", "sacramento kings",
            "dallas mavericks", "houston rockets", "memphis grizzlies", "new orleans pelicans", "san antonio spurs",
            # Player prop patterns (statistical markers)
            "over ", "under ", "o/u ", "+", "total", "prop",
        ],
        "categories": ["sports"],
        "entities": ["people"],  # Athletes are people entities
        "boost": 4,  # Increased from 2 to override entertainment's 3x boost
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


def classify_sport_type(title: str) -> Optional[str]:
    """Detect specific sport type (NFL, NHL, NBA, MLB, etc.).

    Args:
        title: Clean market title

    Returns:
        Sport type string or None if not sports
    """
    title_lower = title.lower()

    # NFL markers (most distinctive first)
    nfl_markers = [
        # NFL-specific terms
        "nfl", "super bowl", "quarterback", "qb", "running back", "wide receiver",
        "tight end", "yards", "touchdowns", "passing yards", "rushing yards",
        "receiving yards", "field goal", "touchdown", "afc", "nfc",
        # NFL teams
        "bills", "dolphins", "patriots", "jets", "ravens", "bengals", "browns",
        "steelers", "texans", "colts", "jaguars", "titans", "broncos", "chiefs",
        "raiders", "chargers", "cowboys", "giants", "eagles", "commanders",
        "bears", "lions", "packers", "vikings", "falcons", "panthers", "saints",
        "buccaneers", "cardinals", "rams", "49ers", "seahawks"
    ]

    # NHL markers
    nhl_markers = [
        # NHL-specific terms
        "nhl", "stanley cup", "hockey", "puck", "goalie", "hat trick",
        "power play", "shootout", "overtime goal", "ice hockey",
        # NHL teams (distinctive names that won't overlap with NFL)
        "avalanche", "flames", "oilers", "canucks", "maple leafs", "senators",
        "canadiens", "bruins", "sabres", "red wings", "blackhawks", "blues",
        "predators", "jets", "wild", "penguins", "capitals", "blue jackets",
        "hurricanes", "devils", "islanders", "rangers", "flyers", "sharks",
        "ducks", "kings", "golden knights", "coyotes", "kraken", "lightning",
        "panthers"
    ]

    # NBA markers
    nba_markers = [
        # NBA-specific terms
        "nba", "basketball", "three-pointer", "free throw", "rebounds",
        "assists", "blocks", "steals", "dunks", "playoff series",
        # NBA teams
        "celtics", "nets", "knicks", "76ers", "raptors", "bulls", "cavaliers",
        "pistons", "pacers", "bucks", "hawks", "hornets", "heat", "magic",
        "wizards", "nuggets", "timberwolves", "thunder", "trail blazers", "jazz",
        "warriors", "clippers", "lakers", "suns", "kings", "mavericks", "rockets",
        "grizzlies", "pelicans", "spurs"
    ]

    # MLB markers
    mlb_markers = [
        # MLB-specific terms
        "mlb", "baseball", "home run", "strikeout", "innings", "pitcher",
        "batting average", "rbi", "world series", "playoff game",
        # MLB teams (distinctive names)
        "yankees", "red sox", "orioles", "rays", "blue jays", "white sox",
        "guardians", "tigers", "royals", "twins", "astros", "angels", "athletics",
        "mariners", "mets", "phillies", "braves", "marlins", "nationals", "cubs",
        "brewers", "pirates", "reds", "rockies", "dodgers", "padres", "giants",
        "diamondbacks", "rangers"
    ]

    # Count markers for each sport
    nfl_count = sum(1 for marker in nfl_markers if marker in title_lower)
    nhl_count = sum(1 for marker in nhl_markers if marker in title_lower)
    nba_count = sum(1 for marker in nba_markers if marker in title_lower)
    mlb_count = sum(1 for marker in mlb_markers if marker in title_lower)

    # Return sport with most markers
    counts = {
        "NFL": nfl_count,
        "NHL": nhl_count,
        "NBA": nba_count,
        "MLB": mlb_count,
    }

    max_count = max(counts.values())
    if max_count >= 1:
        # Get sport with highest count
        for sport, count in counts.items():
            if count == max_count:
                return sport

    # Default to None if no clear sport detected
    return None


def detect_parlay_market(title: str) -> bool:
    """Detect if market is a parlay (multi-game/multi-outcome market).

    Args:
        title: Clean market title

    Returns:
        True if market appears to be a parlay
    """
    title_lower = title.lower()

    # Parlay indicators
    parlay_keywords = [
        "parlay", "multi-game", "multigame", "both teams", "all teams",
        "and", " & ", "combo", "combined", "multiple games"
    ]

    # Check for explicit parlay keywords
    if any(keyword in title_lower for keyword in parlay_keywords):
        return True

    # Check for multiple team names (indicates multi-game parlay)
    # Count occurrences of outcome separators (with or without spaces)
    outcome_separators = title_lower.count(",yes") + title_lower.count(", yes")
    outcome_separators += title_lower.count(",no") + title_lower.count(", no")

    # If 3+ outcome separators, likely a parlay
    # NOTE: Lowered from 3 to 2 to catch 2-game parlays
    if outcome_separators >= 2:
        return True

    # Check for multiple "vs" or "vs." (multiple games)
    vs_count = title_lower.count(" vs ") + title_lower.count(" vs. ")
    if vs_count >= 2:
        return True

    return False


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
