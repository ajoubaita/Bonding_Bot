# Bonding Bot - Deployment Guide

Quick guide for deploying Bonding Bot to a new server.

## Prerequisites

- Ubuntu 22.04+ server
- Docker & Docker Compose installed
- Python 3.10+
- Git access to repository

## Quick Deployment

### 1. Server Setup

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Install Docker Compose
sudo apt install docker-compose -y

# Install build essentials
sudo apt install -y build-essential python3-dev python3-pip git
```

### 2. Clone Repository

```bash
cd /opt
git clone https://github.com/[YOUR_USERNAME]/Bonding_Bot-1.git bonding_bot
cd bonding_bot
```

### 3. Configure Environment

```bash
cd deploy
cp .env.example .env
nano .env  # Edit with your API keys and settings
```

**Critical settings:**
- `BONDING_API_KEY` - Internal API key
- `KALSHI_API_KEY` - Kalshi API credentials (optional)
- `POLYMARKET_API_KEY` - Polymarket credentials (optional)
- `DATABASE_URL` - PostgreSQL connection
- `REDIS_URL` - Redis connection

### 4. Build and Deploy

```bash
# Build Docker images
docker-compose -f docker-compose.production.yml build --no-cache

# Start services
docker-compose -f docker-compose.production.yml up -d

# Check status
docker-compose -f docker-compose.production.yml ps
```

### 5. Initialize Database

```bash
# Run migrations
docker exec bonding_api bash -c "cd /app && alembic upgrade head"

# Create bonds (initial)
docker exec bonding_api bash -c "cd /app && python3 scripts/create_bonds.py --max-markets 1000"
```

### 6. Verify Deployment

```bash
# Check API health
curl -H "X-API-Key: YOUR_API_KEY" http://localhost:8000/v1/health | jq

# Check bonds created
curl -H "X-API-Key: YOUR_API_KEY" http://localhost:8000/v1/bond_registry?tier=1 | jq
```

## Service Architecture

- **bonding_api** (port 8000) - FastAPI REST API
- **bonding_poller** - Market data ingestion worker
- **bonding_price_updater** - Price update worker
- **bonding_postgres** (port 5432) - PostgreSQL database
- **bonding_redis** (port 6379) - Redis cache

## Updating Deployed Code

```bash
# Pull latest changes
cd /opt/bonding_bot
git pull origin master

# Rebuild and restart (CRITICAL: Use --no-cache to pick up config changes)
cd deploy
docker-compose -f docker-compose.production.yml build --no-cache api poller price_updater
docker-compose -f docker-compose.production.yml up -d

# Verify services restarted
docker-compose -f docker-compose.production.yml ps
```

**IMPORTANT:** Always use `--no-cache` when rebuilding to ensure configuration changes (`src/config.py`) are picked up!

## Monitoring

```bash
# View logs
docker logs bonding_api --tail 100 -f
docker logs bonding_poller --tail 100 -f
docker logs bonding_price_updater --tail 100 -f

# Check database
docker exec bonding_postgres psql -U bonding_user -d bonding_agent -c "SELECT COUNT(*), tier FROM bonds WHERE status='active' GROUP BY tier;"

# Check current bonds
docker exec bonding_api python3 scripts/audit_bonds.py --tier 1 --limit 20
```

## Troubleshooting

### Services won't start

```bash
# Check logs
docker-compose -f docker-compose.production.yml logs

# Restart all services
docker-compose -f docker-compose.production.yml restart
```

### Bond creation fails

```bash
# Check for errors
docker logs bonding_api --tail 200

# Verify config is correct
docker exec bonding_api python3 -c "from src.config import settings; print(f'tier1_min_similarity_score={settings.tier1_min_similarity_score}')"
```

### Old config.py in containers

If you see `AttributeError: 'Settings' object has no attribute 'tier1_min_similarity_score'`:

```bash
# Rebuild with --no-cache flag
docker-compose -f docker-compose.production.yml build --no-cache api poller price_updater
docker-compose -f docker-compose.production.yml up -d
```

## Key Scripts

- `scripts/create_bonds.py` - Create new bonds from markets
- `scripts/audit_bonds.py` - Audit bond quality
- `scripts/reclassify_markets.py` - Update market classifications
- `scripts/init_database.py` - Initialize database schema

## Security Checklist

- [ ] Changed default `BONDING_API_KEY`
- [ ] Configured firewall (allow only 22, 80, 443)
- [ ] Set up SSL/TLS if exposing API publicly
- [ ] Regular backups of PostgreSQL database
- [ ] Monitor logs for suspicious activity

## Backup & Recovery

### Database Backup

```bash
docker exec bonding_postgres pg_dump -U bonding_user bonding_agent > backup_$(date +%Y%m%d).sql
```

### Database Restore

```bash
docker exec -i bonding_postgres psql -U bonding_user bonding_agent < backup_20250126.sql
```

## Further Reading

- **README.md** - Project overview and architecture
- **SYSTEM_DESIGN.md** - Detailed technical specification
- **CLAUDE.md** - Development guidelines for Claude Code
