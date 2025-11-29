#!/bin/bash

# Deploy Bonding Bot to DigitalOcean
# Run this from your local machine

echo "========================================="
echo "Bonding Bot - Deployment to DigitalOcean"
echo "========================================="
echo ""

SERVER_IP="142.93.182.218"
SERVER_USER="root"

echo "This script will deploy Bonding Bot to $SERVER_IP"
echo ""
echo "You will be prompted for your server password."
echo ""

# Create deployment commands
DEPLOY_COMMANDS=$(cat <<'ENDCMD'
set -e

echo "Step 1: Updating system packages..."
apt-get update -qq

echo "Step 2: Installing Docker and dependencies..."
apt-get install -y docker.io docker-compose git nginx certbot python3-certbot-nginx ufw curl jq > /dev/null 2>&1

echo "Step 3: Starting Docker..."
systemctl start docker
systemctl enable docker

echo "Step 4: Configuring firewall..."
ufw --force enable
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow http
ufw allow https

echo "Step 5: Creating deployment directory..."
mkdir -p /opt/bonding_bot
cd /opt/bonding_bot

echo "Step 6: Cloning repository..."
if [ -d ".git" ]; then
    git pull origin master
else
    git clone https://github.com/ajoubaita/Bonding_Bot.git .
fi

echo "Step 7: Setting up environment..."
cd /opt/bonding_bot/deploy
cp .env.production .env

# Generate secure passwords
POSTGRES_PASS=$(openssl rand -base64 32)
API_KEY=$(openssl rand -base64 48)

# Update .env file
sed -i "s/POSTGRES_PASSWORD=CHANGE_ME_SECURE_PASSWORD_HERE/POSTGRES_PASSWORD=$POSTGRES_PASS/" .env
sed -i "s/BONDING_API_KEY=CHANGE_ME_SECURE_API_KEY_HERE/BONDING_API_KEY=$API_KEY/" .env

echo ""
echo "========================================="
echo "IMPORTANT: Save these credentials!"
echo "========================================="
echo "PostgreSQL Password: $POSTGRES_PASS"
echo "API Key: $API_KEY"
echo "========================================="
echo ""
echo "Press Enter to continue..."
read

echo "Step 8: Building Docker images..."
docker-compose -f docker-compose.production.yml build

echo "Step 9: Starting services..."
docker-compose -f docker-compose.production.yml up -d

echo "Step 10: Waiting for services to be ready..."
sleep 15

echo "Step 11: Running database migrations..."
docker exec bonding_api alembic upgrade head || echo "Migrations may have already run"

echo "Step 12: Configuring Nginx..."
cp /opt/bonding_bot/deploy/nginx.conf /etc/nginx/sites-available/bonding_bot
ln -sf /etc/nginx/sites-available/bonding_bot /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Update nginx.conf to use HTTP only (no SSL initially)
sed -i 's/listen 443 ssl http2;/#listen 443 ssl http2;/' /etc/nginx/sites-available/bonding_bot
sed -i 's/listen \[::\]:443 ssl http2;/#listen [:]:443 ssl http2;/' /etc/nginx/sites-available/bonding_bot

nginx -t
systemctl reload nginx
systemctl enable nginx

echo "Step 13: Installing systemd service..."
cp /opt/bonding_bot/deploy/systemd/bonding-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable bonding-bot.service

echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
echo ""

# Verify services
echo "Checking services..."
docker ps

echo ""
echo "Testing health endpoint..."
sleep 5
curl -s http://localhost:8000/v1/health | jq '.' || echo "API not ready yet, wait 30 seconds and try: curl http://localhost:8000/v1/health"

echo ""
echo "========================================="
echo "Access your API at:"
echo "  http://142.93.182.218/v1/health"
echo ""
echo "Get your API key:"
echo "  grep BONDING_API_KEY /opt/bonding_bot/deploy/.env"
echo ""
echo "View logs:"
echo "  docker logs bonding_api -f"
echo "  docker logs bonding_poller -f"
echo "========================================="
echo ""
ENDCMD
)

echo "Connecting to server and deploying..."
echo ""

ssh -t $SERVER_USER@$SERVER_IP "$DEPLOY_COMMANDS"

echo ""
echo "========================================="
echo "Testing external access..."
echo "========================================="
sleep 3
curl -s http://$SERVER_IP/v1/health | jq '.' && echo "" && echo "✓ Deployment successful!"

echo ""
echo "Next steps:"
echo "1. Get your API key: ssh root@$SERVER_IP \"grep BONDING_API_KEY /opt/bonding_bot/deploy/.env\""
echo "2. Test API: curl -H \"X-API-Key: YOUR_KEY\" http://$SERVER_IP/v1/bond_registry | jq"
echo "3. View logs: ssh root@$SERVER_IP \"docker logs bonding_poller -f\""
echo ""
