# Similarity Engine - Effectiveness Analysis

**Date**: 2025-01-20
**System Version**: 1.0 (Production MVP)
**Analyst**: Claude Code

---

## Executive Summary

The Bonding Bot similarity engine implements a **5-feature weighted scoring system** with **hard constraint filtering** and **logistic regression probability estimation**. After comprehensive code review, the engine demonstrates:

### Strengths ✓
- **Multi-dimensional matching**: 5 complementary features capture different aspects of market similarity
- **Safety-first design**: Hard constraints prevent catastrophic errors
- **Tiered confidence system**: Clear risk stratification (Tier 1/2/3)
- **Entity-aware**: Specialized handling for tickers, people, organizations
- **Polarity detection**: Prevents negation-induced false matches

### Weaknesses ⚠
- **Untrained logistic regression**: Uses placeholder coefficients (not calibrated on real data)
- **Missing separate title/description embeddings**: Currently uses combined embedding for both
- **No cross-validation**: Thresholds are manually set, not empirically optimized
- **Potential over-reliance on text**: 35% weight on embeddings may miss structural nuances

### Effectiveness Rating: **7.5/10** (Production-Ready but Needs Calibration)

---

## Feature-by-Feature Analysis

### 1. Text Similarity (Weight: 35%)

**Implementation**: `src/similarity/features/text_similarity.py`

**Method**:
- Sentence-transformers embeddings (all-MiniLM-L6-v2, 384 dimensions)
- Cosine similarity between embeddings
- Normalized to [0, 1] from [-1, 1]
- Weighted combination: 70% title + 30% description

**Strengths**:
- ✓ Semantic understanding (captures meaning, not just keywords)
- ✓ Robust to minor wording differences
- ✓ 384-dimensional space provides rich representation
- ✓ Pre-trained model benefits from large corpus knowledge

**Weaknesses**:
- ⚠ Currently uses **combined** embedding for both title and description
  - TODO comment: "Calculate separate title and description embeddings"
  - This reduces granularity - can't weight title vs description differently
- ⚠ Embedding model is general-purpose, not fine-tuned for prediction markets
- ⚠ No handling of platform-specific prefixes/formatting

**Effectiveness**: **8/10**
- Works well for semantically similar markets
- May struggle with markets that are similar in structure but different in wording
- Missing separate embeddings reduces precision slightly

**Recommendation**:
- Generate separate title and description embeddings
- Consider fine-tuning embedding model on prediction market corpus
- Add platform-specific normalization (e.g., remove "KALSHI-" prefixes)

---

### 2. Entity Similarity (Weight: 25%)

**Implementation**: `src/similarity/features/entity_similarity.py`

**Method**:
- Jaccard similarity on extracted entities (tickers, people, orgs, countries)
- Bonuses for exact matches:
  - Ticker exact match: +20%
  - Person exact match: +15%
  - Organization overlap: +10%
- Maximum capped at 1.0

**Strengths**:
- ✓ Captures critical domain entities (BTC, Trump, Fed, etc.)
- ✓ Exact ticker match bonus prevents mixing similar but different assets
- ✓ Handles partial overlaps gracefully
- ✓ Works well for entity-heavy markets (price targets, political events)

**Weaknesses**:
- ⚠ Relies on spaCy NER quality (may miss custom tickers like "SOL", "AAPL")
- ⚠ No fuzzy matching (e.g., "Biden" vs "Joseph Biden")
- ⚠ Equal weighting of entity types (should tickers be more important than misc?)
- ⚠ No synonym handling (e.g., "BTC" vs "Bitcoin")

**Effectiveness**: **7.5/10**
- Strong for markets with clear entities
- Weaker for abstract markets ("Will the economy improve?")
- Ticker bonus is excellent for preventing asset confusion

**Recommendation**:
- Add ticker synonym dictionary (BTC = Bitcoin, ETH = Ethereum)
- Implement fuzzy name matching for people
- Weight tickers more heavily than other entity types
- Expand NER patterns for crypto/stock tickers

---

### 3. Time Alignment (Weight: 15%)

**Implementation**: `src/similarity/features/time_alignment.py`

**Method**:
- Exponential decay on resolution date difference
- Time window overlap for markets with range dates
- Weighted: 60% resolution date + 40% time window overlap

**Strengths**:
- ✓ Exponential decay is appropriate (1-day difference >> 10-day difference)
- ✓ Handles both point-in-time and range markets
- ✓ Hard constraint (>14 days) prevents gross mismatches

**Weaknesses**:
- ⚠ Tau parameter (decay rate) not empirically calibrated
- ⚠ Doesn't account for event type (elections have hard dates, economic metrics are continuous)
- ⚠ No special handling for recurring events (monthly CPI releases)

**Effectiveness**: **8/10**
- Works well for most markets
- May be too strict for markets with intentional temporal spreads

**Recommendation**:
- Adjust tau based on event granularity (daily vs quarterly vs yearly events)
- Add special cases for recurring events
- Consider event type context (elections vs price targets)

---

### 4. Outcome Similarity (Weight: 20%)

**Implementation**: `src/similarity/features/outcome_similarity.py`

**Method**:
- Yes/no: Polarity check + negation detection
- Brackets: Overlap and containment analysis
- Scalar: Value comparison with tolerance

**Strengths**:
- ✓ Polarity detection prevents "Will win" vs "Will not win" false matches
- ✓ Bracket overlap handles price ranges intelligently
- ✓ Handles 3 different outcome types (yes/no, brackets, scalar)
- ✓ Negation detection is sophisticated (checks multiple phrases)

**Weaknesses**:
- ⚠ Negation detection is keyword-based (may miss complex negations)
- ⚠ No handling of implicit negations ("fails to" vs "succeeds")
- ⚠ Bracket comparison doesn't weight closeness (perfect overlap = 1.0, partial overlap = 0.5, but how partial?)
- ⚠ Hard constraint (score_outcome == 0.0) may reject recoverable cases

**Effectiveness**: **9/10**
- Excellent safety mechanism
- Polarity detection prevents costly errors
- Bracket logic is sound

**Recommendation**:
- Add more sophisticated NLP for negation (dependency parsing)
- Implement graduated bracket overlap scoring (not just binary)
- Consider soft reject for borderline cases instead of hard 0.0

---

### 5. Resolution Similarity (Weight: 5%)

**Implementation**: `src/similarity/features/resolution_similarity.py`

**Method**:
- Same source: 1.0
- Similar sources: 0.7
- Different sources: 0.3

**Strengths**:
- ✓ Lightweight and simple
- ✓ Appropriate low weight (5%) - resolution source is less critical than content

**Weaknesses**:
- ⚠ "Similar sources" logic not defined (what qualifies as similar?)
- ⚠ Doesn't account for source reliability (official vs user-reported)
- ⚠ No handling of multi-source resolution

**Effectiveness**: **6/10**
- Works for basic cases
- Under-specified for edge cases
- Low weight mitigates impact of errors

**Recommendation**:
- Define "similar sources" more precisely (e.g., Bloomberg vs Reuters are similar)
- Add source reliability weighting
- Consider source category matching (official govt vs media vs blockchain)

---

## Hard Constraint Analysis

**Location**: `src/similarity/calculator.py:check_hard_constraints()`

### Constraints:
1. `score_text < 0.60` → REJECT
2. `score_entity < 0.20` (unless exact ticker/person match) → REJECT
3. `delta_days > 14` → REJECT
4. `score_outcome == 0.0` → REJECT

### Analysis:

**Strengths**:
- ✓ Prevents catastrophic errors (trading opposite outcomes, wrong assets, wrong time periods)
- ✓ Entity exception (exact ticker match) allows low Jaccard but high confidence matches
- ✓ Conservative thresholds reduce false positives

**Weaknesses**:
- ⚠ Thresholds are manually set, not empirically validated
- ⚠ No soft constraints (could warn instead of reject for borderline cases)
- ⚠ Text threshold (0.60) may be too strict for markets with different wording but same meaning

**Effectiveness**: **8.5/10**
- Excellent safety mechanism
- May reject valid matches due to conservative thresholds

**Recommendation**:
- Collect rejection data and analyze false negatives
- Consider tiered hard constraints (Tier 1 vs Tier 2 have different thresholds)
- Add logging for near-miss rejections to identify threshold issues

---

## Tier Assignment Analysis

**Location**: `src/similarity/tier_assigner.py:assign_tier()`

### Tier 1 (Auto Bond - ≥98% confidence)
**Requirements**:
- `p_match ≥ 0.98`
- `score_text ≥ 0.85`
- `score_outcome ≥ 0.95`
- `score_time_final ≥ 0.90`
- `score_resolution ≥ 0.95`

**Analysis**:
- ✓ Extremely strict criteria → 99.5%+ accuracy achievable
- ✓ Requires high scores across **all** critical dimensions
- ⚠ May be too strict - could miss valid arbitrage opportunities

### Tier 2 (Cautious Bond - ≥90% confidence)
**Requirements**:
- `p_match ≥ 0.90`
- `score_text ≥ 0.70`
- `score_outcome ≥ 0.70`
- `score_time_final ≥ 0.70`

**Analysis**:
- ✓ More flexible than Tier 1
- ✓ Still requires strong alignment on key features
- ⚠ Lower text threshold (0.70) may allow semantic mismatches

### Tier 3 (Reject)
**All others**

**Overall Tier Effectiveness**: **8/10**
- Clear risk stratification
- Conservative approach reduces losses
- May leave money on table with overly strict Tier 1

---

## Match Probability Calculation (Critical Issue)

**Location**: `src/similarity/calculator.py:calculate_match_probability()`

### Current Implementation:
```python
beta = [
    -5.0,  # intercept
    4.2,   # text
    3.1,   # entity
    2.5,   # time
    3.8,   # outcome
    1.2,   # resolution
]
```

### Issue: **PLACEHOLDER COEFFICIENTS**

The code contains this TODO:
```python
# TODO: Train these from actual labeled data
# These are example parameters
```

**Impact**: 🔴 **CRITICAL**
- The `p_match` probability is calculated using **untrained coefficients**
- This means the 98% Tier 1 threshold and 90% Tier 2 threshold are **arbitrary**
- Without calibration, the system cannot guarantee 99.5%+ accuracy

**Effectiveness**: **4/10** (Concept is sound, implementation is incomplete)

**Urgent Recommendation**:
1. **Collect labeled training data**:
   - Sample 100-200 market pairs
   - Manually label as match/no-match
   - Include edge cases and near-misses

2. **Train logistic regression**:
   - Fit beta coefficients on labeled data
   - Cross-validate to prevent overfitting
   - Calibrate to achieve desired accuracy (99.5% for Tier 1)

3. **Validate on hold-out set**:
   - Test on 50+ pairs not used in training
   - Measure precision, recall, F1
   - Adjust thresholds if needed

4. **Continuous learning**:
   - Track all bonds and their post-resolution outcomes
   - Retrain quarterly with new data
   - Alert on drift (accuracy degradation)

**Alternative (Short-term)**:
- Use conservative weighted score only (ignore p_match for now)
- Set Tier 1 threshold at weighted_score ≥ 0.95 + all hard constraints
- Deploy with manual review for first 50 bonds

---

## Feature Weighting Analysis

### Current Weights:
- Text: 35%
- Entity: 25%
- Time: 15%
- Outcome: 20%
- Resolution: 5%

### Analysis:

**Strengths**:
- ✓ Text is highest (semantic meaning is most important)
- ✓ Outcome is significant (20%) - prevents structural mismatches
- ✓ Resolution is low (5%) - appropriately de-emphasized
- ✓ Weights sum to 1.0 (validated in config)

**Potential Issues**:
- ⚠ Text (35%) + Entity (25%) = 60% focused on content, only 40% on structure
- ⚠ Time (15%) may be too low for time-sensitive events (elections)
- ⚠ Outcome (20%) may be too low given its criticality

**Effectiveness**: **7/10**
- Reasonable default weighting
- Not empirically optimized
- May need adjustment for different market types

**Recommendation**:
- **Event-specific weights**:
  - Elections: Increase time (20%), decrease text (30%)
  - Price targets: Increase entity (30%), decrease time (10%)
  - Economic data: Increase time (20%), decrease outcome (15%)
- **A/B test different weightings** with labeled data
- **Allow configuration override** per market category

---

## Overall System Effectiveness

### Precision vs Recall Trade-off

**Current System**: **High Precision, Low Recall**
- Hard constraints + strict Tier 1 criteria = few false positives
- But may reject valid arbitrage opportunities (false negatives)

**Quantitative Estimates** (based on code analysis, not empirical data):
- **Tier 1 Precision**: 95-98% (with calibrated logistic regression)
- **Tier 1 Recall**: 30-50% (many valid matches rejected by strict thresholds)
- **Tier 2 Precision**: 90-93%
- **Tier 2 Recall**: 50-70%

### Risk Assessment:
- **False Positive Risk**: LOW (hard constraints prevent most errors)
- **False Negative Risk**: MODERATE-HIGH (may miss 50-70% of valid arbitrage)
- **Catastrophic Error Risk**: VERY LOW (hard constraints + Tier 1 requirements)

---

## Key Findings

### 🟢 What's Working Well:
1. **Multi-dimensional approach**: 5 features capture complementary signals
2. **Hard constraints**: Excellent safety net preventing gross mismatches
3. **Polarity detection**: Prevents negation-induced errors
4. **Ticker bonuses**: Reduces asset confusion
5. **Tiered confidence**: Clear risk stratification
6. **Safety-first design**: Conservative thresholds protect capital

### 🟡 Needs Improvement:
1. **Untrained logistic regression**: Placeholder coefficients (CRITICAL)
2. **Missing separate embeddings**: Title and description use same embedding
3. **No empirical validation**: Thresholds manually set, not data-driven
4. **Limited entity handling**: No fuzzy matching, synonyms, or weighted types
5. **Fixed weights**: Same weights for all market types
6. **No cross-validation**: Can't measure true precision/recall

### 🔴 Critical Gaps:
1. **No training data**: System has never been validated on real market pairs
2. **No backtesting**: No historical validation of accuracy claims
3. **No monitoring**: No post-resolution accuracy tracking implemented
4. **No recalibration loop**: No plan for ongoing model improvement

---

## Recommendations (Prioritized)

### 🔥 Immediate (Pre-Production):
1. **Collect labeled training data** (100-200 pairs)
2. **Train logistic regression** or replace with weighted score only
3. **Set conservative Tier 1 threshold** (weighted_score ≥ 0.95)
4. **Implement post-resolution tracking** (already in code, needs activation)
5. **Manual review first 50 bonds** regardless of tier

### 📅 Short-term (Month 1):
1. **Generate separate title/description embeddings**
2. **Add ticker synonym dictionary** (BTC=Bitcoin, etc.)
3. **Implement fuzzy name matching** for people
4. **Event-specific weight configurations**
5. **Validate on 50+ historical market pairs**

### 📈 Medium-term (Quarter 1):
1. **Fine-tune embedding model** on prediction market corpus
2. **Implement graduated bracket overlap scoring**
3. **Add more sophisticated negation detection** (dependency parsing)
4. **Build calibration dashboard** (precision/recall by tier, feature)
5. **A/B test different weighting schemes**

### 🚀 Long-term (Ongoing):
1. **Continuous learning**: Retrain quarterly on new data
2. **Drift detection**: Alert on accuracy degradation
3. **Market type classifier**: Auto-select weights based on category
4. **Ensemble approach**: Combine multiple models (voting, stacking)
5. **Active learning**: Flag uncertain cases for manual labeling

---

## Production Readiness Assessment

### Can we deploy today?

**Answer**: **YES, with caveats**

**Safe Deployment Plan**:
1. ✅ Use **weighted score only** (ignore untrained p_match)
2. ✅ Set Tier 1 threshold: `weighted_score ≥ 0.95 AND all hard constraints AND manual review`
3. ✅ Set Tier 2 threshold: `weighted_score ≥ 0.85 AND all hard constraints AND reduced size`
4. ✅ Reject all Tier 3
5. ✅ Monitor every bond outcome
6. ✅ Retrain after 50 resolved bonds

**Expected Performance** (conservative estimate):
- **Tier 1 Accuracy**: 93-96% (below 99.5% target due to no calibration)
- **Tier 2 Accuracy**: 88-92%
- **Arbitrage Opportunities Found**: 20-40% of actual opportunities (low recall)

**Risk Level**: **ACCEPTABLE** for initial deployment with manual oversight

---

## Conclusion

The Bonding Bot similarity engine is **well-designed but undertrained**. The architecture is sound, with multiple complementary features and strong safety mechanisms. However, the lack of empirical validation means the system cannot guarantee its 99.5%+ accuracy target for Tier 1 bonds.

**Key Insight**: The system prioritizes **precision over recall** - it will miss many valid arbitrage opportunities, but those it does identify should be high confidence (assuming calibration).

**Bottom Line**:
- **Current state**: 7.5/10 - Production-ready with manual review
- **Potential state** (with training data): 9/10 - Fully autonomous Tier 1 bonds
- **Deployment recommendation**: Proceed with conservative thresholds and human oversight

---

**Next Steps**: See recommendations above. Priority is collecting training data and either training the logistic regression or switching to weighted-score-only approach.
