# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Bonding_Bot** is a market bonding agent that determines whether a Kalshi market and a Polymarket market represent the same underlying economic event for safe cross-exchange arbitrage trading. The system computes similarity scores, match probabilities, and assigns tier classifications (Tier 1 = Auto Bond, Tier 2 = Cautious Bond, Tier 3 = Reject).

**Critical Safety Principle**: This is a production system for real-money HFT usage. Optimize for **precision over recall** — false positives (incorrect bonds) are catastrophic, while false negatives (missed opportunities) are acceptable.

## Core Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Bonding Agent System                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │   Kalshi     │         │  Polymarket  │                 │
│  │   Client     │         │   Client     │                 │
│  │              │         │ (Gamma/CLOB) │                 │
│  └──────┬───────┘         └──────┬───────┘                 │
│         │                        │                          │
│         └────────┬───────────────┘                          │
│                  ▼                                          │
│         ┌─────────────────┐                                 │
│         │   Ingestion     │                                 │
│         │   Pipeline      │                                 │
│         │ (Normalization) │                                 │
│         └────────┬────────┘                                 │
│                  ▼                                          │
│         ┌─────────────────┐                                 │
│         │  Candidate      │                                 │
│         │  Generation     │                                 │
│         │ (Fast Filters)  │                                 │
│         └────────┬────────┘                                 │
│                  ▼                                          │
│         ┌─────────────────┐                                 │
│         │  Similarity     │                                 │
│         │  Calculator     │                                 │
│         │ (ML Features)   │                                 │
│         └────────┬────────┘                                 │
│                  ▼                                          │
│         ┌─────────────────┐                                 │
│         │  Tier           │                                 │
│         │  Assignment     │                                 │
│         └────────┬────────┘                                 │
│                  ▼                                          │
│         ┌─────────────────┐                                 │
│         │  REST API       │                                 │
│         │  (Bond Service) │                                 │
│         └─────────────────┘                                 │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Ingestion**: Poll Kalshi/Polymarket APIs every 60s for new markets
2. **Normalization**: Clean text, extract entities (NER), generate embeddings, parse outcome schemas
3. **Candidate Generation**: Fast filters reduce O(N×M) to O(N×20) candidates per market
4. **Similarity Calculation**: Compute feature scores (text, entity, time, outcome, resolution)
5. **Tier Assignment**: Logistic model outputs p_match → Tier 1/2/3
6. **API Exposure**: Trading engine queries `/bond_registry` every 10s

### Technology Stack (Expected)

- **Language**: Python 3.10+
- **API Framework**: FastAPI
- **Database**: PostgreSQL with pgvector extension
- **Cache**: Redis
- **ML/NLP**:
  - `sentence-transformers` (all-MiniLM-L6-v2 for embeddings)
  - `spaCy` (NER for entity extraction)
- **Task Queue**: Celery or RQ (background similarity recomputation)
- **Testing**: pytest
- **Deployment**: Docker + docker-compose

## Development Commands

### Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install spaCy model for NER
python3 -m spacy download en_core_web_sm

# Start local services (PostgreSQL + Redis)
docker-compose up -d

# Run database migrations
alembic upgrade head

# Download embedding model (first run)
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### Running the Service

```bash
# Start API server (development)
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Start background worker (similarity recomputation)
celery -A src.workers.tasks worker --loglevel=info

# Start ingestion poller (Kalshi + Polymarket)
python3 src/ingestion/poller.py
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_similarity_calculator.py

# Run specific test
pytest tests/test_similarity_calculator.py::test_yes_no_polarity_match -v

# Run integration tests (requires docker-compose services)
pytest tests/integration/ --integration
```

### Database Operations

```bash
# Create new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Reset database (CAUTION: destroys all data)
alembic downgrade base && alembic upgrade head
```

### Calibration and Model Training

```bash
# Export labeled dataset for calibration
python3 scripts/export_labeled_pairs.py --output labeled_pairs.csv

# Train logistic regression model
python3 scripts/train_similarity_model.py --input labeled_pairs.csv --output models/similarity_v1.pkl

# Validate model performance
python3 scripts/validate_model.py --model models/similarity_v1.pkl --test labeled_pairs_test.csv
```

### Monitoring and Debugging

```bash
# Check API health
curl http://localhost:8000/v1/health | jq

# View bond registry
curl http://localhost:8000/v1/bond_registry?tier=1 | jq

# Trigger manual recomputation
curl -X POST http://localhost:8000/v1/pairs/recompute \
  -H "X-API-Key: your-key" \
  -d '{"mode": "all", "blocking": false}' | jq

# View logs (structured JSON)
tail -f logs/bonding_agent.log | jq

# Monitor Celery tasks
celery -A src.workers.tasks inspect active
```

## Key Design Principles

### 1. Normalized Market Schema

All markets (Kalshi + Polymarket) are converted to a unified internal schema with:
- `clean_title`, `clean_description`: Normalized text (lowercased, stripped)
- `entities`: Extracted tickers, people, organizations, countries
- `time_window`: Observation period + resolution date
- `outcome_schema`: Unified representation (yes/no, brackets, scalar)
- `text_embedding`: 384-dim vector from sentence-transformers

**Location**: Schema defined in `src/models/market.py` (expected)

### 2. Similarity Features

Five primary feature categories:
- **Text Similarity** (weight 0.35): Embedding cosine similarity on title+description
- **Entity Similarity** (weight 0.25): Jaccard similarity + exact match bonuses
- **Time Alignment** (weight 0.15): Resolution date difference scoring
- **Outcome Structure** (weight 0.20): Polarity/bracket/unit compatibility
- **Resolution Source** (weight 0.05): Authority matching (BLS, FOMC, etc.)

**Location**: Feature calculators in `src/similarity/` (expected)

### 3. Hard Constraints (Auto-Reject)

Immediately reject pairs if ANY of:
- Polarity mismatch (yes/no markets with opposite meaning)
- Unit mismatch (dollars vs percent in bracket markets)
- Time skew >14 days
- Text similarity <0.60
- Entity Jaccard <0.2 with no exact ticker/person match
- Outcome incompatibility (cannot map outcomes)

**Location**: Hard constraint checker in `src/similarity/constraints.py` (expected)

### 4. Tier Thresholds

| Tier | p_match Range | Requirements | Trading Size |
|------|---------------|--------------|--------------|
| 1 | ≥0.98 | All features ≥0.85-0.95 | 100% |
| 2 | 0.90-0.98 | Relaxed thresholds | 10-25% |
| 3 | <0.90 | Reject | 0% |

**Location**: Tier assignment logic in `src/similarity/tier_assigner.py` (expected)

## REST API Endpoints

### Core Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v1/markets/ingest` | Batch ingest raw markets from platforms |
| GET | `/v1/markets/{platform}/{id}/candidates` | Get cross-platform candidates for bonding |
| GET | `/v1/pairs/{platform}/{id}` | Get bonded pairs for specific market |
| GET | `/v1/bond_registry` | Full list of active bonds (used by trading engine) |
| POST | `/v1/pairs/recompute` | Trigger similarity recalculation |
| GET | `/v1/health` | Health check + dependency status |

**Location**: API routes in `src/api/routes/` (expected)

### Authentication

Internal service-to-service auth via `X-API-Key` header.

**Location**: Auth middleware in `src/api/middleware/auth.py` (expected)

## Configuration

### Environment Variables

**Required**:
```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/bonding_agent
REDIS_URL=redis://localhost:6379/0

# API Keys (internal)
BONDING_API_KEY=your-internal-key

# External APIs
KALSHI_API_BASE=https://api.kalshi.com/v1  # (placeholder)
POLYMARKET_GAMMA_API_BASE=https://gamma-api.polymarket.com
POLYMARKET_CLOB_API_BASE=https://clob.polymarket.com

# ML Models
EMBEDDING_MODEL=all-MiniLM-L6-v2
SPACY_MODEL=en_core_web_sm

# Performance
CANDIDATE_LIMIT=20                # Max candidates per market
SIMILARITY_CALC_TIMEOUT_MS=50     # Per-pair timeout
BOND_REGISTRY_CACHE_TTL_SEC=60    # Cache lifetime
```

**Optional**:
```bash
# Feature Weights (for manual tuning)
WEIGHT_TEXT=0.35
WEIGHT_ENTITY=0.25
WEIGHT_TIME=0.15
WEIGHT_OUTCOME=0.20
WEIGHT_RESOLUTION=0.05

# Tier Thresholds
TIER1_P_MATCH_THRESHOLD=0.98
TIER2_P_MATCH_THRESHOLD=0.90

# Polling Intervals
KALSHI_POLL_INTERVAL_SEC=60
POLYMARKET_POLL_INTERVAL_SEC=60
```

**Location**: Configuration loaded from `src/config.py` using `pydantic.BaseSettings` (expected)

## Database Schema

### Key Tables

**`markets`**: Normalized market data
- Primary key: `id` (platform-specific ID)
- Indexed on: `platform`, `category`, `resolution_date`, `text_embedding` (pgvector)
- JSONB fields: `entities`, `time_window`, `outcome_schema`, `metadata`

**`bonds`**: Bonded market pairs
- Primary key: `pair_id`
- Foreign keys: `kalshi_market_id`, `polymarket_market_id`
- Indexed on: `tier`, `status`, both market IDs
- JSONB fields: `outcome_mapping`, `feature_breakdown`

**Location**: Schema migrations in `alembic/versions/` (expected)

### pgvector Extension

Used for fast embedding similarity search:
```sql
CREATE EXTENSION vector;
CREATE INDEX idx_markets_embedding ON markets USING ivfflat (text_embedding vector_cosine_ops);
```

Query example:
```sql
SELECT id, 1 - (text_embedding <=> '[0.1, 0.2, ...]') AS similarity
FROM markets
WHERE platform = 'polymarket'
ORDER BY text_embedding <=> '[0.1, 0.2, ...]'
LIMIT 50;
```

## Critical Safety Rules

### When Implementing Features

1. **Never Auto-Promote to Tier 1**: Human review or strong validation required
2. **Fail Closed**: If similarity calculation errors, default to Tier 3 (reject)
3. **Log All Bond State Changes**: Audit trail for tier promotions/demotions
4. **Validate Outcome Mappings**: Ensure 1:1 mapping between outcomes (no ambiguity)
5. **Time Skew Hard Limit**: Never bond markets >14 days apart

### When Modifying Similarity Logic

1. **Test on Labeled Dataset**: Run `pytest tests/test_similarity_labeled.py` with 100+ labeled pairs
2. **Check Precision**: Tier 1 false positive rate must be <0.5%
3. **Update SYSTEM_DESIGN.md**: Document weight/threshold changes
4. **Version Schema**: Increment `metadata.ingestion_version` if normalization changes
5. **Recompute Existing Bonds**: Run `POST /v1/pairs/recompute` with `force_refresh=true`

### When Adding External API Calls

1. **Rate Limit Handling**: Implement exponential backoff on 429 responses
2. **Graceful Degradation**: Use cached data if API unavailable
3. **Timeout Enforcement**: All external calls must have <5s timeout
4. **Error Logging**: Log all API errors with request context
5. **Health Check Integration**: Update `/v1/health` to monitor new dependency

## Common Development Patterns

### Adding a New Similarity Feature

1. **Define Feature Calculator**: Create `src/similarity/features/new_feature.py`
   ```python
   def calculate_new_feature(market_k: Market, market_p: Market) -> float:
       """Returns score in [0, 1]"""
       # Implementation
       return score
   ```

2. **Add to Feature Vector**: Update `src/similarity/aggregator.py`
   ```python
   features = [
       score_text,
       score_entity,
       # ...
       score_new_feature,  # Add here
   ]
   weights = [0.30, 0.20, ..., 0.05]  # Adjust weights (must sum to 1.0)
   ```

3. **Retrain Model**: Update logistic regression with new feature
   ```bash
   python3 scripts/train_similarity_model.py --input labeled_pairs.csv
   ```

4. **Test**: Add tests in `tests/test_similarity_features.py`

5. **Document**: Update `SYSTEM_DESIGN.md` Section 5 with new feature

### Adding a New Market Category

1. **Update Category Mapping**: Edit `src/normalization/categories.py`
   ```python
   CATEGORY_MAPPINGS = {
       "new_category": ["kalshi_cat", "polymarket_tag"],
       # ...
   }
   ```

2. **Adjust Time Thresholds**: If category has special time requirements
   ```python
   TIME_THRESHOLDS = {
       "new_category": 7,  # days
       # ...
   }
   ```

3. **Update Entity Extraction**: Add category-specific entity patterns
   ```python
   # In src/normalization/entity_extractor.py
   if market.category == "new_category":
       entities.extend(extract_custom_entities(text))
   ```

### Debugging a Bond Mismatch

If a Tier 1/2 bond resolves incorrectly:

1. **Fetch Bond Details**:
   ```bash
   curl http://localhost:8000/v1/pairs/kalshi/MARKET_ID | jq '.bonds[0]'
   ```

2. **Review Feature Breakdown**:
   ```json
   {
     "feature_breakdown": {
       "text_similarity": 0.87,
       "entity_similarity": 0.92,
       "time_alignment": 0.95,
       "outcome_similarity": 1.0,  // Check if this was correct
       "resolution_similarity": 1.0
     }
   }
   ```

3. **Check Raw Market Data**:
   ```sql
   SELECT raw_title, raw_description, outcome_schema
   FROM markets WHERE id IN ('kalshi_id', 'poly_id');
   ```

4. **Analyze Root Cause**:
   - Polarity mismatch? → Update polarity detection
   - Outcome mapping error? → Fix outcome parser
   - Resolution source mismatch? → Improve source normalization

5. **Add to Test Suite**:
   ```python
   # In tests/test_similarity_labeled.py
   def test_bond_mismatch_case_xyz():
       """Regression test for bond mismatch discovered on 2025-XX-XX"""
       # ...
   ```

6. **Demote Similar Bonds**:
   ```bash
   # Manual SQL or API call to demote bonds with similar features
   ```

## Monitoring and Alerts

### Key Metrics to Track

- **Bond Accuracy**: % of resolved bonds where outcomes matched
- **Tier Distribution**: Count of Tier 1 / Tier 2 / Tier 3 bonds
- **API Latency**: p50, p95, p99 for each endpoint
- **Ingestion Rate**: Markets/minute from each platform
- **Cache Hit Rate**: Redis cache effectiveness
- **Feature Scores**: Distribution of similarity scores

### Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Tier 1 mismatch | Any occurrence | — |
| Tier 2 mismatch rate | >3% | >5% |
| API latency (p99) | >200ms | >500ms |
| API error rate | >1% | >5% |
| Ingestion lag | >5 min | >15 min |
| Cache hit rate | <70% | <50% |

**Location**: Monitoring setup in `src/monitoring/` and `docker-compose.yml` with Prometheus/Grafana (expected)

## Testing Strategy

### Unit Tests
- All similarity feature calculators
- Entity extraction
- Outcome schema parsing
- Tier assignment logic

### Integration Tests
- Full ingestion pipeline (mock APIs)
- Candidate generation
- End-to-end bonding flow
- Database operations

### Validation Tests
- Labeled dataset (100+ pairs)
- Precision/recall metrics
- Edge cases (polarity inversions, bracket overlaps)

### Load Tests
- 500 pairs/minute similarity calculation
- 100 req/min API throughput
- Database query performance

**Location**: Tests in `tests/` with subdirectories per type

## Deployment

### Production Checklist

- [ ] Environment variables configured (see Configuration section)
- [ ] PostgreSQL with pgvector extension installed
- [ ] Redis running and accessible
- [ ] Embedding model downloaded (`all-MiniLM-L6-v2`)
- [ ] spaCy model downloaded (`en_core_web_sm`)
- [ ] Database migrations applied (`alembic upgrade head`)
- [ ] Logistic regression model trained and deployed
- [ ] API authentication keys rotated
- [ ] Monitoring/alerting configured
- [ ] Health check endpoint returns "healthy"
- [ ] Rate limit handling tested against live APIs
- [ ] Backup/restore procedures documented

### Scaling Considerations

- **Horizontal Scaling**: API servers are stateless (scale via load balancer)
- **Database**: Use read replicas for `/bond_registry` queries
- **Cache**: Redis cluster for high availability
- **Workers**: Scale Celery workers based on recompute queue depth
- **Embedding Service**: GPU acceleration for batch embedding generation

## Related Documentation

- **SYSTEM_DESIGN.md**: Complete technical specification
- **API_DOCS.md**: OpenAPI/Swagger documentation (auto-generated)
- **CALIBRATION.md**: Guide for labeling pairs and training models (expected)
- **RUNBOOK.md**: Operational procedures for incidents (expected)

## External API References

- Kalshi API: Internal integration documentation
- Polymarket Gamma API: `https://gamma-api.polymarket.com` (see Polymarket integration docs)
- Polymarket CLOB API: `https://clob.polymarket.com` (see Polymarket integration docs)

## Version History

- **v1.0.0** (2025-01-XX): Initial MVP release
  - 5 similarity features
  - 3-tier system
  - Kalshi + Polymarket support
  - Logistic regression model
