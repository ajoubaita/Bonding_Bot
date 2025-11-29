"""Complete normalization pipeline for market data."""

from typing import Dict, Any, Optional
from datetime import datetime
import structlog

from src.normalization.text_cleaner import clean_title, clean_description
from src.normalization.entity_extractor import extract_entities
from src.normalization.embedding_generator import generate_market_embedding
from src.normalization.event_classifier import classify_event_type, determine_geo_scope

logger = structlog.get_logger()


def normalize_market(raw_market: Dict[str, Any], platform: str) -> Dict[str, Any]:
    """Normalize raw market data to internal schema.

    Args:
        raw_market: Raw market data (from API client)
        platform: Platform name ("kalshi" or "polymarket")

    Returns:
        Fully normalized market data ready for database
    """
    logger.info(
        "normalize_market_start",
        platform=platform,
        market_id=raw_market.get("id"),
    )

    try:
        # Step 1: Extract raw fields
        market_id = raw_market.get("id")
        raw_title = raw_market.get("title", "")
        raw_description = raw_market.get("description", "")
        category = raw_market.get("category", "unknown")
        resolution_date = raw_market.get("resolution_date")
        resolution_source = raw_market.get("resolution_source", "Unknown")
        outcome_type = raw_market.get("outcome_type", "yes_no")
        outcomes = raw_market.get("outcomes", [])
        metadata = raw_market.get("metadata", {})

        # Step 2: Clean text
        clean_title_text = clean_title(raw_title)
        clean_description_text = clean_description(raw_description)

        logger.debug(
            "normalize_market_text_cleaned",
            market_id=market_id,
            title_length=len(clean_title_text),
            desc_length=len(clean_description_text),
        )

        # Step 3: Extract entities
        combined_text = f"{raw_title} {raw_description}"
        entities = extract_entities(combined_text)

        logger.debug(
            "normalize_market_entities_extracted",
            market_id=market_id,
            total_entities=sum(len(v) for v in entities.values()),
        )

        # Step 4: Generate embedding
        text_embedding = generate_market_embedding(clean_title_text, clean_description_text)

        if text_embedding:
            logger.debug(
                "normalize_market_embedding_generated",
                market_id=market_id,
                embedding_dims=len(text_embedding),
            )
        else:
            logger.warning(
                "normalize_market_embedding_failed",
                market_id=market_id,
            )

        # Step 5: Classify event type
        event_type = classify_event_type(category, entities, clean_title_text)

        logger.debug(
            "normalize_market_event_classified",
            market_id=market_id,
            event_type=event_type,
        )

        # Step 6: Determine geo scope
        geo_scope = determine_geo_scope(entities, clean_title_text)

        # Step 7: Build normalized schema
        normalized = {
            "id": market_id,
            "platform": platform,
            "condition_id": metadata.get("clob_token_ids", [None])[0] if platform == "polymarket" else None,
            "status": "active",  # Will be updated based on market state
            "raw_title": raw_title,
            "raw_description": raw_description,
            "clean_title": clean_title_text,
            "clean_description": clean_description_text,
            "category": category,
            "event_type": event_type,
            "entities": entities,
            "geo_scope": geo_scope,
            "time_window": {
                "resolution_date": resolution_date,
                "granularity": infer_granularity(clean_title_text, resolution_date),
            },
            "resolution_source": resolution_source,
            "outcome_schema": {
                "type": outcome_type,
                "polarity": infer_polarity(clean_title_text),
                "outcomes": outcomes,
            },
            "text_embedding": text_embedding,
            "metadata": {
                **metadata,
                "ingestion_version": "v1.0.0",
                "normalized_at": datetime.utcnow().isoformat(),
            },
        }

        logger.info(
            "normalize_market_complete",
            platform=platform,
            market_id=market_id,
            event_type=event_type,
            geo_scope=geo_scope,
        )

        return normalized

    except Exception as e:
        logger.error(
            "normalize_market_failed",
            platform=platform,
            market_id=raw_market.get("id"),
            error=str(e),
        )
        raise


def infer_granularity(title: str, resolution_date: Optional[str]) -> str:
    """Infer time granularity from title and resolution date.

    Args:
        title: Market title
        resolution_date: Resolution date string

    Returns:
        Granularity ("day", "week", "month", "quarter", "year")
    """
    title_lower = title.lower()

    # Check for explicit granularity indicators
    if any(word in title_lower for word in ["daily", "today", "by end of day", "eod"]):
        return "day"

    if any(word in title_lower for word in ["week", "weekly"]):
        return "week"

    if any(word in title_lower for word in ["month", "monthly"]):
        return "month"

    if any(word in title_lower for word in ["quarter", "q1", "q2", "q3", "q4", "quarterly"]):
        return "quarter"

    if any(word in title_lower for word in ["year", "annual", "yearly", "eoy", "end of year"]):
        return "year"

    # Default to week
    return "week"


def infer_polarity(title: str) -> str:
    """Infer polarity for yes/no markets.

    Args:
        title: Market title

    Returns:
        Polarity ("positive" or "negative")
    """
    title_lower = title.lower()

    # Check for negative indicators
    negative_words = ["not", "won't", "will not", "fails to", "doesn't", "does not", "reject"]

    for word in negative_words:
        if word in title_lower:
            return "negative"

    # Default to positive
    return "positive"
