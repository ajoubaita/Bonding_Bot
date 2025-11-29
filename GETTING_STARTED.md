# Getting Started with Bonding Bot

This guide will help you set up and run the Bonding Bot market bonding agent.

## Prerequisites

- Python 3.10 or higher
- Docker and Docker Compose (for PostgreSQL and Redis)
- Virtual environment tool (venv)

## Step 1: Clone and Setup Environment

```bash
cd /Users/adamoubaita/Bonding_Bot

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Download ML models
python3 -m spacy download en_core_web_sm
```

## Step 2: Start Services

```bash
# Start PostgreSQL (with pgvector) and Redis
docker-compose up -d

# Verify services are running
docker-compose ps

# Check logs if needed
docker-compose logs postgres
docker-compose logs redis
```

## Step 3: Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env if needed (defaults should work for local development)
# nano .env
```

## Step 4: Initialize Database

### Option A: Using Alembic (Recommended)

```bash
# Create initial migration
alembic upgrade head

# This will:
# - Enable pgvector extension
# - Create markets table
# - Create bonds table
# - Create all necessary indexes
```

### Option B: Using init script

```bash
# Alternative: Direct table creation (skip if using Alembic)
python3 scripts/init_database.py
```

## Step 5: Verify Installation

```bash
# Run tests
pytest

# Run specific test
pytest tests/unit/test_text_similarity.py -v

# Check database connection
python3 -c "from src.models import engine; print('Database connected:', engine.connect())"
```

## Step 6: Start API Server

```bash
# Start the FastAPI server
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# In another terminal, test the health endpoint
curl http://localhost:8000/v1/health | jq
```

You should see output like:

```json
{
  "status": "healthy",
  "timestamp": "2025-01-20T15:45:00Z",
  "components": {
    "database": {"status": "healthy"},
    "redis": {"status": "healthy"},
    ...
  },
  "metrics": {
    "total_markets_kalshi": 0,
    "total_markets_polymarket": 0,
    "total_bonds_tier1": 0,
    "total_bonds_tier2": 0
  }
}
```

## Step 7: Test API Endpoints

### View API Documentation

Open your browser to: http://localhost:8000/docs

This shows the interactive Swagger UI for all endpoints.

### Test Market Ingestion

```bash
curl -X POST http://localhost:8000/v1/markets/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-key-change-in-production" \
  -d '{
    "platform": "kalshi",
    "markets": [
      {
        "id": "TEST-001",
        "title": "Will Bitcoin reach $100k by end of 2025?",
        "description": "Resolves YES if BTC >= $100,000",
        "category": "crypto",
        "resolution_date": "2025-12-31T23:59:59Z",
        "resolution_source": "CoinGecko",
        "outcome_type": "yes_no",
        "outcomes": [
          {"label": "Yes", "token_id": "yes_token"},
          {"label": "No", "token_id": "no_token"}
        ]
      }
    ]
  }' | jq
```

### Check Bond Registry

```bash
curl http://localhost:8000/v1/bond_registry \
  -H "X-API-Key: dev-key-change-in-production" | jq
```

## Step 8: Next Steps

### Implement Missing Components

The current MVP has these TODO items:

1. **Normalization Pipeline** (`src/normalization/`)
   - Text cleaning
   - Entity extraction (NER)
   - Embedding generation
   - Outcome schema parsing

2. **External API Clients** (`src/ingestion/`)
   - Kalshi client
   - Polymarket Gamma client
   - Polymarket CLOB client

3. **Candidate Generation** (`src/similarity/candidate_generator.py`)
   - Fast filtering using embeddings
   - Category/entity/time filters

4. **Background Workers** (`src/workers/`)
   - Celery task for similarity recomputation
   - Polling jobs for market ingestion

5. **Model Training** (`scripts/train_similarity_model.py`)
   - Label 100+ market pairs
   - Train logistic regression
   - Validate precision metrics

### Development Workflow

```bash
# Watch for file changes and restart server
uvicorn src.api.main:app --reload

# Run tests on save
pytest --watch

# Format code
black src/ tests/

# Type checking
mypy src/

# Linting
flake8 src/ tests/
```

## Troubleshooting

### Database Connection Error

```bash
# Check PostgreSQL is running
docker-compose ps postgres

# Check connection settings
echo $DATABASE_URL

# Test direct connection
psql postgresql://bonding_user:bonding_pass@localhost:5432/bonding_agent
```

### Redis Connection Error

```bash
# Check Redis is running
docker-compose ps redis

# Test connection
redis-cli ping
```

### Import Errors

```bash
# Ensure you're in virtual environment
which python  # Should show venv path

# Reinstall dependencies
pip install -r requirements.txt

# Check PYTHONPATH
export PYTHONPATH=/Users/adamoubaita/Bonding_Bot:$PYTHONPATH
```

### Port Already in Use

```bash
# Find process using port 8000
lsof -i :8000

# Kill process (replace PID)
kill -9 PID

# Or use different port
uvicorn src.api.main:app --port 8001
```

## Useful Commands

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (CAUTION: deletes data)
docker-compose down -v

# View logs
docker-compose logs -f

# Restart service
docker-compose restart postgres

# Check disk usage
docker system df

# Clean up
docker system prune

# Database backup
docker exec bonding_bot_postgres pg_dump -U bonding_user bonding_agent > backup.sql

# Database restore
docker exec -i bonding_bot_postgres psql -U bonding_user bonding_agent < backup.sql
```

## Architecture Overview

```
API Server (Port 8000)
  ↓
FastAPI Routes
  ├── /v1/health
  ├── /v1/markets/ingest
  ├── /v1/markets/{platform}/{id}/candidates
  ├── /v1/pairs/{platform}/{id}
  ├── /v1/bond_registry
  └── /v1/pairs/recompute
  ↓
Similarity Calculator
  ├── Text Similarity (35%)
  ├── Entity Similarity (25%)
  ├── Time Alignment (15%)
  ├── Outcome Similarity (20%)
  └── Resolution Similarity (5%)
  ↓
Tier Assignment
  ├── Tier 1 (p_match ≥ 0.98)
  ├── Tier 2 (p_match ≥ 0.90)
  └── Tier 3 (reject)
  ↓
Bond Registry → Trading Engine
```

## Resources

- **System Design**: See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)
- **Developer Guide**: See [CLAUDE.md](CLAUDE.md)
- **API Docs**: http://localhost:8000/docs
- **GitHub Issues**: https://github.com/ajoubaita/Bonding_Bot/issues

## Support

For questions or issues:
1. Check CLAUDE.md for development guidelines
2. Review SYSTEM_DESIGN.md for architecture details
3. Open an issue on GitHub

---

**Ready to start developing!** 🚀
