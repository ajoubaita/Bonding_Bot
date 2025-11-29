"""Outcome structure similarity feature calculator."""

from typing import Optional, List, Dict, Any, Tuple
import structlog

from src.models import Market

logger = structlog.get_logger()


def overlaps(bracket1: Tuple[Optional[float], Optional[float]],
             bracket2: Tuple[Optional[float], Optional[float]]) -> bool:
    """Check if two brackets overlap.

    Args:
        bracket1: (min, max) tuple
        bracket2: (min, max) tuple

    Returns:
        True if brackets overlap
    """
    min1, max1 = bracket1
    min2, max2 = bracket2

    # Handle unbounded brackets (None values)
    if min1 is None:
        min1 = float('-inf')
    if max1 is None:
        max1 = float('inf')
    if min2 is None:
        min2 = float('-inf')
    if max2 is None:
        max2 = float('inf')

    # Check overlap
    return max1 > min2 and max2 > min1


def contains(bracket1: Tuple[Optional[float], Optional[float]],
             bracket2: Tuple[Optional[float], Optional[float]]) -> bool:
    """Check if bracket1 contains bracket2.

    Args:
        bracket1: (min, max) tuple
        bracket2: (min, max) tuple

    Returns:
        True if bracket1 contains bracket2
    """
    min1, max1 = bracket1
    min2, max2 = bracket2

    # Handle unbounded brackets
    if min1 is None:
        min1 = float('-inf')
    if max1 is None:
        max1 = float('inf')
    if min2 is None:
        min2 = float('-inf')
    if max2 is None:
        max2 = float('inf')

    return min1 <= min2 and max1 >= max2


def detect_negation(title1: str, title2: str) -> bool:
    """Detect if titles have opposite polarity via negation.

    Args:
        title1: First title
        title2: Second title

    Returns:
        True if negation detected
    """
    if not title1 or not title2:
        return False

    title1_lower = title1.lower()
    title2_lower = title2.lower()

    # Common negation patterns
    negation_words = ["not", "won't", "wont", "will not", "fails to", "doesn't", "does not"]

    # Count negations in each title
    neg_count1 = sum(1 for word in negation_words if word in title1_lower)
    neg_count2 = sum(1 for word in negation_words if word in title2_lower)

    # Opposite polarity if one has negation and other doesn't
    return (neg_count1 > 0) != (neg_count2 > 0)


def calculate_yes_no_similarity(schema_k: Dict[str, Any],
                                 schema_p: Dict[str, Any],
                                 title_k: str,
                                 title_p: str) -> float:
    """Calculate similarity for yes/no markets.

    Args:
        schema_k: Kalshi outcome schema
        schema_p: Polymarket outcome schema
        title_k: Kalshi market title
        title_p: Polymarket market title

    Returns:
        Similarity score [0, 1]
    """
    polarity_k = schema_k.get("polarity", "positive")
    polarity_p = schema_p.get("polarity", "positive")

    same_polarity = (polarity_k == polarity_p)
    is_complement = detect_negation(title_k, title_p)

    # Both have same polarity and no negation = match
    if same_polarity and not is_complement:
        return 1.0

    # Different polarity but clear negation = inverted match (still valid)
    if not same_polarity and is_complement:
        return 1.0

    # Polarity mismatch = reject
    return 0.0


def calculate_bracket_similarity(schema_k: Dict[str, Any],
                                  schema_p: Dict[str, Any]) -> float:
    """Calculate similarity for bracket markets.

    Args:
        schema_k: Kalshi outcome schema
        schema_p: Polymarket outcome schema

    Returns:
        Similarity score [0, 1]
    """
    # Check unit match
    unit_k = schema_k.get("unit")
    unit_p = schema_p.get("unit")

    if unit_k != unit_p:
        logger.warning(
            "bracket_unit_mismatch",
            unit_k=unit_k,
            unit_p=unit_p,
        )
        return 0.0  # Reject if units don't match

    # Extract brackets
    brackets_k = schema_k.get("brackets", [])
    brackets_p = schema_p.get("brackets", [])

    if not brackets_k or not brackets_p:
        return 0.0

    # Convert to (min, max) tuples
    k_ranges = [(b.get("min"), b.get("max")) for b in brackets_k]
    p_ranges = [(b.get("min"), b.get("max")) for b in brackets_p]

    # Check for exact match
    if k_ranges == p_ranges:
        return 1.0

    # Calculate partial overlap
    overlap_count = 0
    for kb in k_ranges:
        for pb in p_ranges:
            if overlaps(kb, pb):
                overlap_count += 1
                break  # Count each K bracket only once

    total_brackets = max(len(k_ranges), len(p_ranges))
    overlap_ratio = overlap_count / total_brackets if total_brackets > 0 else 0.0

    return overlap_ratio


def calculate_scalar_similarity(schema_k: Dict[str, Any],
                                 schema_p: Dict[str, Any]) -> float:
    """Calculate similarity for scalar range markets.

    Args:
        schema_k: Kalshi outcome schema
        schema_p: Polymarket outcome schema

    Returns:
        Similarity score [0, 1]
    """
    # Check unit match
    unit_k = schema_k.get("unit")
    unit_p = schema_p.get("unit")

    if unit_k != unit_p:
        logger.warning(
            "scalar_unit_mismatch",
            unit_k=unit_k,
            unit_p=unit_p,
        )
        return 0.0  # Reject if units don't match

    # Extract ranges
    min_k = schema_k.get("min")
    max_k = schema_k.get("max")
    min_p = schema_p.get("min")
    max_p = schema_p.get("max")

    k_range = (min_k, max_k)
    p_range = (min_p, max_p)

    # Exact match
    if k_range == p_range:
        return 1.0

    # One contains the other (cautious bond)
    if contains(k_range, p_range) or contains(p_range, k_range):
        return 0.8

    # No match
    return 0.0


def calculate_outcome_similarity(market_k: Market, market_p: Market) -> dict:
    """Calculate outcome structure similarity between two markets.

    Args:
        market_k: Kalshi market
        market_p: Polymarket market

    Returns:
        Dictionary with outcome similarity score:
        {
            "score_outcome": float,  # Outcome similarity [0, 1]
        }
    """
    result = {
        "score_outcome": 0.0,
    }

    try:
        schema_k = market_k.outcome_schema
        schema_p = market_p.outcome_schema

        if not schema_k or not schema_p:
            logger.warning(
                "outcome_similarity_missing_schema",
                kalshi_id=market_k.id,
                poly_id=market_p.id,
            )
            return result

        type_k = schema_k.get("type")
        type_p = schema_p.get("type")

        # Yes/No markets
        if type_k == "yes_no" and type_p == "yes_no":
            score = calculate_yes_no_similarity(
                schema_k,
                schema_p,
                market_k.clean_title or market_k.raw_title or "",
                market_p.clean_title or market_p.raw_title or "",
            )
            result["score_outcome"] = score

        # Discrete bracket markets
        elif type_k == "discrete_brackets" and type_p == "discrete_brackets":
            score = calculate_bracket_similarity(schema_k, schema_p)
            result["score_outcome"] = score

        # Scalar range markets
        elif type_k == "scalar_range" and type_p == "scalar_range":
            score = calculate_scalar_similarity(schema_k, schema_p)
            result["score_outcome"] = score

        # Cross-type: yes/no vs discrete brackets (binary collapse)
        elif (type_k == "yes_no" and type_p == "discrete_brackets") or \
             (type_k == "discrete_brackets" and type_p == "yes_no"):
            # Check if discrete has only 2 brackets
            brackets = schema_k.get("brackets", []) if type_k == "discrete_brackets" else schema_p.get("brackets", [])
            if len(brackets) == 2:
                result["score_outcome"] = 0.9  # Tier 2 only
            else:
                result["score_outcome"] = 0.0  # Reject

        # Incompatible types
        else:
            logger.warning(
                "outcome_similarity_incompatible",
                kalshi_id=market_k.id,
                poly_id=market_p.id,
                type_k=type_k,
                type_p=type_p,
            )
            result["score_outcome"] = 0.0

        logger.debug(
            "outcome_similarity_calculated",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            type_k=type_k,
            type_p=type_p,
            score=result["score_outcome"],
        )

    except Exception as e:
        logger.error(
            "outcome_similarity_error",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            error=str(e),
        )

    return result
