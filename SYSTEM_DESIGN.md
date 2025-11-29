# Market Bonding Agent MVP — System Design

**Purpose**: Determine whether a Kalshi market and a Polymarket market represent the same underlying economic event for safe cross-exchange arbitrage.

**Safety Level**: Production-ready for real-money HFT usage.

---

## 1. Goal

### System Requirements

The bonding agent must:

- **Input**: One Kalshi market `K` and one Polymarket market `P`
- **Output**:
  - Similarity score `S ∈ [0,1]`
  - Match probability `p_match ∈ [0,1]`
  - Tier classification: `{1, 2, 3}`

### Tier Definitions

| Tier | Label | Criteria | Trading Action |
|------|-------|----------|----------------|
| 1 | Auto Bond | `p_match ≥ 0.98`, unambiguous mapping | Full arbitrage size |
| 2 | Cautious Bond | `0.90 ≤ p_match < 0.98` | Reduced size (10-25%) |
| 3 | Reject | `p_match < 0.90` OR hard constraint failed | No trading |

**Philosophy**: Optimize for **precision over recall**. False negatives (missed opportunities) are acceptable. False positives (incorrect bonds) are catastrophic.

---

## 2. External Exchange Integrations

### A. Kalshi Integration

#### Required Endpoints

1. **Market Listing Endpoint**
   - **Role**: Discover all active and upcoming markets
   - **Data**: Market IDs, categories, status flags
   - **Polling**: Every 60 seconds for new markets

2. **Market Metadata Endpoint**
   - **Role**: Fetch detailed market information
   - **Data**:
     - Title, subtitle
     - Category, subcategory
     - Resolution rules and source
     - Close/expiration/settlement timestamps
     - Outcome structure (yes/no, bracket ranges)
   - **Polling**: On-demand when new market detected

3. **Market Rules Endpoint**
   - **Role**: Extract resolution criteria and edge cases
   - **Data**: Plain-text rules, resolution authority references
   - **Polling**: Once per market on ingestion

4. **Price/Orderbook Endpoint** (Optional for MVP)
   - **Role**: Sanity check that markets are liquid
   - **Data**: Best bid/ask, spread, volume
   - **Usage**: Filter out dead markets before bonding

#### Update Strategy

- **Discovery**: Poll market listing every 60s
- **Metadata**: Fetch on-demand for new/updated markets
- **Incremental**: Track last-seen market ID, fetch only newer markets
- **Backfill**: Full refresh every 24 hours

#### Rate Limit Handling

- **Default**: 100 requests/minute assumed
- **Strategy**:
  - Use exponential backoff on 429 responses
  - Maintain internal request queue with rate limiter
  - Prioritize metadata fetches over discovery polls
  - Cache metadata for 5 minutes
  - Graceful degradation: Skip low-priority updates if rate-limited

---

### B. Polymarket Integration

#### Required Endpoints

1. **Gamma API - Market Discovery**
   - **Role**: List all active markets with metadata
   - **Data**: Market IDs, condition IDs, slugs, status, end dates
   - **Polling**: Every 60 seconds

2. **Gamma API - Market Details**
   - **Role**: Fetch full market metadata
   - **Data**:
     - Question text
     - Description
     - Category/tags
     - Resolution source
     - End date
     - Token IDs for outcomes
   - **Polling**: On-demand for new markets

3. **CLOB API - Simplified Markets**
   - **Role**: Get outcome schemas and current prices
   - **Data**:
     - Token mappings (outcome names → token IDs)
     - Yes/No/Other outcome labels
     - Price sanity data
   - **Polling**: On-demand during ingestion

4. **Resolution Metadata** (if available)
   - **Role**: Extract official resolution criteria
   - **Data**: Resolution rules, data sources

#### Update Strategy

- **Discovery**: Poll Gamma simplified markets every 60s
- **Filtering**: Fetch only `active=True, closed=False` markets
- **Metadata Enrichment**: Combine Gamma + CLOB data on ingestion
- **Incremental**: Track last-seen condition IDs

#### Rate Limit Handling

- **Default**: Assume 100-200 requests/minute
- **Strategy**:
  - Batch requests where possible (CLOB `/books`, `/prices`)
  - Use simplified-markets endpoint (single call for all markets)
  - Cache for 5 minutes
  - Exponential backoff on failures
  - Degrade to stale data rather than block

---

## 3. Internal Normalized Market Schema

### Schema Definition

```json
{
  "id": "string",                    // Platform-specific market ID
  "platform": "kalshi | polymarket",
  "condition_id": "string | null",   // Polymarket condition ID (for matching)
  "status": "active | closed | resolved",

  "raw_title": "string",             // Original title from platform
  "raw_description": "string",       // Original description
  "clean_title": "string",           // Normalized title (lowercased, stripped)
  "clean_description": "string",     // Normalized description

  "category": "string",              // Platform category (politics, sports, crypto, etc.)
  "event_type": "string",            // Derived: election, price_target, rate_decision, etc.

  "entities": {
    "tickers": ["BTC", "AAPL"],      // Financial instruments
    "people": ["Biden", "Powell"],   // Named individuals
    "organizations": ["Fed", "CPI"], // Institutions/indices
    "countries": ["US", "China"],    // Geographic entities
    "misc": ["Super Bowl", "Q1"]     // Other named entities
  },

  "geo_scope": "global | US | EU | specific_country",

  "time_window": {
    "start": "ISO8601 | null",       // Event observation period start
    "end": "ISO8601 | null",         // Event observation period end
    "resolution_date": "ISO8601",    // When market settles
    "granularity": "day | week | month | quarter | year"
  },

  "resolution_source": "string",     // e.g., "BLS", "FOMC", "CoinGecko", "AP"

  "outcome_type": "yes_no | discrete_brackets | scalar_range",

  "outcome_schema": {
    // For yes_no:
    "type": "yes_no",
    "polarity": "positive | negative", // Does "yes" mean event happens?
    "outcomes": [
      {"label": "Yes", "token_id": "...", "value": true},
      {"label": "No", "token_id": "...", "value": false}
    ],

    // For discrete_brackets:
    "type": "discrete_brackets",
    "unit": "dollars | percent | basis_points | count",
    "brackets": [
      {"label": "< 50", "min": null, "max": 50, "token_id": "..."},
      {"label": "50-100", "min": 50, "max": 100, "token_id": "..."},
      {"label": "> 100", "min": 100, "max": null, "token_id": "..."}
    ],

    // For scalar_range:
    "type": "scalar_range",
    "min": 0,
    "max": 100,
    "unit": "dollars | percent | count"
  },

  "text_embedding": [0.123, -0.456, ...],  // 384-dim vector from sentence-transformers

  "metadata": {
    "created_at": "ISO8601",
    "last_updated": "ISO8601",
    "ingestion_version": "v1.0.0",   // Schema version for migrations
    "liquidity": 12345.67,           // For filtering dead markets
    "volume": 98765.43
  }
}
```

### Normalization Pipeline

#### Frequency
- **New markets**: Immediate ingestion on discovery
- **Updates**: Re-normalize if raw title/description changes
- **Batch refresh**: Full re-normalization every 24 hours (for schema migrations)

#### Steps

1. **Text Cleaning**
   - Lowercase
   - Strip HTML tags
   - Normalize whitespace
   - Remove platform-specific prefixes (e.g., "Kalshi:" or "Will...")
   - Expand common abbreviations ("BTC" → "Bitcoin")

2. **Entity Extraction**
   - Named Entity Recognition (NER) using spaCy or similar
   - Custom regex patterns for tickers, indices
   - Maintain whitelist of common entities per category

3. **Event Type Classification**
   - Rule-based classifier on category + keywords
   - Examples:
     - "election" → category=politics + entities.people
     - "price_target" → category=crypto + entities.tickers + brackets
     - "rate_decision" → entities.organizations=["Fed", "FOMC"]

4. **Time Window Extraction**
   - Parse resolution_date from platform metadata
   - Extract observation window from description:
     - "by end of Q1 2025" → end = "2025-03-31"
     - "on November 5" → start = end = "2025-11-05"
   - Default to resolution_date if no explicit window

5. **Outcome Schema Parsing**
   - Detect yes/no vs brackets via platform metadata
   - For brackets: extract min/max/unit from outcome labels
   - Validate polarity (does "Yes" mean event happens?)

6. **Text Embedding**
   - Concatenate: `clean_title + " | " + clean_description`
   - Embed using `sentence-transformers/all-MiniLM-L6-v2` (384-dim)
   - Store in database for fast similarity search

---

## 4. Candidate Generation (Fast Filter)

### Goal
Reduce `O(N_kalshi × N_polymarket)` comparisons to `O(N_kalshi × 20)` candidates per market.

### Filter Pipeline

For each Kalshi market `K`, find Polymarket candidates `P` where:

#### 1. Category Match
- **Rule**: `K.category` must overlap with `P.category`
- **Implementation**:
  - Maintain category mapping: `{"politics": ["politics", "elections"], ...}`
  - Allow cross-category matches for close categories (e.g., "crypto" ↔ "finance")
- **Reject**: If no category overlap

#### 2. Time Window Overlap
- **Rule**: `|K.resolution_date - P.resolution_date| ≤ 7 days`
- **Implementation**: Index markets by resolution_date, query ±7 day range
- **Exceptions**:
  - Quarterly events: Allow ±14 days
  - Annual events: Allow ±30 days
- **Reject**: If no overlap

#### 3. Entity Overlap
- **Rule**: `Jaccard(K.entities, P.entities) ≥ 0.3`
- **Implementation**: Flatten all entity types, compute set intersection
- **Boosting**:
  - Exact ticker match → automatic pass
  - Exact person name match → automatic pass
- **Reject**: If `Jaccard < 0.1` AND no exact matches

#### 4. Outcome Type Compatibility
- **Rule**: `K.outcome_type` must be compatible with `P.outcome_type`
- **Compatible pairs**:
  - `yes_no ↔ yes_no`
  - `discrete_brackets ↔ discrete_brackets` (if units match)
  - `yes_no ↔ discrete_brackets` (if brackets can collapse to binary)
- **Reject**: If incompatible

#### 5. Fast Text Similarity
- **Rule**: `embedding_cosine(K, P) ≥ 0.5`
- **Implementation**:
  - Use FAISS or Annoy for approximate nearest neighbor search
  - Query top-50 by embedding similarity
- **Reject**: If `cosine < 0.3`

#### 6. Keyword Match (Fallback)
- **Rule**: At least 2 significant keywords overlap
- **Implementation**: TF-IDF on title+description, extract top-10 keywords
- **Usage**: Rescue candidates that failed embedding threshold

### Output
- **Target**: ≤ 20 candidates per market
- **Ranking**: Sort by embedding similarity (highest first)
- **Caching**: Cache candidate lists for 10 minutes

---

## 5. Similarity Calculator (Feature-Level)

### Overview

For each candidate pair `(K, P)`, compute:
- Individual feature scores `f_1, ..., f_N ∈ [0,1]`
- Combined score `S ∈ [0,1]`
- Match probability `p_match ∈ [0,1]`

---

### A. Text Similarity

#### A1. Title Embedding Similarity
```python
score_title = cosine_similarity(K.text_embedding_title, P.text_embedding_title)
# Range: [0, 1]
```

#### A2. Description Embedding Similarity
```python
score_desc = cosine_similarity(K.text_embedding_desc, P.text_embedding_desc)
# Range: [0, 1]
```

#### A3. Combined Text Score
```python
score_text = 0.7 * score_title + 0.3 * score_desc
# Weight title more heavily (descriptions can be verbose/divergent)
```

#### Thresholds
- **Tier 1**: `score_text ≥ 0.85`
- **Tier 2**: `score_text ≥ 0.70`
- **Reject**: `score_text < 0.60` (hard constraint)

---

### B. Entity Similarity

#### B1. Overall Entity Jaccard
```python
all_K = flatten(K.entities)  # All entity types combined
all_P = flatten(P.entities)
score_entity = Jaccard(all_K, all_P) = |intersection| / |union|
# Range: [0, 1]
```

#### B2. Type-Specific Bonuses
```python
bonus_ticker = 1.0 if exact_match(K.entities.tickers, P.entities.tickers) else 0.0
bonus_person = 1.0 if exact_match(K.entities.people, P.entities.people) else 0.0
bonus_org = 0.5 if any_overlap(K.entities.organizations, P.entities.organizations) else 0.0
```

#### B3. Final Entity Score
```python
score_entity_final = min(1.0, score_entity + 0.2*bonus_ticker + 0.15*bonus_person + 0.1*bonus_org)
```

#### Hard Constraints
- **Reject** if `score_entity < 0.2` AND no exact ticker/person match

---

### C. Time Alignment

#### C1. Resolution Date Difference
```python
delta_days = abs(K.resolution_date - P.resolution_date).days
score_time = exp(-delta_days / tau)
# tau = 3 days for daily events, 7 days for weekly, 14 for monthly
```

#### C2. Observation Window Overlap
```python
overlap = intersection(K.time_window, P.time_window)
union = union_span(K.time_window, P.time_window)
score_window = overlap.days / union.days if union > 0 else 0.0
```

#### C3. Combined Time Score
```python
score_time_final = 0.6 * score_time + 0.4 * score_window
```

#### Hard Constraints
- **Tier 1**: `delta_days ≤ 3` (or ≤7 for quarterly events)
- **Tier 2**: `delta_days ≤ 7`
- **Reject**: `delta_days > 14`

---

### D. Outcome Structure Similarity

#### D1. Yes/No Markets

**Polarity Check**:
```python
# Does "Yes" mean the same thing?
if K.outcome_schema.type == "yes_no" and P.outcome_schema.type == "yes_no":
    same_polarity = (K.outcome_schema.polarity == P.outcome_schema.polarity)
    # Check for complement: "Will X happen?" vs "Will X NOT happen?"
    is_complement = detect_negation_in_title(K.clean_title, P.clean_title)

    if same_polarity and not is_complement:
        score_outcome = 1.0
    elif not same_polarity and is_complement:
        score_outcome = 1.0  # Inverted but mappable
    else:
        score_outcome = 0.0  # REJECT
```

**Hard Constraint**: Reject if polarity mismatch without clear negation.

---

#### D2. Discrete Bracket Markets

**Unit Match**:
```python
if K.outcome_schema.unit != P.outcome_schema.unit:
    score_outcome = 0.0  # REJECT (e.g., "dollars" vs "percent")
```

**Bracket Overlap**:
```python
# Compare bracket boundaries
K_brackets = [(b.min, b.max) for b in K.outcome_schema.brackets]
P_brackets = [(b.min, b.max) for b in P.outcome_schema.brackets]

exact_match = (K_brackets == P_brackets)
partial_overlap = sum(1 for kb in K_brackets if any(overlaps(kb, pb) for pb in P_brackets))
total_brackets = max(len(K_brackets), len(P_brackets))

if exact_match:
    score_outcome = 1.0
else:
    score_outcome = partial_overlap / total_brackets
```

**Hard Constraints**:
- **Tier 1**: Exact bracket match OR ≥90% overlap
- **Tier 2**: ≥70% overlap
- **Reject**: <50% overlap OR unit mismatch

---

#### D3. Scalar Range Markets

**Range Compatibility**:
```python
if K.outcome_schema.type == "scalar_range" and P.outcome_schema.type == "scalar_range":
    if K.outcome_schema.unit != P.outcome_schema.unit:
        score_outcome = 0.0  # REJECT

    K_range = (K.outcome_schema.min, K.outcome_schema.max)
    P_range = (P.outcome_schema.min, P.outcome_schema.max)

    # Ranges must be identical or one strictly contains the other
    if K_range == P_range:
        score_outcome = 1.0
    elif contains(K_range, P_range) or contains(P_range, K_range):
        score_outcome = 0.8  # Cautious bond
    else:
        score_outcome = 0.0  # REJECT
```

---

#### D4. Cross-Type Compatibility

**Binary Collapse**:
```python
# Can discrete brackets collapse to yes/no?
if K.outcome_schema.type == "yes_no" and P.outcome_schema.type == "discrete_brackets":
    if len(P.outcome_schema.brackets) == 2:
        # Map brackets to yes/no if they're exhaustive
        score_outcome = 0.9  # Tier 2 only
    else:
        score_outcome = 0.0  # REJECT
```

---

### E. Resolution Source Similarity

```python
# Extract authority from resolution_source field
K_source = normalize_source(K.resolution_source)  # "BLS" → "bureau_of_labor_statistics"
P_source = normalize_source(P.resolution_source)

if K_source == P_source and K_source != "unknown":
    score_resolution = 1.0
elif similar_sources(K_source, P_source):  # e.g., "CoinGecko" ~ "CoinMarketCap"
    score_resolution = 0.7
else:
    score_resolution = 0.3  # Different sources → risky
```

**Hard Constraint**:
- **Tier 1**: Same resolution source required
- **Tier 2**: Similar sources acceptable

---

### F. Hard Constraints (Auto-Reject)

Immediately set `score = 0.0` and `tier = 3` if ANY of:

1. **Polarity Mismatch**: Yes/no markets with opposite polarity and no clear negation
2. **Unit Mismatch**: Bracket/scalar markets with different units (dollars vs percent)
3. **Time Skew**: `|resolution_date_diff| > 14 days`
4. **Text Dissimilarity**: `score_text < 0.60`
5. **Entity Disjoint**: `score_entity < 0.2` AND no exact ticker/person match
6. **Outcome Incompatible**: `score_outcome == 0.0`
7. **Resolution Conflict**: Explicit contradictory resolution rules (manual review flag)

---

### G. Final Score Aggregation

#### G1. Feature Weights (Logistic Calibration)

```python
# Feature vector
features = [
    score_text,          # w1 = 0.35
    score_entity_final,  # w2 = 0.25
    score_time_final,    # w3 = 0.15
    score_outcome,       # w4 = 0.20
    score_resolution,    # w5 = 0.05
]

weights = [0.35, 0.25, 0.15, 0.20, 0.05]

# Weighted sum
S = sum(w_i * f_i for w_i, f_i in zip(weights, features))
# S ∈ [0, 1]
```

#### G2. Match Probability (Logistic Regression)

```python
# Calibrate using labeled dataset (see below)
# Logistic model: p_match = 1 / (1 + exp(-z))
# where z = beta_0 + beta_1*f_1 + ... + beta_5*f_5

# Example calibrated parameters (from manual labeling):
beta = [-5.0, 4.2, 3.1, 2.5, 3.8, 1.2]  # [intercept, w1, ..., w5]

z = beta[0] + sum(beta[i+1] * features[i] for i in range(len(features)))
p_match = 1.0 / (1.0 + exp(-z))
# p_match ∈ [0, 1]
```

#### G3. Calibration Dataset

**Minimum Labeled Pairs**: 100
- 30 confirmed matches (same event on both platforms)
- 50 confirmed non-matches (different events)
- 20 edge cases (similar but different, e.g., monthly vs quarterly targets)

**Labeling Process**:
1. Manual review by 2 independent analysts
2. Consensus required for ground truth
3. Iterative: Retrain model weekly as new edge cases emerge

**Validation**:
- Hold out 20% for testing
- Target metrics:
  - **Precision @ Tier 1**: ≥99.5% (false positive rate <0.5%)
  - **Recall @ Tier 1+2**: ≥80% (capture most true matches)

---

## 6. Tier Thresholds & Safety Rules

### Tier Assignment Logic

```python
def assign_tier(p_match, features, hard_constraints_violated):
    if hard_constraints_violated:
        return 3  # REJECT

    # Tier 1: Auto Bond
    if (p_match >= 0.98 and
        features.score_text >= 0.85 and
        features.score_outcome >= 0.95 and
        features.score_time_final >= 0.90 and
        features.score_resolution >= 0.95):
        return 1

    # Tier 2: Cautious Bond
    elif (p_match >= 0.90 and
          features.score_text >= 0.70 and
          features.score_outcome >= 0.70 and
          features.score_time_final >= 0.70):
        return 2

    # Tier 3: Reject
    else:
        return 3
```

### Tier-Specific Trading Rules

| Tier | Max Notional | Position Limit | Review Requirement |
|------|--------------|----------------|-------------------|
| 1 | Full size (100%) | 10% of book liquidity | None |
| 2 | Reduced size (10-25%) | 5% of book liquidity | Optional daily review |
| 3 | Zero | Zero | N/A |

### Precision vs Recall Philosophy

- **False Positive** (bad bond): Catastrophic — leads to directional loss
- **False Negative** (missed opportunity): Acceptable — just missed profit
- **Strategy**: Err on the side of rejection
  - Set Tier 1 thresholds very high (p_match ≥ 0.98)
  - Manual review queue for Tier 2 (optional)
  - Never auto-trade Tier 3

### Dynamic Threshold Adjustment

- Monitor realized bond accuracy weekly
- If any Tier 1 bond fails (markets resolve differently):
  - Pause all Tier 1 bonds immediately
  - Investigate root cause
  - Increase threshold to 0.99 temporarily
- If Tier 2 failure rate >5%:
  - Demote to manual-review-required

---

## 7. Internal REST API Design (Bonding Service MVP)

### API Conventions

- **Auth**: Internal service-to-service auth via API key in `X-API-Key` header
- **Content-Type**: `application/json`
- **Error Format**:
  ```json
  {
    "error": {
      "code": "INVALID_MARKET_ID",
      "message": "Market not found",
      "details": {"market_id": "XYZ123", "platform": "kalshi"}
    }
  }
  ```
- **Rate Limiting**: 100 requests/minute per client
- **Versioning**: `/v1/` prefix (future-proof)

---

### Endpoint 1: Ingest Markets

**POST** `/v1/markets/ingest`

**Purpose**: Batch ingest raw markets from either platform, normalize, and store.

**Request**:
```json
{
  "platform": "kalshi | polymarket",
  "markets": [
    {
      "id": "KALSHI-ABC-123",
      "title": "Will Bitcoin reach $100k by EOY 2025?",
      "description": "Resolves YES if BTC ≥ $100,000 on CoinGecko...",
      "category": "crypto",
      "resolution_date": "2025-12-31T23:59:59Z",
      "resolution_source": "CoinGecko",
      "outcome_type": "yes_no",
      "outcomes": [
        {"label": "Yes", "token_id": "..."},
        {"label": "No", "token_id": "..."}
      ],
      "metadata": {
        "liquidity": 50000,
        "volume": 250000
      }
    }
  ]
}
```

**Response**:
```json
{
  "ingested": 1,
  "failed": 0,
  "results": [
    {
      "id": "KALSHI-ABC-123",
      "status": "success",
      "normalized_id": "norm_kalshi_abc_123"
    }
  ]
}
```

**Implementation Notes**:
- Idempotent: Re-ingesting same market updates existing record
- Async processing: Returns immediately, processing in background
- Triggers candidate generation after normalization

---

### Endpoint 2: Get Candidates

**GET** `/v1/markets/{platform}/{market_id}/candidates`

**Purpose**: Retrieve cross-platform candidate markets for bonding.

**Request**: None (query params optional)
```
GET /v1/markets/kalshi/KALSHI-ABC-123/candidates?limit=10
```

**Response**:
```json
{
  "market_id": "KALSHI-ABC-123",
  "platform": "kalshi",
  "candidates": [
    {
      "market_id": "poly_cond_xyz789",
      "platform": "polymarket",
      "title": "Bitcoin to $100k in 2025",
      "quick_similarity": {
        "text_score": 0.87,
        "entity_score": 0.92,
        "time_score": 0.95,
        "overall": 0.89
      },
      "rank": 1
    },
    {
      "market_id": "poly_cond_def456",
      "platform": "polymarket",
      "title": "BTC price above $100,000 by Dec 2025",
      "quick_similarity": {
        "text_score": 0.82,
        "entity_score": 0.88,
        "time_score": 0.91,
        "overall": 0.85
      },
      "rank": 2
    }
  ],
  "total_candidates": 2
}
```

**Implementation Notes**:
- Cache for 10 minutes
- Auto-refresh if source market updated
- Limit default: 20

---

### Endpoint 3: Get Bonded Pairs

**GET** `/v1/pairs/{platform}/{market_id}`

**Purpose**: Return all Tier 1 and Tier 2 bonded pairs for a specific market.

**Request**:
```
GET /v1/pairs/kalshi/KALSHI-ABC-123?include_tier=1,2
```

**Response**:
```json
{
  "market_id": "KALSHI-ABC-123",
  "platform": "kalshi",
  "bonds": [
    {
      "pair_id": "bond_abc123_xyz789",
      "counterparty_market_id": "poly_cond_xyz789",
      "counterparty_platform": "polymarket",
      "tier": 1,
      "p_match": 0.987,
      "similarity_score": 0.92,
      "outcome_mapping": {
        "kalshi_yes": "polymarket_token_yes_abc",
        "kalshi_no": "polymarket_token_no_def"
      },
      "feature_breakdown": {
        "text_similarity": 0.87,
        "entity_similarity": 0.92,
        "time_alignment": 0.95,
        "outcome_similarity": 1.0,
        "resolution_similarity": 1.0
      },
      "created_at": "2025-01-15T10:30:00Z",
      "last_validated": "2025-01-20T14:22:00Z"
    }
  ],
  "total_bonds": 1
}
```

**Implementation Notes**:
- Only return active bonds (both markets still open)
- Include validation timestamp for staleness checks
- Filter by tier via query param

---

### Endpoint 4: Get Bond Registry

**GET** `/v1/bond_registry`

**Purpose**: Full list of all active bonded pairs (used by trading engine at startup).

**Request**:
```
GET /v1/bond_registry?tier=1&status=active&limit=100&offset=0
```

**Response**:
```json
{
  "bonds": [
    {
      "pair_id": "bond_001",
      "kalshi_market_id": "KALSHI-ABC-123",
      "polymarket_condition_id": "0x1234...",
      "tier": 1,
      "p_match": 0.987,
      "outcome_mapping": {
        "kalshi_yes": "polymarket_token_yes",
        "kalshi_no": "polymarket_token_no"
      },
      "trading_params": {
        "max_notional": 10000,
        "max_position_pct": 0.10
      },
      "created_at": "2025-01-15T10:30:00Z"
    },
    {
      "pair_id": "bond_002",
      "kalshi_market_id": "KALSHI-DEF-456",
      "polymarket_condition_id": "0x5678...",
      "tier": 2,
      "p_match": 0.923,
      "outcome_mapping": {...},
      "trading_params": {
        "max_notional": 2000,
        "max_position_pct": 0.05
      },
      "created_at": "2025-01-16T08:15:00Z"
    }
  ],
  "total": 2,
  "pagination": {
    "limit": 100,
    "offset": 0,
    "has_more": false
  }
}
```

**Implementation Notes**:
- Cached for 60 seconds (low latency required for trading engine)
- Supports pagination for large registries
- Filter by tier, status (active/paused/retired)

---

### Endpoint 5: Recompute Similarities

**POST** `/v1/pairs/recompute`

**Purpose**: Trigger similarity recalculation for all or subset of markets.

**Request**:
```json
{
  "mode": "all | incremental | specific",
  "market_ids": ["KALSHI-ABC-123"],  // Only if mode=specific
  "blocking": false,  // true = wait for completion, false = async
  "force_refresh": true  // Ignore cache, recompute from scratch
}
```

**Response (Async)**:
```json
{
  "job_id": "recompute_job_xyz",
  "status": "queued",
  "estimated_duration_seconds": 120,
  "markets_to_process": 150
}
```

**Response (Blocking)**:
```json
{
  "job_id": "recompute_job_xyz",
  "status": "completed",
  "duration_seconds": 98,
  "results": {
    "processed": 150,
    "new_bonds": 3,
    "updated_bonds": 7,
    "demoted_bonds": 2,
    "failed": 0
  }
}
```

**Implementation Notes**:
- Use background worker queue (Celery, RQ, etc.)
- Priority queue: specific > incremental > all
- Auto-trigger incremental recompute every 1 hour
- Manual trigger for emergency recalibration

---

### Endpoint 6: Health Check

**GET** `/v1/health`

**Purpose**: Service health and readiness check.

**Request**: None

**Response**:
```json
{
  "status": "healthy | degraded | unhealthy",
  "timestamp": "2025-01-20T15:45:00Z",
  "components": {
    "database": {
      "status": "healthy",
      "latency_ms": 12
    },
    "kalshi_api": {
      "status": "healthy",
      "last_poll": "2025-01-20T15:44:30Z",
      "rate_limit_remaining": 87
    },
    "polymarket_api": {
      "status": "degraded",
      "last_poll": "2025-01-20T15:43:00Z",
      "error": "Rate limited",
      "rate_limit_remaining": 0
    },
    "embedding_service": {
      "status": "healthy",
      "model_loaded": true
    }
  },
  "metrics": {
    "total_markets_kalshi": 1234,
    "total_markets_polymarket": 987,
    "total_bonds_tier1": 45,
    "total_bonds_tier2": 23,
    "avg_similarity_calc_ms": 18
  }
}
```

**Implementation Notes**:
- Call before starting trading engine
- Alert if status != "healthy"
- Include dependency health (database, APIs, ML model)

---

## 8. MVP Non-Functional Requirements

### Performance Targets

#### Latency

| Operation | Target Latency | Max Acceptable |
|-----------|----------------|----------------|
| Single pair similarity calc | <20ms | 50ms |
| Candidate generation (per market) | <100ms | 250ms |
| Full bond registry fetch | <50ms | 100ms |
| Market ingestion (batch of 10) | <500ms | 1s |
| Embedding generation (per market) | <50ms | 100ms |

**Critical Path**: Trading engine queries `/bond_registry` every 10s → must be <100ms.

#### Throughput

- **Market ingestion**: 100 markets/minute sustained
- **Similarity calculations**: 500 pairs/minute (recompute jobs)
- **API requests**: 100 req/min per client (trading engine, monitoring tools)

---

### Persistence Layer

#### Database Choice: PostgreSQL + JSONB

**Rationale**:
- Structured data (markets, bonds) + semi-structured (feature breakdowns)
- ACID guarantees for critical bond registry updates
- Indexing on time ranges, categories, entities
- Full-text search for descriptions

**Schema**:

**Table: `markets`**
```sql
CREATE TABLE markets (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    condition_id TEXT,
    status TEXT NOT NULL,
    raw_title TEXT,
    raw_description TEXT,
    clean_title TEXT,
    clean_description TEXT,
    category TEXT,
    event_type TEXT,
    entities JSONB,
    geo_scope TEXT,
    time_window JSONB,
    resolution_source TEXT,
    outcome_schema JSONB,
    text_embedding vector(384),  -- pgvector extension
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_markets_platform ON markets(platform);
CREATE INDEX idx_markets_category ON markets(category);
CREATE INDEX idx_markets_resolution_date ON markets((time_window->>'resolution_date'));
CREATE INDEX idx_markets_embedding ON markets USING ivfflat (text_embedding vector_cosine_ops);
```

**Table: `bonds`**
```sql
CREATE TABLE bonds (
    pair_id TEXT PRIMARY KEY,
    kalshi_market_id TEXT REFERENCES markets(id),
    polymarket_market_id TEXT REFERENCES markets(id),
    tier INTEGER NOT NULL CHECK (tier IN (1, 2, 3)),
    p_match FLOAT NOT NULL,
    similarity_score FLOAT NOT NULL,
    outcome_mapping JSONB NOT NULL,
    feature_breakdown JSONB NOT NULL,
    status TEXT DEFAULT 'active',  -- active | paused | retired
    created_at TIMESTAMP DEFAULT NOW(),
    last_validated TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_bonds_tier ON bonds(tier) WHERE status = 'active';
CREATE INDEX idx_bonds_kalshi ON bonds(kalshi_market_id);
CREATE INDEX idx_bonds_poly ON bonds(polymarket_market_id);
```

**Cache Layer**: Redis for:
- Candidate lists (TTL 10 min)
- Bond registry (TTL 60s)
- API rate limit counters

---

### Logging and Audit Trails

#### Structured Logging (JSON format)

**Log Levels**:
- **DEBUG**: Feature scores, embedding similarities
- **INFO**: Market ingestion, bond creation/updates
- **WARNING**: Tier demotion, API rate limits
- **ERROR**: Failed similarity calculations, API errors
- **CRITICAL**: Bond validation failures, data corruption

**Required Fields**:
```json
{
  "timestamp": "2025-01-20T15:45:00Z",
  "level": "INFO",
  "service": "bonding_agent",
  "operation": "create_bond",
  "pair_id": "bond_abc123",
  "tier": 1,
  "p_match": 0.987,
  "markets": {
    "kalshi": "KALSHI-ABC-123",
    "polymarket": "poly_cond_xyz789"
  },
  "feature_breakdown": {...},
  "trace_id": "trace_xyz"
}
```

#### Audit Trail

**Track all state changes**:
- Market ingestion (raw → normalized)
- Bond creation (candidate → Tier 1/2/3)
- Bond updates (tier changes, validation timestamps)
- Manual overrides (admin demotes bond to Tier 3)

**Retention**: 90 days in hot storage, 1 year in cold storage

---

### Safe Degradation Under Rate Limits

#### Strategy

1. **Detect Rate Limit**:
   - Monitor 429 responses from Kalshi/Polymarket
   - Track request counters internally

2. **Graceful Degradation**:
   - **Priority 1**: Keep bond registry fresh (critical for trading)
   - **Priority 2**: Ingest new markets (miss some is OK)
   - **Priority 3**: Recompute similarities (use stale data temporarily)

3. **Actions**:
   - Switch to cached data (extend TTL from 60s to 5 min)
   - Reduce polling frequency (60s → 120s)
   - Drop low-priority recompute jobs
   - Alert monitoring system

4. **Recovery**:
   - Resume normal polling when rate limit resets
   - Backfill missed markets in next cycle

---

### Versioning

#### Normalization Schema Versioning

- **Field**: `metadata.ingestion_version` (e.g., "v1.0.0")
- **Migration Strategy**:
  - Breaking changes → new version (v2.0.0)
  - Add `migration_v1_to_v2()` function
  - Recompute all bonds after schema change
  - Support dual-version read during transition (1 week)

#### API Versioning

- **Path prefix**: `/v1/`, `/v2/`
- **Deprecation Policy**:
  - Announce 30 days before deprecation
  - Support old version for 90 days
  - Return `Deprecated: true` header in responses

---

## 9. Implementation Checklist

### Phase 1: Core Infrastructure (Week 1)
- [ ] PostgreSQL schema + pgvector setup
- [ ] Redis cache layer
- [ ] API framework (FastAPI/Flask)
- [ ] Auth middleware (API key validation)
- [ ] Health check endpoint

### Phase 2: Ingestion Pipeline (Week 2)
- [ ] Kalshi client (market listing, metadata)
- [ ] Polymarket client (Gamma API, CLOB API)
- [ ] Normalization pipeline (text cleaning, NER, embedding)
- [ ] `/markets/ingest` endpoint
- [ ] Scheduled polling jobs

### Phase 3: Similarity Engine (Week 3)
- [ ] Feature calculators (text, entity, time, outcome, resolution)
- [ ] Hard constraint checker
- [ ] Weighted score aggregator
- [ ] Logistic calibration (manual labeling of 100 pairs)
- [ ] Candidate generation (fast filters)

### Phase 4: Bonding API (Week 4)
- [ ] `/markets/{platform}/{id}/candidates` endpoint
- [ ] `/pairs/{platform}/{id}` endpoint
- [ ] `/bond_registry` endpoint
- [ ] `/pairs/recompute` endpoint
- [ ] Background recompute job (Celery/RQ)

### Phase 5: Validation & Monitoring (Week 5)
- [ ] Structured logging
- [ ] Audit trail
- [ ] Rate limit handling
- [ ] Tier demotion alerts
- [ ] Weekly bond accuracy report

### Phase 6: Testing & Launch (Week 6)
- [ ] Unit tests (feature calculators)
- [ ] Integration tests (end-to-end bonding flow)
- [ ] Load testing (500 pairs/min)
- [ ] Shadow mode (compute bonds, don't trade)
- [ ] Production launch (Tier 1 only, manual review Tier 2)

---

## 10. Example Bonding Flow (End-to-End)

### Scenario: New Kalshi Market Detected

**1. Ingestion**
```
Kalshi API → POST /v1/markets/ingest
   ↓
Normalize: Extract entities, embed text, parse outcome schema
   ↓
Store in DB: markets table
```

**2. Candidate Generation**
```
Trigger: New market ingested
   ↓
Fast filters:
  - Category: "crypto"
  - Time: resolution_date ± 7 days
  - Entity: ticker="BTC"
  - Embedding similarity ≥ 0.5
   ↓
Find 3 Polymarket candidates
   ↓
Cache in Redis (10 min TTL)
```

**3. Similarity Calculation (for each candidate)**
```
Compute features:
  - Text: 0.87
  - Entity: 0.92
  - Time: 0.95
  - Outcome: 1.0
  - Resolution: 1.0
   ↓
Weighted score S = 0.91
   ↓
Logistic model p_match = 0.987
   ↓
Tier assignment: p_match ≥ 0.98 → Tier 1
```

**4. Bond Creation**
```
Insert into bonds table:
  - pair_id: bond_abc123
  - tier: 1
  - p_match: 0.987
  - outcome_mapping: {kalshi_yes → poly_token_yes, ...}
   ↓
Invalidate bond_registry cache
   ↓
Log: INFO "New Tier 1 bond created"
```

**5. Trading Engine Consumption**
```
Every 10s: GET /v1/bond_registry?tier=1
   ↓
Fetch active Tier 1 bonds
   ↓
For each bond:
  - Fetch prices from Kalshi CLOB
  - Fetch prices from Polymarket CLOB
  - Compute arbitrage spread
  - If spread > threshold → execute trade
```

---

## 11. Risk Mitigation

### False Positive Safeguards

1. **Human-in-the-Loop (Tier 2)**:
   - Daily review of all Tier 2 bonds
   - Manual promotion to Tier 1 if validated
   - Quick rejection if suspicious

2. **Confidence Decay**:
   - Lower `p_match` by 1% per week for unvalidated bonds
   - Force recomputation every 7 days

3. **Post-Resolution Validation**:
   - After both markets settle, verify outcomes match
   - If mismatch detected:
     - Pause all bonds with similar features
     - Root cause analysis
     - Model retraining

4. **Tier 1 Guardrails**:
   - Limit total Tier 1 bonds to 50 initially
   - Graduate slowly: Add max 5 new Tier 1/week
   - Manual override: Admin can demote any bond instantly

### Monitoring Alerts

- **Critical**: Any Tier 1 bond outcome mismatch → Page on-call engineer
- **High**: Tier 2 mismatch rate >5% → Daily review required
- **Medium**: API rate limit hit → Reduce polling frequency
- **Low**: Candidate generation returns 0 results → Check data freshness

---

## End of System Design

This completes the Market Bonding Agent MVP specification. All components are production-ready for real-money HFT usage with appropriate safeguards.
