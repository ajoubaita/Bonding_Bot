"""Tier assignment logic for bonded pairs."""

from typing import Dict, Any, Optional
import structlog

from src.config import settings

logger = structlog.get_logger()


def assign_tier(
    p_match: float,
    features: Dict[str, Any],
    hard_constraints_violated: bool,
    market_k_id: Optional[str] = None,
    market_p_id: Optional[str] = None,
    similarity_result: Optional[Dict[str, Any]] = None,
) -> int:
    """Assign tier based on similarity scores and requirements.

    Args:
        p_match: Match probability [0, 1]
        features: Feature breakdown dictionary
        hard_constraints_violated: Whether hard constraints were violated
        market_k_id: Kalshi market ID (for logging)
        market_p_id: Polymarket market ID (for logging)
        similarity_result: Full similarity result (for logging)

    Returns:
        Tier (1, 2, or 3)
    """
    # Immediate reject if hard constraints violated
    if hard_constraints_violated:
        logger.info("tier_assignment", tier=3, reason="hard_constraints_violated")
        
        # Log rejection for analysis
        if market_k_id and market_p_id and similarity_result:
            from src.utils.bonding_logger import log_bonding_candidate
            log_bonding_candidate(
                market_k_id=market_k_id,
                market_p_id=market_p_id,
                similarity_result=similarity_result,
                was_accepted=False,
                tier=3,
                rejection_reason="hard_constraints_violated",
            )
        
        return 3

    # Extract individual feature scores
    score_text = features.get("text", {}).get("score_text", 0.0)
    score_entity_final = features.get("entity", {}).get("score_entity_final", 0.0)
    score_time_final = features.get("time", {}).get("score_time_final", 0.0)
    score_outcome = features.get("outcome", {}).get("score_outcome", 0.0)
    score_resolution = features.get("resolution", {}).get("score_resolution", 0.0)

    # Tier 1: Auto Bond (highest confidence)
    tier1_criteria = [
        p_match >= settings.tier1_p_match_threshold,
        score_text >= settings.tier1_min_text_score,
        score_outcome >= settings.tier1_min_outcome_score,
        score_time_final >= settings.tier1_min_time_score,
        score_resolution >= settings.tier1_min_resolution_score,
    ]

    if all(tier1_criteria):
        logger.info(
            "tier_assignment",
            tier=1,
            p_match=p_match,
            scores={
                "text": score_text,
                "entity": score_entity_final,
                "time": score_time_final,
                "outcome": score_outcome,
                "resolution": score_resolution,
            },
        )
        
        # Log acceptance for analysis
        if market_k_id and market_p_id and similarity_result:
            from src.utils.bonding_logger import log_bonding_candidate
            log_bonding_candidate(
                market_k_id=market_k_id,
                market_p_id=market_p_id,
                similarity_result=similarity_result,
                was_accepted=True,
                tier=1,
            )
        
        return 1

    # Tier 2: Cautious Bond (moderate confidence)
    tier2_criteria = [
        p_match >= settings.tier2_p_match_threshold,
        score_text >= settings.tier2_min_text_score,
        score_outcome >= settings.tier2_min_outcome_score,
        score_time_final >= settings.tier2_min_time_score,
    ]

    if all(tier2_criteria):
        logger.info(
            "tier_assignment",
            tier=2,
            p_match=p_match,
            scores={
                "text": score_text,
                "entity": score_entity_final,
                "time": score_time_final,
                "outcome": score_outcome,
                "resolution": score_resolution,
            },
        )
        
        # Log acceptance for analysis
        if market_k_id and market_p_id and similarity_result:
            from src.utils.bonding_logger import log_bonding_candidate
            log_bonding_candidate(
                market_k_id=market_k_id,
                market_p_id=market_p_id,
                similarity_result=similarity_result,
                was_accepted=True,
                tier=2,
            )
        
        return 2

    # Tier 3: Reject (low confidence)
    logger.info(
        "tier_assignment",
        tier=3,
        p_match=p_match,
        reason="insufficient_scores",
        scores={
            "text": score_text,
            "entity": score_entity_final,
            "time": score_time_final,
            "outcome": score_outcome,
            "resolution": score_resolution,
        },
    )
    
    # Log rejection for analysis
    if market_k_id and market_p_id and similarity_result:
        from src.utils.bonding_logger import log_bonding_candidate
        log_bonding_candidate(
            market_k_id=market_k_id,
            market_p_id=market_p_id,
            similarity_result=similarity_result,
            was_accepted=False,
            tier=3,
            rejection_reason="insufficient_scores",
        )
    
    return 3


def get_tier_description(tier: int) -> Dict[str, Any]:
    """Get description and trading parameters for a tier.

    Args:
        tier: Tier number (1, 2, or 3)

    Returns:
        Dictionary with tier information
    """
    tier_info = {
        1: {
            "label": "Auto Bond",
            "description": "High confidence - safe for full arbitrage",
            "max_notional_default": 10000,
            "max_position_pct": 0.10,
            "review_required": False,
        },
        2: {
            "label": "Cautious Bond",
            "description": "Moderate confidence - reduced size, optional review",
            "max_notional_default": 2000,
            "max_position_pct": 0.05,
            "review_required": True,
        },
        3: {
            "label": "Reject",
            "description": "Low confidence - no trading",
            "max_notional_default": 0,
            "max_position_pct": 0.0,
            "review_required": False,
        },
    }

    return tier_info.get(tier, tier_info[3])
