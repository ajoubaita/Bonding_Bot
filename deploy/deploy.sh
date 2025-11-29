#!/bin/bash

# Bonding Bot Deployment Script
# This script deploys the Bonding Bot to a production server

set -e  # Exit on error

echo "========================================"
echo "Bonding Bot - Production Deployment"
echo "========================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: Please run as root (use sudo)${NC}"
    exit 1
fi

# Get the deployment directory
DEPLOY_DIR="/opt/bonding_bot"
REPO_URL="https://github.com/ajoubaita/Bonding_Bot.git"

echo "Step 1: Installing system dependencies..."
apt-get update
apt-get install -y \
    docker.io \
    docker-compose \
    git \
    nginx \
    certbot \
    python3-certbot-nginx \
    ufw

echo -e "${GREEN}✓ System dependencies installed${NC}"
echo ""

echo "Step 2: Starting Docker service..."
systemctl start docker
systemctl enable docker

echo -e "${GREEN}✓ Docker service started${NC}"
echo ""

echo "Step 3: Setting up firewall..."
ufw --force enable
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow http
ufw allow https

echo -e "${GREEN}✓ Firewall configured${NC}"
echo ""

echo "Step 4: Creating deployment directory..."
mkdir -p $DEPLOY_DIR
cd $DEPLOY_DIR

echo -e "${GREEN}✓ Deployment directory created: $DEPLOY_DIR${NC}"
echo ""

echo "Step 5: Cloning repository..."
if [ -d ".git" ]; then
    echo "Repository exists, pulling latest..."
    git pull origin master
else
    git clone $REPO_URL .
fi

echo -e "${GREEN}✓ Repository ready${NC}"
echo ""

echo "Step 6: Setting up environment variables..."
if [ ! -f "deploy/.env.production" ]; then
    echo -e "${RED}Error: deploy/.env.production not found${NC}"
    echo "Please create deploy/.env.production with your configuration"
    exit 1
fi

# Copy environment file
cp deploy/.env.production deploy/.env

# Generate secure passwords if needed
if grep -q "CHANGE_ME" deploy/.env; then
    echo -e "${YELLOW}Warning: Default passwords detected in .env file${NC}"
    echo "Generating secure passwords..."

    # Generate random password
    POSTGRES_PASS=$(openssl rand -base64 32)
    API_KEY=$(openssl rand -base64 48)

    # Replace in .env
    sed -i "s/POSTGRES_PASSWORD=CHANGE_ME_SECURE_PASSWORD_HERE/POSTGRES_PASSWORD=$POSTGRES_PASS/" deploy/.env
    sed -i "s/BONDING_API_KEY=CHANGE_ME_SECURE_API_KEY_HERE/BONDING_API_KEY=$API_KEY/" deploy/.env

    echo -e "${GREEN}✓ Secure passwords generated${NC}"
    echo ""
    echo -e "${YELLOW}IMPORTANT: Save these credentials:${NC}"
    echo "PostgreSQL Password: $POSTGRES_PASS"
    echo "API Key: $API_KEY"
    echo ""
    read -p "Press Enter to continue..."
fi

echo -e "${GREEN}✓ Environment configured${NC}"
echo ""

echo "Step 7: Building Docker images..."
cd $DEPLOY_DIR/deploy
docker-compose -f docker-compose.production.yml build

echo -e "${GREEN}✓ Docker images built${NC}"
echo ""

echo "Step 8: Starting services..."
docker-compose -f docker-compose.production.yml up -d

echo -e "${GREEN}✓ Services started${NC}"
echo ""

echo "Step 9: Running database migrations..."
sleep 10  # Wait for PostgreSQL to be ready
docker exec bonding_api alembic upgrade head

echo -e "${GREEN}✓ Database migrations complete${NC}"
echo ""

echo "Step 10: Configuring Nginx..."
cp $DEPLOY_DIR/deploy/nginx.conf /etc/nginx/sites-available/bonding_bot
ln -sf /etc/nginx/sites-available/bonding_bot /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test Nginx configuration
nginx -t

# Reload Nginx
systemctl reload nginx
systemctl enable nginx

echo -e "${GREEN}✓ Nginx configured${NC}"
echo ""

echo "Step 11: Setting up SSL (optional)..."
read -p "Do you have a domain name for SSL setup? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    read -p "Enter your domain name: " DOMAIN
    certbot --nginx -d $DOMAIN
    echo -e "${GREEN}✓ SSL configured for $DOMAIN${NC}"
else
    echo "Skipping SSL setup. You can run 'certbot --nginx' later."
fi
echo ""

echo "Step 12: Verifying deployment..."
sleep 5

# Check if services are running
if docker ps | grep -q bonding_api; then
    echo -e "${GREEN}✓ API service is running${NC}"
else
    echo -e "${RED}✗ API service failed to start${NC}"
fi

if docker ps | grep -q bonding_poller; then
    echo -e "${GREEN}✓ Poller service is running${NC}"
else
    echo -e "${RED}✗ Poller service failed to start${NC}"
fi

if docker ps | grep -q bonding_postgres; then
    echo -e "${GREEN}✓ PostgreSQL is running${NC}"
else
    echo -e "${RED}✗ PostgreSQL failed to start${NC}"
fi

if docker ps | grep -q bonding_redis; then
    echo -e "${GREEN}✓ Redis is running${NC}"
else
    echo -e "${RED}✗ Redis failed to start${NC}"
fi

echo ""

# Test health endpoint
echo "Testing health endpoint..."
if curl -s http://localhost:8000/v1/health | grep -q "healthy"; then
    echo -e "${GREEN}✓ Health check passed${NC}"
else
    echo -e "${YELLOW}⚠ Health check failed (services may still be starting)${NC}"
fi

echo ""
echo "========================================"
echo "Deployment Complete!"
echo "========================================"
echo ""
echo "Services are running at:"
echo "  API: http://localhost:8000"
echo "  External: http://$(curl -s ifconfig.me)"
echo ""
echo "Useful commands:"
echo "  View logs:       docker-compose -f $DEPLOY_DIR/deploy/docker-compose.production.yml logs -f"
echo "  Restart:         docker-compose -f $DEPLOY_DIR/deploy/docker-compose.production.yml restart"
echo "  Stop:            docker-compose -f $DEPLOY_DIR/deploy/docker-compose.production.yml stop"
echo "  Health check:    curl http://localhost:8000/v1/health"
echo ""
echo "Next steps:"
echo "1. Test the API: curl http://$(curl -s ifconfig.me)/v1/health"
echo "2. Monitor logs: docker-compose -f $DEPLOY_DIR/deploy/docker-compose.production.yml logs -f"
echo "3. Set up monitoring and alerts"
echo ""
