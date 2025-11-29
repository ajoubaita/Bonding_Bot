"""Entity extraction using spaCy NER and custom patterns."""

import re
from typing import Dict, List, Set
import structlog

logger = structlog.get_logger()

# Lazy load spaCy model
_nlp = None


def get_nlp():
    """Get spaCy NLP model (lazy loaded)."""
    global _nlp
    if _nlp is None:
        try:
            import spacy
            from src.config import settings

            _nlp = spacy.load(settings.spacy_model)
            logger.info("spacy_model_loaded", model=settings.spacy_model)
        except Exception as e:
            logger.error("spacy_model_load_failed", error=str(e))
            raise
    return _nlp


# Known financial tickers
KNOWN_TICKERS = {
    "btc", "bitcoin", "eth", "ethereum", "aapl", "apple", "tsla", "tesla",
    "googl", "google", "msft", "microsoft", "amzn", "amazon", "meta",
    "nvda", "nvidia", "spy", "qqq", "dow", "s&p", "sp500", "nasdaq",
}

# Known organizations/indices
KNOWN_ORGANIZATIONS = {
    "fed", "federal reserve", "fomc", "federal open market committee",
    "bls", "bureau of labor statistics", "treasury", "sec",
    "securities and exchange commission", "cpi", "consumer price index",
    "gdp", "unemployment", "ecb", "european central bank",
}

# Known countries
KNOWN_COUNTRIES = {
    "us", "usa", "united states", "america", "china", "russia", "ukraine",
    "uk", "united kingdom", "eu", "europe", "japan", "germany", "france",
    "canada", "mexico", "brazil", "india", "israel", "iran", "north korea",
    "south korea",
}


def extract_tickers(text: str) -> Set[str]:
    """Extract financial tickers from text.

    Args:
        text: Input text

    Returns:
        Set of ticker symbols
    """
    tickers = set()

    text_lower = text.lower()

    # Check for known tickers
    for ticker in KNOWN_TICKERS:
        # Word boundary match
        pattern = r'\b' + re.escape(ticker) + r'\b'
        if re.search(pattern, text_lower):
            # Normalize to uppercase for tickers
            tickers.add(ticker.upper() if len(ticker) <= 5 else ticker.title())

    # Look for ticker patterns: $XXX or uppercase 2-5 letter words
    ticker_pattern = r'\$([A-Z]{2,5})\b|\b([A-Z]{2,5})\b'
    matches = re.findall(ticker_pattern, text)
    for match in matches:
        ticker = match[0] or match[1]
        if ticker and ticker in KNOWN_TICKERS:
            tickers.add(ticker)

    logger.debug("tickers_extracted", count=len(tickers), tickers=list(tickers))

    return tickers


def extract_people(text: str) -> Set[str]:
    """Extract people names using spaCy NER.

    Args:
        text: Input text

    Returns:
        Set of person names
    """
    people = set()

    try:
        nlp = get_nlp()
        doc = nlp(text)

        for ent in doc.ents:
            if ent.label_ == "PERSON":
                people.add(ent.text.strip())

        logger.debug("people_extracted", count=len(people), people=list(people))

    except Exception as e:
        logger.error("people_extraction_failed", error=str(e))

    return people


def extract_organizations(text: str) -> Set[str]:
    """Extract organizations using spaCy NER and known patterns.

    Args:
        text: Input text

    Returns:
        Set of organization names
    """
    organizations = set()

    text_lower = text.lower()

    # Check for known organizations
    for org in KNOWN_ORGANIZATIONS:
        pattern = r'\b' + re.escape(org) + r'\b'
        if re.search(pattern, text_lower):
            organizations.add(org.upper() if len(org) <= 5 else org.title())

    # Use spaCy NER for additional organizations
    try:
        nlp = get_nlp()
        doc = nlp(text)

        for ent in doc.ents:
            if ent.label_ in ["ORG", "FAC", "GPE"]:  # Organization, Facility, Geo-political entity
                org_name = ent.text.strip().lower()
                # Filter out countries (handled separately)
                if org_name not in KNOWN_COUNTRIES:
                    organizations.add(ent.text.strip())

        logger.debug("organizations_extracted", count=len(organizations), orgs=list(organizations))

    except Exception as e:
        logger.error("organizations_extraction_failed", error=str(e))

    return organizations


def extract_countries(text: str) -> Set[str]:
    """Extract country names.

    Args:
        text: Input text

    Returns:
        Set of country names
    """
    countries = set()

    text_lower = text.lower()

    # Check for known countries
    for country in KNOWN_COUNTRIES:
        pattern = r'\b' + re.escape(country) + r'\b'
        if re.search(pattern, text_lower):
            countries.add(country.upper() if len(country) <= 3 else country.title())

    # Use spaCy NER for additional countries
    try:
        nlp = get_nlp()
        doc = nlp(text)

        for ent in doc.ents:
            if ent.label_ == "GPE":  # Geo-political entity
                country_name = ent.text.strip().lower()
                if country_name in KNOWN_COUNTRIES or len(ent.text) > 3:
                    countries.add(ent.text.strip())

        logger.debug("countries_extracted", count=len(countries), countries=list(countries))

    except Exception as e:
        logger.error("countries_extraction_failed", error=str(e))

    return countries


def extract_misc_entities(text: str) -> Set[str]:
    """Extract miscellaneous entities (events, dates, etc.).

    Args:
        text: Input text

    Returns:
        Set of misc entities
    """
    misc = set()

    try:
        nlp = get_nlp()
        doc = nlp(text)

        for ent in doc.ents:
            if ent.label_ in ["EVENT", "PRODUCT", "WORK_OF_ART"]:
                misc.add(ent.text.strip())

        # Extract specific events
        event_patterns = [
            r'\b(super bowl)\b',
            r'\b(world cup)\b',
            r'\b(olympics)\b',
            r'\b(election)\b',
            r'\b(q[1-4])\b',
            r'\b(quarter [1-4])\b',
        ]

        text_lower = text.lower()
        for pattern in event_patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                misc.add(match.title())

        logger.debug("misc_entities_extracted", count=len(misc), entities=list(misc))

    except Exception as e:
        logger.error("misc_extraction_failed", error=str(e))

    return misc


def extract_entities(text: str) -> Dict[str, List[str]]:
    """Extract all entities from text.

    Args:
        text: Input text (title + description)

    Returns:
        Dictionary of entity lists by type
    """
    logger.debug("extract_entities_start", text_length=len(text))

    entities = {
        "tickers": list(extract_tickers(text)),
        "people": list(extract_people(text)),
        "organizations": list(extract_organizations(text)),
        "countries": list(extract_countries(text)),
        "misc": list(extract_misc_entities(text)),
    }

    total_entities = sum(len(v) for v in entities.values())

    logger.info(
        "extract_entities_complete",
        total=total_entities,
        breakdown={k: len(v) for k, v in entities.items()},
    )

    return entities
