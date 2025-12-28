# Bonding Bot - Market Bonding Agent

Cross-exchange arbitrage bonding system for Kalshi and Polymarket prediction markets.

## Overview

**Bonding Bot** automatically determines whether markets on Kalshi and Polymarket represent the same underlying economic event, enabling safe cross-exchange arbitrage trading.

**Key Features**:
- 🎯 **High Precision**: 99.5%+ accuracy for Tier 1 bonds (production HFT-ready)
- 🤖 **ML-Powered**: Sentence embeddings + logistic regression for similarity scoring
- ⚡ **Low Latency**: <50ms per-pair similarity calculation
- 🔒 **Safety First**: Multi-tier system with hard constraints to prevent false positives
- 📊 **REST API**: Clean internal API for trading engine integration
- 🏷️ **Event Classification**: Intelligent categorization across 10+ event types

**Production Enhancements** (NEW):
- 🔌 **Real APIs**: Full Kalshi & Polymarket integration (public APIs)
- 🧠 **Complete ML Pipeline**: spaCy NER + sentence-transformers + event classifier
- ⚡ **Redis Caching**: Sub-ms lookups for bond registry
- 📈 **Metrics & Monitoring**: Counters, gauges, histograms with percentiles
- ✅ **Auto-Validation**: Post-resolution bond accuracy tracking
- 🔄 **Auto-Ingestion**: Continuous polling from both platforms (60s intervals)

**📖 See [ENHANCEMENTS.md](ENHANCEMENTS.md) for full feature list**

---

## Table of Contents

1. [Event Classification System](#event-classification-system)
2. [Quick Start](#quick-start)
3. [Detailed Setup](#detailed-setup)
4. [Production Deployment](#production-deployment)
5. [Architecture](#architecture)
6. [API Reference](#api-reference)
7. [Development](#development)
8. [Monitoring](#monitoring)

---

## Event Classification System

The bonding agent intelligently classifies markets into **10 event types** to prevent cross-category mismatches (e.g., sports markets bonding with political markets):

### Supported Event Types

| Event Type | Examples | Keywords |
|------------|----------|----------|
| **Sports** | NFL/NBA/NHL/MLB games, player props, team outcomes | touchdown, yards, rebounds, assists, goals, quarterback, teams |
| **Entertainment** | Oscar nominations, box office results, streaming rankings | oscars, emmy, grammy, best actor, box office, rotten tomatoes |
| **Election** | Presidential races, senate seats, governor elections | election, president, senate, vote, ballot, campaign, primary |
| **Regulatory** | Legal proceedings, court rulings, SEC actions | arrested, indicted, lawsuit, trial, verdict, court, ban |
| **Price Target** | Crypto/stock price predictions | bitcoin, eth, price, reach, trading at, market cap |
| **Rate Decision** | Federal Reserve rate changes, monetary policy | fed, fomc, interest rate, basis points, hike, cut |
| **Economic Indicator** | GDP, inflation, unemployment reports | gdp, inflation, cpi, unemployment, jobs, retail sales |
| **Geopolitical** | Wars, conflicts, international treaties | war, conflict, invasion, sanctions, military, nuclear |
| **Corporate** | Earnings reports, mergers, IPOs | earnings, revenue, acquisition, merger, ceo, ipo, dividend |
| **General** | Catch-all for uncategorized markets | (default fallback) |

### How Event Classification Works

1. **Keyword Matching**: Each event type has a curated list of keywords with singular/plural forms
2. **Boost Multipliers**: Higher-priority types (sports=5, entertainment=3) override lower-priority types
3. **Exclusion Rules**: Sports excludes awards keywords, preventing "Best NFL Player" from being classified as entertainment
4. **Hard Constraints**: Markets with mismatched event types are automatically rejected from bonding

**Example**: A market titled "Patrick Mahomes 200+ yards" is classified as **sports** (score=15) due to keywords "yards" and player name, preventing it from bonding with an entertainment market about "Mahomes documentary Oscar nomination".

---

## Quick Start

### Prerequisites

- **Python 3.10+**
- **Docker & Docker Compose**
- **PostgreSQL 14+** with pgvector extension
- **Redis 6+**

### Installation

```bash
# Clone repository
git clone https://github.com/your-username/Bonding_Bot.git
cd Bonding_Bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Download ML models
python3 -m spacy download en_core_web_sm
python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

### Environment Setup

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
# Edit .env with your configuration (see Configuration section below)
```

### Start Services

```bash
# Start PostgreSQL + Redis
docker-compose up -d postgres redis

# Run database migrations
alembic upgrade head

# Start API server
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# In separate terminals, start background workers:
# Terminal 2: Market poller
python3 src/ingestion/poller.py

# Terminal 3: Price updater
python3 src/ingestion/price_updater.py
```

### Verify Installation

```bash
# Health check
curl http://localhost:8000/v1/health | jq

# Check bond registry
curl http://localhost:8000/v1/bond_registry?limit=10 | jq
```

---

## Detailed Setup

### 1. Database Configuration

**PostgreSQL with pgvector**:

```bash
# Start PostgreSQL container
docker-compose up -d postgres

# Install pgvector extension
docker exec bonding_postgres psql -U bonding_user -d bonding_agent -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Verify extension
docker exec bonding_postgres psql -U bonding_user -d bonding_agent -c "SELECT * FROM pg_extension WHERE extname = 'vector';"
```

**Run Migrations**:

```bash
# Apply all migrations
alembic upgrade head

# Create new migration (if schema changes)
alembic revision --autogenerate -m "Description of changes"

# Rollback one migration
alembic downgrade -1
```

**Optional: Upgrade to HNSW Index** (for faster vector search):

```bash
alembic upgrade 002  # Applies HNSW index migration
```

### 2. Redis Configuration

```bash
# Start Redis container
docker-compose up -d redis

# Verify connection
docker exec bonding_redis redis-cli ping  # Should return "PONG"

# Monitor cache activity
docker exec bonding_redis redis-cli MONITOR
```

### 3. External API Configuration

**Kalshi API**:
- Public API base: `https://api.elections.kalshi.com/trade-api/v2`
- No API key required for public market data
- Optional: Add `KALSHI_API_KEY` for authenticated endpoints

**Polymarket API**:
- Gamma API: `https://gamma-api.polymarket.com` (market discovery)
- CLOB API: `https://clob.polymarket.com` (prices and order books)
- No API key required for public endpoints

### 4. ML Model Setup

**spaCy NER Model**:

```bash
# Download English model
python3 -m spacy download en_core_web_sm

# Verify installation
python3 -c "import spacy; nlp = spacy.load('en_core_web_sm'); print('spaCy loaded successfully')"
```

**Sentence Transformers**:

```bash
# Download embedding model (first run only)
python3 -c "from sentence_transformers import SentenceTransformer; model = SentenceTransformer('all-MiniLM-L6-v2'); print('Model downloaded successfully')"
```

### 5. Configuration

**Environment Variables** (`.env` file):

```bash
# Database
DATABASE_URL=postgresql://bonding_user:bonding_pass@localhost:5432/bonding_agent

# Redis
REDIS_URL=redis://localhost:6379/0

# Internal API Authentication
BONDING_API_KEY=your-secure-random-key-here  # Generate with: openssl rand -hex 32

# External APIs (public endpoints - no keys needed for read-only access)
KALSHI_API_BASE=https://api.elections.kalshi.com/trade-api/v2
POLYMARKET_GAMMA_API_BASE=https://gamma-api.polymarket.com
POLYMARKET_CLOB_API_BASE=https://clob.polymarket.com

# ML Models
EMBEDDING_MODEL=all-MiniLM-L6-v2
SPACY_MODEL=en_core_web_sm

# Performance Tuning
CANDIDATE_LIMIT=50                 # Max candidates per similarity calculation
SIMILARITY_CALC_TIMEOUT_MS=50      # Timeout per pair calculation
BOND_REGISTRY_CACHE_TTL_SEC=60     # Cache lifetime for bond registry
API_RATE_LIMIT_PER_MIN=100         # Rate limit per client

# Polling Intervals
KALSHI_POLL_INTERVAL_SEC=60        # How often to fetch Kalshi markets
POLYMARKET_POLL_INTERVAL_SEC=60    # How often to fetch Polymarket markets

# Feature Weights (must sum to 1.0)
WEIGHT_TEXT=0.35
WEIGHT_ENTITY=0.25
WEIGHT_TIME=0.15
WEIGHT_OUTCOME=0.20
WEIGHT_RESOLUTION=0.05

# Tier Thresholds
TIER1_P_MATCH_THRESHOLD=0.85       # Auto bond threshold
TIER2_P_MATCH_THRESHOLD=0.75       # Cautious bond threshold

# Tier 1 Additional Requirements
TIER1_MIN_TEXT_SCORE=0.75
TIER1_MIN_OUTCOME_SCORE=0.90
TIER1_MIN_TIME_SCORE=0.01
TIER1_MIN_RESOLUTION_SCORE=0.20

# Hard Constraints (auto-reject)
HARD_CONSTRAINT_MIN_TEXT_SCORE=0.50
HARD_CONSTRAINT_MIN_ENTITY_SCORE=0.0
HARD_CONSTRAINT_MAX_TIME_DELTA_DAYS=150

# Logging
LOG_LEVEL=INFO                     # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FORMAT=json                    # json or text

# Environment
ENVIRONMENT=development            # development, staging, production
```

**Generate Secure API Key**:

```bash
# Generate random 32-byte hex key
openssl rand -hex 32
# Example output: dYKqbUF11NMikvHDtjcQl1icIR4teUtm1ve9ITA+bilrJdbXTA2C9MphwhZPev1u
```

---

## Production Deployment

### Docker Compose Production Setup

**Directory Structure**:

```
/opt/bonding_bot/
├── deploy/
│   ├── docker-compose.production.yml
│   ├── .env                        # Production environment variables
│   └── nginx.conf                  # Optional: reverse proxy config
├── logs/
│   └── bonding_agent.log
└── backups/
    └── postgres/
```

**Production Docker Compose** (`deploy/docker-compose.production.yml`):

```yaml
version: '3.8'

services:
  postgres:
    image: pgvector/pgvector:pg14
    container_name: bonding_postgres
    environment:
      POSTGRES_USER: bonding_user
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}  # Set in .env
      POSTGRES_DB: bonding_agent
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    container_name: bonding_redis
    ports:
      - "6379:6379"
    restart: unless-stopped

  api:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: bonding_api
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - BONDING_API_KEY=${BONDING_API_KEY}
      - ENVIRONMENT=production
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  poller:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: bonding_poller
    command: python3 src/ingestion/poller.py
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

  price_updater:
    build:
      context: ..
      dockerfile: deploy/Dockerfile
    container_name: bonding_price_updater
    command: python3 src/ingestion/price_updater.py
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
    depends_on:
      - postgres
      - redis
    restart: unless-stopped

volumes:
  postgres_data:
```

**Dockerfile** (`deploy/Dockerfile`):

```dockerfile
FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download ML models
RUN python3 -m spacy download en_core_web_sm
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy application code
COPY . .

# Run API server by default
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Deployment Steps

1. **Prepare Server**:

```bash
# SSH into production server
ssh root@your-server-ip

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
apt-get update
apt-get install -y docker-compose-plugin
```

2. **Deploy Application**:

```bash
# Create deployment directory
mkdir -p /opt/bonding_bot/deploy
cd /opt/bonding_bot

# Clone repository
git clone https://github.com/your-username/Bonding_Bot.git .

# Configure production environment
cp .env.example deploy/.env
nano deploy/.env  # Edit with production values

# Build and start containers
cd deploy
docker-compose -f docker-compose.production.yml up -d --build

# Apply database migrations
docker exec bonding_api alembic upgrade head

# Verify services
docker-compose -f docker-compose.production.yml ps
```

3. **Verify Deployment**:

```bash
# Check API health
curl http://localhost:8000/v1/health | jq

# Check database connection
docker exec bonding_postgres psql -U bonding_user -d bonding_agent -c "SELECT COUNT(*) FROM markets;"

# Check Redis connection
docker exec bonding_redis redis-cli ping

# View logs
docker logs bonding_api --tail 50 -f
```

### Initial Data Seeding

```bash
# Ingest initial markets from both platforms
docker exec bonding_api python3 scripts/initial_ingestion.py --max-markets 5000

# Run event classification on existing markets
docker exec bonding_api python3 scripts/reclassify_markets.py --batch-size 2000

# Generate initial bonds
docker exec bonding_api python3 scripts/create_bonds.py --max-markets 2000
```

### Production Maintenance

**Update Application**:

```bash
# Pull latest code
cd /opt/bonding_bot
git pull origin master

# Rebuild and restart containers
cd deploy
docker-compose -f docker-compose.production.yml up -d --build

# Run new migrations (if any)
docker exec bonding_api alembic upgrade head
```

**Database Backups**:

```bash
# Backup database
docker exec bonding_postgres pg_dump -U bonding_user bonding_agent > /opt/bonding_bot/backups/postgres/backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from backup
docker exec -i bonding_postgres psql -U bonding_user bonding_agent < /opt/bonding_bot/backups/postgres/backup_20250114_120000.sql
```

**Monitoring Commands**:

```bash
# Monitor API logs
docker logs bonding_api --tail 100 -f

# Monitor poller logs
docker logs bonding_poller --tail 100 -f

# Check bond counts by tier
docker exec bonding_postgres psql -U bonding_user -d bonding_agent -c "SELECT tier, COUNT(*) FROM bonds WHERE status='active' GROUP BY tier;"

# Check event type distribution
docker exec bonding_postgres psql -U bonding_user -d bonding_agent -c "SELECT event_type, COUNT(*) FROM markets GROUP BY event_type ORDER BY COUNT(*) DESC;"
```

---

## Architecture

### System Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Bonding Agent System                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐         ┌──────────────┐                                  │
│  │   Kalshi     │         │  Polymarket  │                                  │
│  │   Client     │         │   Client     │                                  │
│  │ (Public API) │         │ (Gamma/CLOB) │                                  │
│  └──────┬───────┘         └──────┬───────┘                                  │
│         │                        │                                           │
│         └────────┬───────────────┘                                           │
│                  ▼                                                           │
│         ┌─────────────────┐                                                  │
│         │   Ingestion     │  ← Text cleaning & normalization                │
│         │   Pipeline      │  ← NER extraction (spaCy)                       │
│         │  (Poller Worker)│  ← Event classification                         │
│         │                 │  ← Embedding generation (sentence-transformers) │
│         └────────┬────────┘                                                  │
│                  ▼                                                           │
│         ┌─────────────────┐                                                  │
│         │  Price Updater  │  ← Continuous price polling (60s interval)      │
│         │    Worker       │  ← Priority market tracking                     │
│         │                 │  ← Order book fetching                          │
│         └────────┬────────┘                                                  │
│                  ▼                                                           │
│         ┌─────────────────┐                                                  │
│         │  Candidate      │  ← Vector similarity (HNSW index)               │
│         │  Generation     │  ← Fast filters (event type, time range)        │
│         │                 │  ← Top-K retrieval (limit=50)                   │
│         └────────┬────────┘                                                  │
│                  ▼                                                           │
│         ┌─────────────────┐                                                  │
│         │  Similarity     │  ← Text embeddings (cosine similarity)          │
│         │  Calculator     │  ← Entity matching (Jaccard)                    │
│         │                 │  ← Time alignment (date proximity)               │
│         │                 │  ← Outcome compatibility (polarity, structure)   │
│         │                 │  ← Resolution source matching                    │
│         └────────┬────────┘                                                  │
│                  ▼                                                           │
│         ┌─────────────────┐                                                  │
│         │  Tier           │  ← Logistic regression (p_match calculation)    │
│         │  Assignment     │  ← Hard constraints (event type, direction)     │
│         │                 │  ← Dual threshold validation                    │
│         └────────┬────────┘                                                  │
│                  ▼                                                           │
│         ┌─────────────────┐                                                  │
│         │ Arbitrage       │  ← Cross-platform opportunity detection         │
│         │ Monitor Worker  │  ← Intra-platform detection (yes+no < $1)       │
│         │                 │  ← Profit calculation & ranking                  │
│         └────────┬────────┘                                                  │
│                  ▼                                                           │
│         ┌─────────────────┐                                                  │
│         │  REST API       │  ← Redis caching (60s TTL)                      │
│         │  (FastAPI)      │  ← Rate limiting (100 req/min)                  │
│         │                 │  ← Dashboard (HTML/JSON)                         │
│         │                 │  ← Authentication (X-API-Key)                    │
│         └─────────────────┘                                                  │
│                  ▲                                                           │
│         ┌────────┴────────┐                                                  │
│         │                 │                                                  │
│    ┌────▼─────┐   ┌───────▼──────┐                                          │
│    │PostgreSQL│   │    Redis     │                                          │
│    │(pgvector)│   │ (Cache Store)│                                          │
│    └──────────┘   └──────────────┘                                          │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Worker Processes

The system includes multiple background workers:

1. **Poller Worker** (`src/ingestion/poller.py`): Continuously polls Kalshi & Polymarket APIs every 60s for new markets
2. **Price Updater Worker** (`src/workers/price_updater.py`): Updates market prices every 60s, prioritizes active arbitrage opportunities
3. **Arbitrage Monitor** (`src/trading/arbitrage_monitor.py`): Scans bonded markets for cross-platform arbitrage opportunities

### Tier System

| Tier | Requirements | Description | Trading Size |
|------|--------------|-------------|--------------|
| **1** | p_match ≥ 0.85 **AND** similarity_score ≥ 0.825 | **Auto Bond** - High confidence, safe for full arbitrage | 100% |
| **2** | p_match ≥ 0.75 **AND** similarity_score ≥ 0.70 | **Cautious Bond** - Reduced size, optional review | 10-25% |
| **3** | Below Tier 2 thresholds | **Reject** - No trading | 0% |

**Important**: Tier assignment requires BOTH thresholds to be met. A bond with p_match=0.90 but similarity_score=0.80 will be assigned to Tier 2, not Tier 1.

**Tier 1 Additional Requirements**:
- Text similarity ≥ 0.75
- Outcome score ≥ 0.90
- Time alignment score ≥ 0.01
- Resolution source score ≥ 0.20

See `src/similarity/tier_assigner.py:26-45` for complete logic.

---

## API Reference

### Authentication

All endpoints require `X-API-Key` header:

```bash
curl -H "X-API-Key: your-api-key-here" http://localhost:8000/v1/health
```

### Endpoints

#### Dashboard & Health

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/` | Interactive HTML dashboard with system metrics |
| GET | `/v1/status` | Detailed JSON status (bonds, markets, health) |
| GET | `/v1/health` | Health check + dependency status |

#### Bond Registry & Markets

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/bond_registry` | Get all active bonds (for trading engine) |
| GET | `/v1/bonds` | List all bonds with filtering (tier, status) |
| GET | `/v1/pairs/{platform}/{market_id}` | Get bonds for specific market |
| POST | `/v1/pairs/recompute` | Trigger similarity recalculation |
| GET | `/v1/markets/{platform}` | List markets by platform |
| GET | `/v1/markets/{platform}/{market_id}` | Get specific market details |

#### Arbitrage Opportunities

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/arbitrage/opportunities` | Top cross-platform arbitrage opportunities |
| GET | `/v1/arbitrage/opportunities/{bond_id}` | Specific arbitrage opportunity by bond ID |
| GET | `/v1/arbitrage/intra-platform` | Intra-platform arbitrage (yes+no < $1) |
| POST | `/v1/arbitrage/scan` | Manually trigger arbitrage scan |
| GET | `/v1/arbitrage/stats` | Arbitrage monitoring statistics |
| GET | `/v1/arbitrage/priority-markets` | Market IDs to prioritize for price updates |
| DELETE | `/v1/arbitrage/stale` | Remove stale opportunities |

**Example: Get Bond Registry**:

```bash
curl -H "X-API-Key: your-key" \
  "http://localhost:8000/v1/bond_registry?tier=1&min_volume=1000&limit=50" | jq
```

**Response**:

```json
{
  "bonds": [
    {
      "pair_id": "KXMARKET123-0xabc123...",
      "kalshi_market_id": "KXMARKET123",
      "polymarket_condition_id": "0xabc123...",
      "tier": 1,
      "p_match": 0.92,
      "outcome_mapping": {"Yes": "Yes", "No": "No"},
      "trading_params": {
        "max_notional": 10000,
        "max_position_pct": 0.10
      },
      "arbitrage": {
        "has_arbitrage": true,
        "arbitrage_type": "kalshi_sell_poly_buy",
        "profit_per_dollar": 0.023,
        "kalshi_price": 0.68,
        "polymarket_price": 0.65
      }
    }
  ],
  "total": 142,
  "pagination": {
    "limit": 50,
    "offset": 0,
    "has_more": true
  }
}
```

---

## Development

### Running Tests

```bash
# Install test dependencies
pip install pytest pytest-cov pytest-asyncio

# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_similarity_calculator.py -v

# Run integration tests
pytest tests/integration/ --integration
```

### Code Quality

```bash
# Format code
black src/ tests/

# Lint
flake8 src/ tests/
pylint src/

# Type checking
mypy src/
```

### Development Scripts

**Reclassify Markets**:

```bash
# Reclassify all markets with updated event classifier
python3 scripts/reclassify_markets.py --batch-size 2000
```

**Create Bonds**:

```bash
# Generate bonds for markets
python3 scripts/create_bonds.py --max-markets 1000 --batch-size 100
```

**Manual Market Ingestion**:

```bash
# Ingest specific markets
python3 scripts/ingest_markets.py --platform kalshi --market-ids KXMARKET1,KXMARKET2
```

---

## Monitoring

### Key Metrics

| Metric | Warning | Critical | Purpose |
|--------|---------|----------|---------|
| Tier 1 mismatch rate | Any occurrence | — | Bond accuracy |
| Tier 2 mismatch rate | >3% | >5% | Bond quality |
| API latency (p99) | >200ms | >500ms | Performance |
| API error rate | >1% | >5% | Reliability |
| Ingestion lag | >5 min | >15 min | Data freshness |
| Cache hit rate | <70% | <50% | Caching effectiveness |

### Logging

Structured JSON logging to `/logs/bonding_agent.log`:

```bash
# View logs with jq
tail -f logs/bonding_agent.log | jq '.'

# Filter by level
tail -f logs/bonding_agent.log | jq 'select(.level=="ERROR")'

# Monitor similarity calculations
tail -f logs/bonding_agent.log | jq 'select(.event=="similarity_calculation")'
```

---

## Safety Principles

**Precision over Recall**: False positives (bad bonds) are catastrophic. False negatives (missed opportunities) are acceptable.

### Hard Constraints (Auto-Reject)

Markets are rejected if ANY of the following are true:

1. **Event Type Mismatch**: Different event_type classifications (e.g., sports vs election)
2. **Direction Mismatch**: Opposite directions (e.g., "over 45.5" vs "under 45.5")
3. **Entity Name Mismatch**: No shared people entities when both markets have people
4. **Sport Type Mismatch**: Different sports (e.g., NFL vs NHL)
5. **Parlay Mismatch**: One is multi-game parlay, other is single-game
6. **Time Skew**: >150 days apart
7. **Text Similarity**: <50%
8. **Outcome Incompatibility**: Cannot map outcomes 1:1

---

## Similarity Features

Five weighted features determine final similarity score:

1. **Text Similarity** (35%): Embedding cosine similarity on market titles/descriptions
2. **Entity Similarity** (25%): Overlap of tickers, people, organizations, countries
3. **Time Alignment** (15%): Resolution date proximity
4. **Outcome Structure** (20%): Yes/no polarity, bracket compatibility
5. **Resolution Source** (5%): Authority matching (BLS, FOMC, etc.)

---

## Performance Optimizations

### Database Connection Pooling

PostgreSQL connection pool configured via SQLAlchemy:

```python
# In src/models/__init__.py
engine = create_engine(
    DATABASE_URL,
    pool_size=10,              # Concurrent connections
    max_overflow=20,           # Additional connections under load
    pool_timeout=30,           # Seconds to wait for connection
    pool_recycle=3600,         # Recycle connections every hour
    pool_pre_ping=True,        # Verify connections before use
)
```

**Tuning Guidelines**:
- Development: `pool_size=5, max_overflow=10`
- Production: `pool_size=20, max_overflow=40`
- Monitor pool exhaustion via `/v1/health` endpoint

### Vector Search Index (HNSW)

pgvector supports two index types for embedding similarity:

| Index Type | Build Time | Query Speed | Recall |
|------------|-----------|-------------|--------|
| **IVFFlat** | Fast | Medium | ~95% |
| **HNSW** | Slow | Very Fast | ~99% |

**Production Recommendation**: Use HNSW for candidate generation at scale.

**Create HNSW Index**:
```sql
CREATE INDEX idx_markets_embedding ON markets
USING hnsw (text_embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
```

**Parameters**:
- `m = 16`: Neighbors per layer (higher = better recall, slower build)
- `ef_construction = 64`: Build-time search depth

**Query Tuning**:
```sql
SET hnsw.ef_search = 100;  -- Higher = better recall, slower queries
```

### Redis Caching Strategy

**Bond Registry Cache** (`bond_registry_cache_ttl_sec=60`):
- Cache key: `bond_registry:{tier}:{min_volume}`
- Invalidation: On bond state change (tier upgrade/downgrade)
- Hit rate target: >90%

**Market Price Cache** (`price_cache_ttl_sec=10`):
- Cache key: `market_prices:{platform}:{market_id}`
- Invalidation: On price update from worker
- Hit rate target: >70%

**Monitor Cache Performance**:
```bash
# Check hit rate
docker exec bonding_redis redis-cli INFO stats | grep keyspace_hits
```

### Async/Await Pattern (Future Enhancement)

The price_updater worker currently uses synchronous HTTP calls. Converting to async/await would improve throughput:

**Current** (synchronous):
```python
for market_id in market_ids:
    price = kalshi_client.get_price(market_id)  # Blocks 50-100ms
    update_database(market_id, price)
```

**Optimized** (async):
```python
import asyncio
import aiohttp

async def fetch_prices(market_ids):
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_price(session, mid) for mid in market_ids]
        return await asyncio.gather(*tasks)  # Parallel execution
```

**Expected Improvement**: 10x throughput (50 markets/sec → 500 markets/sec)

### Parallel Order Book Fetching

Polymarket order books are fetched sequentially. Parallelizing with `ThreadPoolExecutor` would reduce latency:

```python
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(max_workers=10) as executor:
    futures = [executor.submit(clob_client.get_book, token_id) for token_id in token_ids]
    order_books = [f.result() for f in futures]
```

**Impact**: Reduce 50-market update from 25s → 5s

### Query Optimization

**Slow Query Example** (full table scan):
```sql
SELECT * FROM bonds WHERE status = 'active' AND tier = 1;
```

**Optimized** (compound index):
```sql
CREATE INDEX idx_bonds_status_tier ON bonds (status, tier);
```

**Candidate Generation** (vector + filters):
```sql
-- Use HNSW index first, then apply filters
SELECT id, 1 - (text_embedding <=> $1) AS similarity
FROM markets
WHERE platform = 'polymarket'
  AND close_time > NOW()
ORDER BY text_embedding <=> $1
LIMIT 50;
```

### Monitoring Query Performance

```sql
-- Enable slow query logging
ALTER SYSTEM SET log_min_duration_statement = 100;  -- Log queries >100ms

-- View slow queries
SELECT query, calls, mean_exec_time
FROM pg_stat_statements
WHERE mean_exec_time > 100
ORDER BY mean_exec_time DESC
LIMIT 10;
```

---

## Contributing

1. Read [CLAUDE.md](CLAUDE.md) for development guidelines
2. All similarity logic changes must be tested against labeled dataset
3. Update SYSTEM_DESIGN.md if architecture changes
4. Maintain >99.5% precision for Tier 1 bonds
5. Add tests for new event types in `test_event_classifier.py`

---

## License

[Add license information]

---

## Contact

[Add contact information]

---

**Status**: Production (v1.0)

**Last Updated**: 2025-01-14
