#!/bin/bash

# Automated deployment to DigitalOcean
set -e

SERVER_IP="142.93.182.218"
SERVER_USER="root"
SERVER_PASS="PolyMarket123\$a"

echo "========================================="
echo "Bonding Bot - Automated Deployment"
echo "========================================="
echo ""

# Create deployment commands
DEPLOY_COMMANDS=$(cat <<'ENDCMD'
set -e

echo "Step 1: Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

echo "Step 2: Installing Docker and dependencies..."
apt-get install -y -qq docker.io docker-compose git nginx certbot python3-certbot-nginx ufw curl jq

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

# Update .env file (escape special characters for sed)
POSTGRES_PASS_ESCAPED=$(echo "$POSTGRES_PASS" | sed 's/[&/\$]/\\&/g')
API_KEY_ESCAPED=$(echo "$API_KEY" | sed 's/[&/\$]/\\&/g')
sed -i "s/POSTGRES_PASSWORD=CHANGE_ME_SECURE_PASSWORD_HERE/POSTGRES_PASSWORD=$POSTGRES_PASS_ESCAPED/" .env
sed -i "s/BONDING_API_KEY=CHANGE_ME_SECURE_API_KEY_HERE/BONDING_API_KEY=$API_KEY_ESCAPED/" .env

echo ""
echo "========================================="
echo "Generated Credentials (SAVE THESE!):"
echo "========================================="
echo "PostgreSQL Password: $POSTGRES_PASS"
echo "API Key: $API_KEY"
echo "========================================="
echo ""

# Save credentials to a file
cat > /opt/bonding_bot/CREDENTIALS.txt <<EOF
PostgreSQL Password: $POSTGRES_PASS
API Key: $API_KEY
Generated: $(date)
EOF
chmod 600 /opt/bonding_bot/CREDENTIALS.txt

echo "Step 8: Building Docker images..."
docker-compose -f docker-compose.production.yml build

echo "Step 9: Starting services..."
docker-compose -f docker-compose.production.yml up -d

echo "Step 10: Waiting for services to be ready..."
sleep 20

echo "Step 11: Running database migrations..."
docker exec bonding_api alembic upgrade head || echo "Migrations completed or already up to date"

echo "Step 12: Configuring Nginx..."
cp /opt/bonding_bot/deploy/nginx.conf /etc/nginx/sites-available/bonding_bot

# Modify for HTTP-only initially (no SSL)
cat > /etc/nginx/sites-available/bonding_bot <<'NGINXCONF'
upstream bonding_api {
    server 127.0.0.1:8000;
    keepalive 32;
}

limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/s;
limit_req_zone $binary_remote_addr zone=health_limit:10m rate=10r/s;

server {
    listen 80;
    listen [::]:80;
    server_name _;

    access_log /var/log/nginx/bonding_bot_access.log;
    error_log /var/log/nginx/bonding_bot_error.log;

    client_max_body_size 10M;

    location /v1/ {
        limit_req zone=api_limit burst=50 nodelay;
        proxy_pass http://bonding_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Connection "";
        proxy_connect_timeout 5s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }

    location /docs {
        proxy_pass http://bonding_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
    }

    location /redoc {
        proxy_pass http://bonding_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Connection "";
    }
}
NGINXCONF

ln -sf /etc/nginx/sites-available/bonding_bot /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

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

echo "Verifying services..."
docker ps

echo ""
echo "Testing health endpoint..."
sleep 5
curl -s http://localhost:8000/v1/health | jq '.' || echo "Waiting for API to start..."

echo ""
echo "========================================="
echo "Deployment Summary:"
echo "========================================="
echo "API Endpoint: http://142.93.182.218/v1/health"
echo "API Docs: http://142.93.182.218/docs"
echo "Credentials saved to: /opt/bonding_bot/CREDENTIALS.txt"
echo ""
echo "To view credentials: cat /opt/bonding_bot/CREDENTIALS.txt"
echo "To view logs: docker logs bonding_api -f"
echo "To view poller: docker logs bonding_poller -f"
echo "========================================="
ENDCMD
)

echo "Connecting to server and deploying..."
echo ""

sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $SERVER_USER@$SERVER_IP "$DEPLOY_COMMANDS"

echo ""
echo "========================================="
echo "Testing external access from local..."
echo "========================================="
sleep 3

if curl -s http://$SERVER_IP/v1/health | jq '.' > /dev/null 2>&1; then
    echo "✓ API is accessible!"
    curl -s http://$SERVER_IP/v1/health | jq '.'
else
    echo "⚠ API not responding yet. Wait 30 seconds and try: curl http://$SERVER_IP/v1/health"
fi

echo ""
echo "========================================="
echo "Retrieving credentials..."
echo "========================================="
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null $SERVER_USER@$SERVER_IP "cat /opt/bonding_bot/CREDENTIALS.txt"

echo ""
echo "========================================="
echo "Next Steps:"
echo "========================================="
echo "1. Save the credentials above"
echo "2. Test API: curl http://$SERVER_IP/v1/health | jq"
echo "3. View logs: ssh root@$SERVER_IP 'docker logs bonding_poller -f'"
echo "4. Check bonds: curl -H 'X-API-Key: YOUR_KEY' http://$SERVER_IP/v1/bond_registry | jq"
echo ""
echo "✓ Deployment complete!"
echo ""
