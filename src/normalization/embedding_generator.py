"""Text embedding generation using sentence-transformers."""

from typing import List, Optional
import numpy as np
import structlog

logger = structlog.get_logger()

# Lazy load sentence transformer model
_model = None


def get_model():
    """Get sentence transformer model (lazy loaded)."""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            from src.config import settings

            _model = SentenceTransformer(settings.embedding_model)
            logger.info("embedding_model_loaded", model=settings.embedding_model)
        except Exception as e:
            logger.error("embedding_model_load_failed", error=str(e))
            raise
    return _model


def generate_embedding(text: str) -> Optional[List[float]]:
    """Generate text embedding.

    Args:
        text: Input text

    Returns:
        384-dimensional embedding vector or None on failure
    """
    if not text:
        logger.warning("generate_embedding_empty_text")
        return None

    try:
        model = get_model()

        # Generate embedding
        embedding = model.encode(text, convert_to_numpy=True)

        # Convert to list for JSON serialization
        embedding_list = embedding.tolist()

        logger.debug(
            "embedding_generated",
            text_length=len(text),
            embedding_dims=len(embedding_list),
        )

        return embedding_list

    except Exception as e:
        logger.error(
            "embedding_generation_failed",
            error=str(e),
            text_preview=text[:100],
        )
        return None


def generate_market_embedding(title: str, description: str) -> Optional[List[float]]:
    """Generate combined embedding for market title and description.

    Args:
        title: Market title
        description: Market description

    Returns:
        384-dimensional embedding vector or None on failure
    """
    # Combine title and description with separator
    combined_text = f"{title} | {description}"

    logger.debug(
        "generate_market_embedding",
        title_length=len(title),
        description_length=len(description),
        combined_length=len(combined_text),
    )

    return generate_embedding(combined_text)


def batch_generate_embeddings(texts: List[str], batch_size: int = 32) -> List[Optional[List[float]]]:
    """Generate embeddings for multiple texts in batches.

    Args:
        texts: List of input texts
        batch_size: Batch size for processing

    Returns:
        List of embeddings (None for failures)
    """
    if not texts:
        return []

    logger.info("batch_generate_embeddings_start", count=len(texts), batch_size=batch_size)

    embeddings = []

    try:
        model = get_model()

        # Process in batches
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]

            # Filter out empty texts
            valid_texts = []
            valid_indices = []
            for j, text in enumerate(batch):
                if text:
                    valid_texts.append(text)
                    valid_indices.append(j)

            # Generate embeddings for valid texts
            if valid_texts:
                batch_embeddings = model.encode(valid_texts, convert_to_numpy=True)

                # Map back to original batch
                batch_results = [None] * len(batch)
                for j, emb_idx in enumerate(valid_indices):
                    batch_results[emb_idx] = batch_embeddings[j].tolist()

                embeddings.extend(batch_results)
            else:
                embeddings.extend([None] * len(batch))

            logger.debug(
                "batch_embeddings_generated",
                batch_start=i,
                batch_size=len(batch),
                valid=len(valid_texts),
            )

        logger.info(
            "batch_generate_embeddings_complete",
            total=len(embeddings),
            successful=sum(1 for e in embeddings if e is not None),
        )

    except Exception as e:
        logger.error(
            "batch_generate_embeddings_failed",
            error=str(e),
            processed=len(embeddings),
        )
        # Pad with None for remaining
        embeddings.extend([None] * (len(texts) - len(embeddings)))

    return embeddings


def cosine_similarity(emb1: List[float], emb2: List[float]) -> float:
    """Calculate cosine similarity between two embeddings.

    Args:
        emb1: First embedding
        emb2: Second embedding

    Returns:
        Cosine similarity [0, 1]
    """
    try:
        vec1 = np.array(emb1)
        vec2 = np.array(emb2)

        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)

        if norm1 == 0 or norm2 == 0:
            return 0.0

        # Cosine similarity is in [-1, 1], normalize to [0, 1]
        similarity = dot_product / (norm1 * norm2)
        return (similarity + 1) / 2

    except Exception as e:
        logger.error("cosine_similarity_failed", error=str(e))
        return 0.0
