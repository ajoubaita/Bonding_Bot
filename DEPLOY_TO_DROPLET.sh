#!/bin/bash

# Quick deployment script to update existing Bonding Bot on droplet
# This script pulls latest code and restarts services

SERVER_IP="142.93.182.218"
SERVER_USER="root"

echo "========================================="
echo "Bonding Bot - Update Deployment"
echo "========================================="
echo ""
echo "This will update the existing Bonding Bot on $SERVER_IP"
echo ""

# Create update commands
UPDATE_COMMANDS=$(cat <<'ENDCMD'
set -e

echo "Step 1: Navigating to deployment directory..."
cd /opt/bonding_bot

echo "Step 2: Pulling latest code from GitHub..."
git fetch origin
git pull origin master || {
    echo "Warning: Git pull failed. Checking if we need to stash changes..."
    git stash
    git pull origin master
}

echo "Step 3: Checking for new dependencies..."
if [ -f "requirements.txt" ]; then
    echo "Updating Python dependencies..."
    docker exec bonding_api pip install -q -r requirements.txt || echo "Dependencies may already be up to date"
fi

echo "Step 4: Running database migrations (if any)..."
docker exec bonding_api alembic upgrade head || echo "Migrations may have already run"

echo "Step 5: Restarting services to load new code..."
cd /opt/bonding_bot/deploy
docker-compose -f docker-compose.production.yml restart api poller || {
    echo "Services may not be running with docker-compose, trying direct restart..."
    docker restart bonding_api bonding_poller 2>/dev/null || echo "Some services may not exist"
}

echo "Step 6: Waiting for services to be ready..."
sleep 10

echo "Step 7: Verifying services are running..."
docker ps | grep bonding || echo "Warning: Some services may not be running"

echo ""
echo "========================================="
echo "Update Complete!"
echo "========================================="
echo ""

# Test health endpoint
echo "Testing health endpoint..."
sleep 5
curl -s http://localhost:8000/v1/health | jq '.' || echo "API may still be starting up..."

echo ""
echo "View logs with:"
echo "  docker logs bonding_api -f"
echo "  docker logs bonding_poller -f"
echo ""
ENDCMD
)

echo "Connecting to server and updating..."
echo ""

ssh -t $SERVER_USER@$SERVER_IP "$UPDATE_COMMANDS"

echo ""
echo "========================================="
echo "Testing external access..."
echo "========================================="
sleep 3
curl -s http://$SERVER_IP/v1/health | jq '.' && echo "" && echo "✓ Update successful!"

echo ""
echo "Next steps:"
echo "1. Monitor logs: ssh root@$SERVER_IP \"docker logs bonding_api -f\""
echo "2. Check for errors: ssh root@$SERVER_IP \"docker logs bonding_api --tail 50\""
echo "3. Test arbitrage endpoint: curl http://$SERVER_IP/v1/markets/arbitrage/{kalshi_id}/{poly_id}"
echo ""

