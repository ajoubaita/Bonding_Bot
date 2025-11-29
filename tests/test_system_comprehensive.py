"""Comprehensive system test without external dependencies."""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

def test_imports():
    """Test that all modules can be imported."""
    print("Testing imports...")

    try:
        # Test configuration
        from src import config
        print("✓ Config module imported")

        # Test models
        from src.models import database, market, bond
        print("✓ Model modules imported")

        # Test API
        from src.api import main
        print("✓ API main imported")

        # Test similarity features
        from src.similarity.features import (
            text_similarity,
            entity_similarity,
            time_alignment,
            outcome_similarity,
            resolution_similarity,
        )
        print("✓ Similarity features imported")

        # Test similarity calculator
        from src.similarity import calculator, tier_assigner
        print("✓ Similarity calculator imported")

        # Test normalization
        from src.normalization import (
            text_cleaner,
            entity_extractor,
            event_classifier,
        )
        print("✓ Normalization modules imported")

        print("\n✅ All imports successful!\n")
        return True

    except ImportError as e:
        print(f"\n❌ Import failed: {e}\n")
        return False


def test_text_cleaning():
    """Test text cleaning functionality."""
    print("Testing text cleaning...")

    from src.normalization.text_cleaner import clean_text, expand_abbreviations

    # Test HTML stripping
    html_text = "<p>Will BTC reach $100k?</p>"
    cleaned = clean_text(html_text)
    assert "<p>" not in cleaned
    assert "btc" in cleaned or "bitcoin" in cleaned
    print(f"  HTML stripping: '{html_text}' → '{cleaned}'")

    # Test abbreviation expansion
    abbr_text = "Will BTC and ETH reach new highs in Q1?"
    expanded = expand_abbreviations(abbr_text.lower())
    assert "bitcoin" in expanded or "btc" in expanded
    print(f"  Abbreviation: '{abbr_text}' → '{expanded}'")

    print("✅ Text cleaning works!\n")
    return True


def test_entity_extraction_patterns():
    """Test entity extraction patterns."""
    print("Testing entity extraction patterns...")

    from src.normalization.entity_extractor import extract_tickers

    test_cases = [
        ("Will BTC reach $100k?", ["BTC"]),
        ("AAPL stock price", ["AAPL"]),
        ("Bitcoin and Ethereum", ["BITCOIN", "ETHEREUM"]),
    ]

    for text, expected in test_cases:
        tickers = extract_tickers(text)
        print(f"  '{text}' → {tickers}")
        # At least some tickers should be found
        assert len(tickers) > 0 or len(expected) == 0

    print("✅ Entity extraction patterns work!\n")
    return True


def test_event_classification():
    """Test event classification logic."""
    print("Testing event classification...")

    from src.normalization.event_classifier import classify_event_type, determine_geo_scope

    # Test election classification
    entities = {"people": ["Biden"], "countries": ["US"]}
    event_type = classify_event_type("politics", entities, "will biden win the election")
    print(f"  Election: {event_type}")
    assert event_type == "election"

    # Test price target
    entities = {"tickers": ["BTC"]}
    event_type = classify_event_type("crypto", entities, "will btc reach 100k")
    print(f"  Price target: {event_type}")
    assert event_type == "price_target"

    # Test geo scope
    entities = {"countries": ["US"]}
    geo_scope = determine_geo_scope(entities, "united states election")
    print(f"  Geo scope: {geo_scope}")
    assert geo_scope == "US"

    print("✅ Event classification works!\n")
    return True


def test_similarity_features():
    """Test similarity feature calculators (logic only)."""
    print("Testing similarity feature logic...")

    from src.similarity.features.entity_similarity import jaccard_similarity

    # Test Jaccard similarity
    set1 = {"btc", "eth", "usd"}
    set2 = {"btc", "usd", "eur"}
    similarity = jaccard_similarity(set1, set2)
    print(f"  Jaccard({set1}, {set2}) = {similarity:.2f}")
    assert 0 < similarity < 1  # Should be partial overlap

    # Test identical sets
    similarity_identical = jaccard_similarity(set1, set1)
    print(f"  Jaccard(identical) = {similarity_identical:.2f}")
    assert similarity_identical == 1.0

    # Test disjoint sets
    set3 = {"aapl", "tsla"}
    similarity_disjoint = jaccard_similarity(set1, set3)
    print(f"  Jaccard(disjoint) = {similarity_disjoint:.2f}")
    assert similarity_disjoint == 0.0

    print("✅ Similarity features work!\n")
    return True


def test_tier_assignment_logic():
    """Test tier assignment logic."""
    print("Testing tier assignment...")

    from src.similarity.tier_assigner import assign_tier

    # Mock features
    tier1_features = {
        "text": {"score_text": 0.90},
        "entity": {"score_entity_final": 0.92},
        "time": {"score_time_final": 0.95},
        "outcome": {"score_outcome": 1.0},
        "resolution": {"score_resolution": 1.0},
    }

    # Test Tier 1
    tier = assign_tier(p_match=0.99, features=tier1_features, hard_constraints_violated=False)
    print(f"  High confidence: Tier {tier}")
    assert tier == 1

    # Test Tier 2
    tier2_features = tier1_features.copy()
    tier = assign_tier(p_match=0.93, features=tier2_features, hard_constraints_violated=False)
    print(f"  Medium confidence: Tier {tier}")
    assert tier == 2

    # Test Tier 3 (low score)
    tier = assign_tier(p_match=0.85, features=tier2_features, hard_constraints_violated=False)
    print(f"  Low confidence: Tier {tier}")
    assert tier == 3

    # Test hard constraint violation
    tier = assign_tier(p_match=0.99, features=tier1_features, hard_constraints_violated=True)
    print(f"  Hard constraint violated: Tier {tier}")
    assert tier == 3

    print("✅ Tier assignment works!\n")
    return True


def test_cache_logic():
    """Test cache decorator logic (without Redis)."""
    print("Testing cache decorator structure...")

    from src.utils.cache import cached

    # Test decorator application
    @cached(ttl=60, key_prefix="test")
    def expensive_function(x):
        return x * 2

    # Check decorator applied
    assert hasattr(expensive_function, '__wrapped__')
    print(f"  Decorator applied: {expensive_function.__name__}")

    print("✅ Cache decorator structure valid!\n")
    return True


def test_metrics_structure():
    """Test metrics structure (without Redis)."""
    print("Testing metrics structure...")

    from src.utils import metrics

    # Check metric functions exist
    assert hasattr(metrics, 'record_bond_creation')
    assert hasattr(metrics, 'record_similarity_calculation')
    assert hasattr(metrics, 'record_api_request')
    print("  Metric functions exist")

    print("✅ Metrics structure valid!\n")
    return True


def test_api_client_structure():
    """Test API client structure (without making real requests)."""
    print("Testing API client structure...")

    from src.ingestion.kalshi_client import KalshiClient
    from src.ingestion.polymarket_client import PolymarketClient

    # Check clients can be instantiated
    kalshi = KalshiClient()
    poly = PolymarketClient()

    # Check key methods exist
    assert hasattr(kalshi, 'get_markets')
    assert hasattr(kalshi, 'fetch_all_active_markets')
    assert hasattr(kalshi, 'normalize_market')
    print("  Kalshi client structure valid")

    assert hasattr(poly, 'fetch_all_active_markets_with_prices')
    assert hasattr(poly.gamma, 'get_markets')
    assert hasattr(poly.clob, 'get_simplified_markets')
    print("  Polymarket client structure valid")

    print("✅ API clients structured correctly!\n")
    return True


def test_normalization_pipeline_structure():
    """Test normalization pipeline structure."""
    print("Testing normalization pipeline...")

    from src.normalization.pipeline import infer_granularity, infer_polarity

    # Test granularity inference
    assert infer_granularity("by end of day", None) == "day"
    assert infer_granularity("by end of Q1", None) == "quarter"
    assert infer_granularity("by end of year", None) == "year"
    print("  Granularity inference works")

    # Test polarity inference
    assert infer_polarity("Will X happen?") == "positive"
    assert infer_polarity("Will X NOT happen?") == "negative"
    assert infer_polarity("X won't happen") == "negative"
    print("  Polarity inference works")

    print("✅ Normalization pipeline logic valid!\n")
    return True


def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print("BONDING BOT - COMPREHENSIVE SYSTEM TEST")
    print("=" * 60)
    print()

    tests = [
        ("Module Imports", test_imports),
        ("Text Cleaning", test_text_cleaning),
        ("Entity Extraction", test_entity_extraction_patterns),
        ("Event Classification", test_event_classification),
        ("Similarity Features", test_similarity_features),
        ("Tier Assignment", test_tier_assignment_logic),
        ("Cache Structure", test_cache_logic),
        ("Metrics Structure", test_metrics_structure),
        ("API Clients", test_api_client_structure),
        ("Normalization Pipeline", test_normalization_pipeline_structure),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"❌ {name} failed: {e}\n")
            results.append((name, False))

    # Summary
    print("=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")

    print()
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 ALL TESTS PASSED! System is ready for deployment.")
    else:
        print(f"\n⚠️  {total - passed} tests failed. Review errors above.")

    return passed == total


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
