# Quick Deployment Guide

## Step 1: Push to GitHub (Manual - Requires Authentication)

Since git authentication is required, please run this manually:

```bash
cd /Users/adamoubaita/Bonding_Bot-1
git push origin master
```

You'll be prompted for:
- **Username**: Your GitHub username
- **Password**: Use a GitHub Personal Access Token (not your password)
  - Create one at: https://github.com/settings/tokens
  - Select scope: `repo`

Or if you have SSH keys set up:
```bash
git remote set-url origin git@github.com:ajoubaita/Bonding_Bot.git
git push origin master
```

## Step 2: Deploy to Droplet

Once pushed to GitHub, run the deployment script:

```bash
cd /Users/adamoubaita/Bonding_Bot-1
./DEPLOY_TO_DROPLET.sh
```

This script will:
1. ✅ SSH to the droplet (142.93.182.218)
2. ✅ Pull latest code from GitHub
3. ✅ Update Python dependencies
4. ✅ Run database migrations (if any)
5. ✅ Restart services (API and poller)
6. ✅ Verify services are running
7. ✅ Test health endpoint

## Alternative: Manual Deployment

If the script doesn't work, SSH to the server and run:

```bash
ssh root@142.93.182.218
# Password: PolyMarket123$a

cd /opt/bonding_bot
git pull origin master

# Restart services
cd deploy
docker-compose -f docker-compose.production.yml restart api poller

# Or if using direct docker commands:
docker restart bonding_api bonding_poller

# Check logs
docker logs bonding_api -f
```

## What's New in This Deployment

This update includes:

1. **Enhanced Arbitrage Calculator** (`src/arbitrage/enhanced_calculator.py`)
   - Real bid/ask prices
   - Order book depth calculation
   - Dynamic fees and gas costs
   - Structured trade instructions

2. **Improved Similarity Matching**
   - Direction detection (prevents matching "over" vs "under")
   - Fuzzy text matching
   - Better hard constraints

3. **Structured Logging** (`src/utils/bonding_logger.py`)
   - Bonding decisions logged
   - Arbitrage opportunities tracked
   - Price updates logged
   - Ready for CSV export

4. **Order Book Integration**
   - API clients fetch order books
   - Price updater stores bid/ask
   - Enhanced calculator uses stored data

## Monitoring After Deployment

### Check Logs

```bash
# On the server
ssh root@142.93.182.218

# Watch API logs
docker logs bonding_api -f

# Watch poller logs
docker logs bonding_poller -f

# Check for errors
docker logs bonding_api --tail 100 | grep -i error
```

### Test New Features

```bash
# Test enhanced arbitrage endpoint
curl http://142.93.182.218/v1/markets/arbitrage/{kalshi_id}/{poly_id} | jq

# Check structured logs (if logging to file)
docker exec bonding_api cat /app/logs/app.log | jq 'select(.event_type=="bonding_candidate")'
```

### Verify Services

```bash
# Check all containers are running
docker ps

# Should see:
# - bonding_postgres
# - bonding_redis  
# - bonding_api (restarted with new code)
# - bonding_poller (restarted with new code)

# Test health endpoint
curl http://142.93.182.218/v1/health | jq
```

## Rollback (If Needed)

If something goes wrong, you can rollback:

```bash
ssh root@142.93.182.218
cd /opt/bonding_bot
git log --oneline -5  # See recent commits
git checkout <previous-commit-hash>  # Go back to previous version
cd deploy
docker-compose -f docker-compose.production.yml restart api poller
```

## Troubleshooting

### Services Won't Start

```bash
# Check Docker
docker ps -a

# Check logs for errors
docker logs bonding_api
docker logs bonding_poller

# Restart everything
cd /opt/bonding_bot/deploy
docker-compose -f docker-compose.production.yml down
docker-compose -f docker-compose.production.yml up -d
```

### Import Errors

If you see import errors for new modules:

```bash
# Rebuild the API container
cd /opt/bonding_bot/deploy
docker-compose -f docker-compose.production.yml build api
docker-compose -f docker-compose.production.yml up -d api
```

### Database Migration Issues

```bash
# Check migration status
docker exec bonding_api alembic current

# Run migrations manually
docker exec bonding_api alembic upgrade head
```

## Next Steps

After successful deployment:

1. **Monitor logs** for any errors
2. **Test arbitrage endpoint** with known bonded pairs
3. **Check structured logs** to verify logging is working
4. **Compare results** with old calculator (if needed)

The enhanced calculator should provide more accurate arbitrage detection with realistic execution costs!

