"""Text similarity feature calculator using embeddings."""

import numpy as np
from typing import Optional
import structlog

from src.models import Market

logger = structlog.get_logger()


def cosine_similarity(vec1: np.ndarray, vec2: np.ndarray) -> float:
    """Calculate cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity score [0, 1]
    """
    dot_product = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)

    if norm1 == 0 or norm2 == 0:
        return 0.0

    # Cosine similarity is in [-1, 1], normalize to [0, 1]
    similarity = dot_product / (norm1 * norm2)
    return (similarity + 1) / 2


def calculate_text_similarity(market_k: Market, market_p: Market) -> dict:
    """Calculate text similarity features between two markets.

    Args:
        market_k: Kalshi market
        market_p: Polymarket market

    Returns:
        Dictionary with text similarity scores:
        {
            "score_text": float,  # Combined score [0, 1]
            "score_title": float,  # Title-only score [0, 1]
            "score_desc": float,   # Description-only score [0, 1]
        }
    """
    result = {
        "score_text": 0.0,
        "score_title": 0.0,
        "score_desc": 0.0,
    }

    try:
        # Check if embeddings exist
        if market_k.text_embedding is None or market_p.text_embedding is None:
            logger.warning(
                "text_similarity_missing_embedding",
                kalshi_id=market_k.id,
                poly_id=market_p.id,
            )
            return result

        # Convert embeddings to numpy arrays
        # Note: text_embedding is stored as vector type, may need conversion
        if isinstance(market_k.text_embedding, str):
            emb_k = np.array([float(x) for x in market_k.text_embedding.strip('[]').split(',')])
        else:
            emb_k = np.array(market_k.text_embedding)

        if isinstance(market_p.text_embedding, str):
            emb_p = np.array([float(x) for x in market_p.text_embedding.strip('[]').split(',')])
        else:
            emb_p = np.array(market_p.text_embedding)

        # Calculate combined similarity
        score_combined = cosine_similarity(emb_k, emb_p)

        # TODO: Calculate separate title and description embeddings
        # For now, use combined score for all
        score_title = score_combined
        score_desc = score_combined

        # Weighted combination: title weighted more heavily
        score_text = 0.7 * score_title + 0.3 * score_desc

        result = {
            "score_text": float(score_text),
            "score_title": float(score_title),
            "score_desc": float(score_desc),
        }

        logger.debug(
            "text_similarity_calculated",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            score=score_text,
        )

    except Exception as e:
        logger.error(
            "text_similarity_error",
            kalshi_id=market_k.id,
            poly_id=market_p.id,
            error=str(e),
        )

    return result
