"""Unit tests for text similarity calculator."""

import pytest
import numpy as np
from src.similarity.features.text_similarity import cosine_similarity, calculate_text_similarity
from src.models import Market


class TestCosineSimilarity:
    """Test cosine similarity function."""

    def test_identical_vectors(self):
        """Test cosine similarity of identical vectors."""
        vec1 = np.array([1, 2, 3, 4])
        vec2 = np.array([1, 2, 3, 4])
        similarity = cosine_similarity(vec1, vec2)
        assert similarity == pytest.approx(1.0, abs=0.01)

    def test_orthogonal_vectors(self):
        """Test cosine similarity of orthogonal vectors."""
        vec1 = np.array([1, 0, 0])
        vec2 = np.array([0, 1, 0])
        similarity = cosine_similarity(vec1, vec2)
        assert similarity == pytest.approx(0.5, abs=0.01)  # Normalized to [0,1]

    def test_opposite_vectors(self):
        """Test cosine similarity of opposite vectors."""
        vec1 = np.array([1, 2, 3])
        vec2 = np.array([-1, -2, -3])
        similarity = cosine_similarity(vec1, vec2)
        assert similarity == pytest.approx(0.0, abs=0.01)  # Normalized to [0,1]

    def test_zero_vector(self):
        """Test cosine similarity with zero vector."""
        vec1 = np.array([1, 2, 3])
        vec2 = np.array([0, 0, 0])
        similarity = cosine_similarity(vec1, vec2)
        assert similarity == 0.0


@pytest.mark.unit
class TestTextSimilarity:
    """Test text similarity calculator."""

    def test_missing_embeddings(self):
        """Test handling of missing embeddings."""
        market_k = Market(
            id="test_k",
            platform="kalshi",
            text_embedding=None,
        )
        market_p = Market(
            id="test_p",
            platform="polymarket",
            text_embedding=None,
        )

        result = calculate_text_similarity(market_k, market_p)

        assert result["score_text"] == 0.0
        assert result["score_title"] == 0.0
        assert result["score_desc"] == 0.0

    def test_similar_embeddings(self):
        """Test similar embeddings."""
        # Create similar embeddings
        embedding_k = np.random.rand(384).tolist()
        embedding_p = (np.array(embedding_k) + np.random.normal(0, 0.1, 384)).tolist()

        market_k = Market(
            id="test_k",
            platform="kalshi",
            text_embedding=embedding_k,
        )
        market_p = Market(
            id="test_p",
            platform="polymarket",
            text_embedding=embedding_p,
        )

        result = calculate_text_similarity(market_k, market_p)

        # Should have high similarity
        assert result["score_text"] > 0.5
        assert result["score_title"] > 0.5
        assert result["score_desc"] > 0.5
