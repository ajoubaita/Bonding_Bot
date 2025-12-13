"""Main similarity calculator that aggregates all features."""

from typing import Dict, Any
import math
import structlog

from src.models import Market
from src.config import settings
from src.similarity.features import (
    calculate_text_similarity,
    calculate_entity_similarity,
    calculate_time_alignment,
    calculate_outcome_similarity,
    calculate_resolution_similarity,
)

logger = structlog.get_logger()


def check_hard_constraints(
    market_k: Market,
    market_p: Market,
    features: Dict[str, Any]
) -> bool:
    """Check if pair violates any hard constraints.

    Args:
        market_k: Kalshi market
        market_p: Polymarket market
        features: Calculated feature scores

    Returns:
        True if hard constraints violated (should reject), False otherwise
    """
    # Extract feature scores
    score_text = features.get("text", {}).get("score_text", 0.0)
    score_entity = features.get("entity", {}).get("score_entity", 0.0)
    score_outcome = features.get("outcome", {}).get("score_outcome", 0.0)
    delta_days = features.get("time", {}).get("delta_days", 999)

    # Check exact ticker/person match for entity exception
    bonus_ticker = features.get("entity", {}).get("bonus_ticker", 0.0)
    bonus_person = features.get("entity", {}).get("bonus_person", 0.0)
    has_exact_match = (bonus_ticker >= 1.0) or (bonus_person >= 1.0)

    # Hard constraint checks
    violations = []

    # 0. Event type mismatch (CRITICAL: don't match sports with politics)
    # Use event_type instead of category since category is not populated by APIs
    if market_k.event_type and market_p.event_type:
        if market_k.event_type != market_p.event_type:
            violations.append(f"event_type_mismatch: {market_k.event_type} != {market_p.event_type}")

    # 1. Text similarity too low
    if score_text < settings.hard_constraint_min_text_score:
        violations.append(f"text_score={score_text:.3f} < {settings.hard_constraint_min_text_score}")

    # 2. Entity disjoint (unless exact match)
    if score_entity < settings.hard_constraint_min_entity_score and not has_exact_match:
        violations.append(f"entity_score={score_entity:.3f} < {settings.hard_constraint_min_entity_score} (no exact match)")

    # 3. Time skew too large
    if delta_days > settings.hard_constraint_max_time_delta_days:
        violations.append(f"delta_days={delta_days} > {settings.hard_constraint_max_time_delta_days}")

    # 4. Outcome incompatibility
    if score_outcome == 0.0:
        violations.append("outcome_incompatible")
    
    # 5. Direction mismatch (e.g., "over 45.5" vs "under 45.5")
    from src.normalization.text_cleaner import detect_direction_mismatch
    title_k = market_k.clean_title or market_k.raw_title or ""
    title_p = market_p.clean_title or market_p.raw_title or ""
    if detect_direction_mismatch(title_k, title_p):
        violations.append("direction_mismatch: opposite directions detected (e.g., over vs under)")

    # 6. Entity name mismatch (CRITICAL for sports/politics/corporate)
    # If both markets have people entities, check if they share at least one person
    entities_k = market_k.entities or {}
    entities_p = market_p.entities or {}
    people_k = set(entities_k.get("people", []))
    people_p = set(entities_p.get("people", []))

    # If both have people (>= 1) but share NONE, likely different events
    if len(people_k) >= 1 and len(people_p) >= 1:
        shared_people = people_k.intersection(people_p)
        if len(shared_people) == 0 and not has_exact_match:
            violations.append(f"entity_name_mismatch: no shared people - K:{list(people_k)[:3]} vs P:{list(people_p)[:3]}")

    # 7. Sports-specific: Player prop vs team outcome mismatch
    # If event_type is sports, check for statistical markers
    if market_k.event_type == "sports" and market_p.event_type == "sports":
        # Statistical markers indicate player props (e.g., "200+", "yards", "touchdowns")
        stat_markers = ["+", "yards", "points", "rushing", "passing", "receiving",
                       "rebounds", "assists", "goals", "saves", "touchdowns"]

        has_stat_k = any(marker in title_k for marker in stat_markers)
        has_stat_p = any(marker in title_p for marker in stat_markers)

        # If one is a player prop and the other is a team outcome, reject
        # (e.g., "Mahomes 200+ yards" vs "Chiefs make playoff")
        if has_stat_k != has_stat_p:
            violations.append(f"sports_market_type_mismatch: stat_prop_K={has_stat_k} vs stat_prop_P={has_stat_p}")

        # Also check if both have statistical markers but for different magnitudes
        # (e.g., "200+" vs "300+" suggests different events/games)
        if has_stat_k and has_stat_p:
            # Extract numbers from titles
            import re
            numbers_k = set(re.findall(r'\d+', title_k))
            numbers_p = set(re.findall(r'\d+', title_p))

            # If they have numbers but share NONE, likely different stat lines/games
            if numbers_k and numbers_p and not numbers_k.intersection(numbers_p):
                # Allow if text similarity is very high (might be same event, different notation)
                if score_text < 0.70:
                    violations.append(f"sports_stat_mismatch: different numbers - K:{numbers_k} vs P:{numbers_p}")

    # 8. CRITICAL: Sport type mismatch (prevent NFL ↔ NHL ↔ NBA ↔ MLB bonding)
    # Detect sport types dynamically from titles
    from src.normalization.event_classifier import classify_sport_type
    if market_k.event_type == "sports" and market_p.event_type == "sports":
        sport_type_k = classify_sport_type(title_k)
        sport_type_p = classify_sport_type(title_p)

        # If both have detected sport types, they MUST match
        if sport_type_k and sport_type_p and sport_type_k != sport_type_p:
            violations.append(f"sport_type_mismatch: {sport_type_k} != {sport_type_p}")

    # 9. CRITICAL: Parlay market blocking (multi-game markets cannot bond with single-game)
    from src.normalization.event_classifier import detect_parlay_market
    is_parlay_k = detect_parlay_market(title_k)
    is_parlay_p = detect_parlay_market(title_p)

    # If one is parlay and other is not, reject
    if is_parlay_k != is_parlay_p:
        violations.append(f"parlay_mismatch: K_parlay={is_parlay_k} vs P_parlay={is_parlay_p}")

    # If both are parlays, require very high text similarity (should be exact same combo)
    if is_parlay_k and is_parlay_p and score_text < 0.85:
        violations.append(f"parlay_text_too_low: both parlays but text_score={score_text:.3f} < 0.85")

    if violations:
        logger.info(
            "hard_constraints_violated",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            violations=violations,
        )
        return True

    return False


def calculate_weighted_score(features: Dict[str, Any]) -> float:
    """Calculate weighted similarity score.

    Args:
        features: Dictionary of feature scores

    Returns:
        Weighted score [0, 1]
    """
    # Extract final scores from each feature
    score_text = features.get("text", {}).get("score_text", 0.0)
    score_entity = features.get("entity", {}).get("score_entity_final", 0.0)
    score_time = features.get("time", {}).get("score_time_final", 0.0)
    score_outcome = features.get("outcome", {}).get("score_outcome", 0.0)
    score_resolution = features.get("resolution", {}).get("score_resolution", 0.0)

    # Weighted sum
    score = (
        settings.weight_text * score_text +
        settings.weight_entity * score_entity +
        settings.weight_time * score_time +
        settings.weight_outcome * score_outcome +
        settings.weight_resolution * score_resolution
    )

    return score


def calculate_match_probability(features: Dict[str, Any]) -> float:
    """Calculate match probability using logistic regression.

    Args:
        features: Dictionary of feature scores

    Returns:
        Match probability [0, 1]
    """
    # Extract scores
    score_text = features.get("text", {}).get("score_text", 0.0)
    score_entity = features.get("entity", {}).get("score_entity_final", 0.0)
    score_time = features.get("time", {}).get("score_time_final", 0.0)
    score_outcome = features.get("outcome", {}).get("score_outcome", 0.0)
    score_resolution = features.get("resolution", {}).get("score_resolution", 0.0)

    # Logistic regression parameters (calibrated from labeled dataset)
    # TODO: Train these from actual labeled data
    # These are example parameters
    beta = [
        -5.0,  # intercept
        4.2,   # text
        3.1,   # entity
        2.5,   # time
        3.8,   # outcome
        1.2,   # resolution
    ]

    # Calculate logit
    z = (
        beta[0] +
        beta[1] * score_text +
        beta[2] * score_entity +
        beta[3] * score_time +
        beta[4] * score_outcome +
        beta[5] * score_resolution
    )

    # Sigmoid function
    p_match = 1.0 / (1.0 + math.exp(-z))

    return p_match


def calculate_similarity(market_k: Market, market_p: Market) -> Dict[str, Any]:
    """Calculate full similarity between two markets.

    Args:
        market_k: Kalshi market
        market_p: Polymarket market

    Returns:
        Dictionary with:
        {
            "similarity_score": float,     # Weighted score [0, 1]
            "p_match": float,              # Match probability [0, 1]
            "hard_constraints_violated": bool,
            "features": {
                "text": {...},
                "entity": {...},
                "time": {...},
                "outcome": {...},
                "resolution": {...},
            }
        }
    """
    logger.info(
        "calculate_similarity_start",
        kalshi_id=market_k.id,
        poly_id=market_p.id,
    )

    # Calculate all features
    features = {
        "text": calculate_text_similarity(market_k, market_p),
        "entity": calculate_entity_similarity(market_k, market_p),
        "time": calculate_time_alignment(market_k, market_p),
        "outcome": calculate_outcome_similarity(market_k, market_p),
        "resolution": calculate_resolution_similarity(market_k, market_p),
    }

    # Check hard constraints
    hard_constraints_violated = check_hard_constraints(market_k, market_p, features)

    # If hard constraints violated, return reject score
    if hard_constraints_violated:
        return {
            "similarity_score": 0.0,
            "p_match": 0.0,
            "hard_constraints_violated": True,
            "features": features,
        }

    # Calculate weighted score
    similarity_score = calculate_weighted_score(features)

    # Calculate match probability
    p_match = calculate_match_probability(features)

    logger.info(
        "calculate_similarity_complete",
        kalshi_id=market_k.id,
        poly_id=market_p.id,
        similarity_score=similarity_score,
        p_match=p_match,
    )

    return {
        "similarity_score": similarity_score,
        "p_match": p_match,
        "hard_constraints_violated": False,
        "features": features,
    }
