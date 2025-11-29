"""Text cleaning and normalization utilities."""

import re
from typing import Optional
import structlog

logger = structlog.get_logger()


# Common abbreviation expansions
ABBREVIATIONS = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "usd": "dollar",
    "q1": "quarter 1",
    "q2": "quarter 2",
    "q3": "quarter 3",
    "q4": "quarter 4",
    "gdp": "gross domestic product",
    "cpi": "consumer price index",
    "fomc": "federal open market committee",
    "fed": "federal reserve",
    "bls": "bureau of labor statistics",
    "djia": "dow jones industrial average",
    "s&p": "standard and poors",
    "nyse": "new york stock exchange",
    "nasdaq": "nasdaq",
}


def strip_html(text: str) -> str:
    """Remove HTML tags from text.

    Args:
        text: Input text

    Returns:
        Text without HTML tags
    """
    if not text:
        return ""

    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', '', text)

    return clean


def normalize_whitespace(text: str) -> str:
    """Normalize whitespace in text.

    Args:
        text: Input text

    Returns:
        Text with normalized whitespace
    """
    if not text:
        return ""

    # Replace multiple spaces with single space
    clean = re.sub(r'\s+', ' ', text)

    # Strip leading/trailing whitespace
    clean = clean.strip()

    return clean


def remove_platform_prefixes(text: str) -> str:
    """Remove platform-specific prefixes from text.

    Args:
        text: Input text

    Returns:
        Text without platform prefixes
    """
    if not text:
        return ""

    # Common prefixes to remove
    prefixes = [
        r'^kalshi:\s*',
        r'^polymarket:\s*',
        r'^will\s+',
        r'^does\s+',
        r'^is\s+',
        r'^what\s+',
        r'^who\s+',
        r'^when\s+',
    ]

    clean = text
    for prefix in prefixes:
        clean = re.sub(prefix, '', clean, flags=re.IGNORECASE)

    return clean


def expand_abbreviations(text: str) -> str:
    """Expand common abbreviations.

    Args:
        text: Input text

    Returns:
        Text with expanded abbreviations
    """
    if not text:
        return ""

    clean = text.lower()

    # Replace abbreviations (word boundaries)
    for abbr, expansion in ABBREVIATIONS.items():
        pattern = r'\b' + re.escape(abbr) + r'\b'
        clean = re.sub(pattern, expansion, clean)

    return clean


def clean_text(text: Optional[str], expand_abbr: bool = True) -> str:
    """Clean and normalize text.

    Args:
        text: Input text
        expand_abbr: Whether to expand abbreviations

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    try:
        # Step 1: Strip HTML
        clean = strip_html(text)

        # Step 2: Normalize whitespace
        clean = normalize_whitespace(clean)

        # Step 3: Remove platform prefixes
        clean = remove_platform_prefixes(clean)

        # Step 4: Lowercase
        clean = clean.lower()

        # Step 5: Expand abbreviations (optional)
        if expand_abbr:
            clean = expand_abbreviations(clean)

        # Step 6: Final whitespace normalization
        clean = normalize_whitespace(clean)

        logger.debug(
            "text_cleaned",
            original_length=len(text),
            cleaned_length=len(clean),
        )

        return clean

    except Exception as e:
        logger.error(
            "text_cleaning_failed",
            error=str(e),
            text_preview=text[:100] if text else "",
        )
        return text or ""


def clean_title(title: str) -> str:
    """Clean market title.

    Args:
        title: Market title

    Returns:
        Cleaned title
    """
    return clean_text(title, expand_abbr=True)


def clean_description(description: str) -> str:
    """Clean market description.

    Args:
        description: Market description

    Returns:
        Cleaned description
    """
    return clean_text(description, expand_abbr=True)
