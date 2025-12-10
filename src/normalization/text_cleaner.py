"""Text cleaning and normalization utilities."""

import re
from typing import Optional, Set
import structlog
from difflib import SequenceMatcher

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


def extract_key_terms(text: str, min_length: int = 3) -> Set[str]:
    """Extract key terms from text for fuzzy matching.
    
    Removes common stopwords and extracts meaningful terms.
    
    Args:
        text: Input text
        min_length: Minimum term length
        
    Returns:
        Set of key terms
    """
    if not text:
        return set()
    
    # Common stopwords to remove
    stopwords = {
        "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "should", "could", "may", "might", "must", "can", "this",
        "that", "these", "those", "what", "which", "who", "when", "where",
        "why", "how", "will", "be", "by", "end", "of", "on", "in", "at",
    }
    
    # Tokenize and clean
    words = re.findall(r'\b\w+\b', text.lower())
    terms = {w for w in words if len(w) >= min_length and w not in stopwords}
    
    return terms


def fuzzy_match_ratio(text1: str, text2: str) -> float:
    """Calculate fuzzy match ratio between two texts.
    
    Uses SequenceMatcher for similarity scoring.
    
    Args:
        text1: First text
        text2: Second text
        
    Returns:
        Similarity ratio [0, 1]
    """
    if not text1 or not text2:
        return 0.0
    
    return SequenceMatcher(None, text1.lower(), text2.lower()).ratio()


def detect_direction_mismatch(title1: str, title2: str) -> bool:
    """Detect if two titles have opposite directions (e.g., "over" vs "under").
    
    Args:
        title1: First title
        title2: Second title
        
    Returns:
        True if directions are opposite
    """
    if not title1 or not title2:
        return False
    
    title1_lower = title1.lower()
    title2_lower = title2.lower()
    
    # Directional pairs
    direction_pairs = [
        ("over", "under"), ("above", "below"), ("higher", "lower"),
        ("greater", "less"), ("more", "less"), ("exceed", "below"),
        ("wins", "loses"), ("win", "lose"), ("beat", "lose to"),
        ("yes", "no"), ("will", "won't"), ("will not", "will"),
    ]
    
    for dir1, dir2 in direction_pairs:
        has_dir1_1 = dir1 in title1_lower
        has_dir2_1 = dir2 in title1_lower
        has_dir1_2 = dir1 in title2_lower
        has_dir2_2 = dir2 in title2_lower
        
        # Check for opposite directions
        if (has_dir1_1 and has_dir2_2) or (has_dir2_1 and has_dir1_2):
            return True
    
    return False
