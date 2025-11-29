# Bonding Bot - Production Deployment Guide

This guide provides step-by-step instructions for deploying the Bonding Bot to a production server.

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start (Automated Deployment)](#quick-start-automated-deployment)
- [Manual Deployment](#manual-deployment)
- [Post-Deployment](#post-deployment)
- [Monitoring and Maintenance](#monitoring-and-maintenance)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Server Requirements

- **OS**: Ubuntu 20.04 LTS or newer (Debian-based)
- **RAM**: Minimum 2GB, recommended 4GB+
- **CPU**: 2+ cores recommended
- **Disk**: 20GB+ available space
- **Network**: Public IP address, ports 80/443 accessible

### Access Requirements

- Root or sudo access to the server
- SSH access configured
- Domain name (optional, for SSL)

### Local Requirements

- Git installed locally
- SSH client
- Your server's IP address and credentials

---

## Quick Start (Automated Deployment)

The easiest way to deploy is using the automated deployment script.

### Step 1: Connect to Your Server

```bash
ssh root@YOUR_SERVER_IP
```

### Step 2: Download and Run Deployment Script

```bash
# Download the deployment script
curl -O https://raw.githubusercontent.com/ajoubaita/Bonding_Bot/master/deploy/deploy.sh

# Make it executable
chmod +x deploy.sh

# Run the deployment
sudo ./deploy.sh
```

### Step 3: Follow the Prompts

The script will:
1. Install system dependencies (Docker, Nginx, etc.)
2. Clone the repository
3. Set up environment variables
4. Build and start Docker containers
5. Configure Nginx reverse proxy
6. Optionally set up SSL with Let's Encrypt

**Important**: The script will prompt you for:
- Domain name (if you want SSL)
- Email address (for SSL certificate)

### Step 4: Verify Deployment

```bash
# Check if services are running
docker ps

# Test the health endpoint
curl http://localhost:8000/v1/health
```

You should see:
```json
{
  "status": "healthy",
  "components": {...},
  "metrics": {...}
}
```

---

## Manual Deployment

If you prefer manual deployment or need more control, follow these steps.

### 1. Install System Dependencies

```bash
# Update package list
sudo apt-get update

# Install Docker
sudo apt-get install -y docker.io docker-compose

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker

# Install other dependencies
sudo apt-get install -y git nginx certbot python3-certbot-nginx ufw curl
```

### 2. Configure Firewall

```bash
# Enable firewall
sudo ufw --force enable

# Configure rules
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw allow http
sudo ufw allow https

# Verify status
sudo ufw status
```

### 3. Clone Repository

```bash
# Create deployment directory
sudo mkdir -p /opt/bonding_bot
cd /opt/bonding_bot

# Clone repository
sudo git clone https://github.com/ajoubaita/Bonding_Bot.git .
```

### 4. Configure Environment Variables

```bash
cd /opt/bonding_bot/deploy

# Copy environment template
sudo cp .env.production .env

# Generate secure passwords
POSTGRES_PASS=$(openssl rand -base64 32)
API_KEY=$(openssl rand -base64 48)

# Update .env file
sudo sed -i "s/POSTGRES_PASSWORD=CHANGE_ME_SECURE_PASSWORD_HERE/POSTGRES_PASSWORD=$POSTGRES_PASS/" .env
sudo sed -i "s/BONDING_API_KEY=CHANGE_ME_SECURE_API_KEY_HERE/BONDING_API_KEY=$API_KEY/" .env

# IMPORTANT: Save these credentials
echo "PostgreSQL Password: $POSTGRES_PASS"
echo "API Key: $API_KEY"
```

**Save these credentials in a secure password manager!**

### 5. Build and Start Services

```bash
cd /opt/bonding_bot/deploy

# Build Docker images
sudo docker-compose -f docker-compose.production.yml build

# Start services
sudo docker-compose -f docker-compose.production.yml up -d

# Check logs
sudo docker-compose -f docker-compose.production.yml logs -f
```

Wait for all services to be healthy (about 30 seconds).

### 6. Run Database Migrations

```bash
# Wait for PostgreSQL to be ready
sleep 10

# Run migrations
sudo docker exec bonding_api alembic upgrade head
```

### 7. Configure Nginx

```bash
# Copy Nginx configuration
sudo cp /opt/bonding_bot/deploy/nginx.conf /etc/nginx/sites-available/bonding_bot

# Create symbolic link
sudo ln -sf /etc/nginx/sites-available/bonding_bot /etc/nginx/sites-enabled/

# Remove default site
sudo rm -f /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
sudo systemctl enable nginx
```

### 8. Set Up SSL (Optional but Recommended)

If you have a domain name:

```bash
# Replace YOUR_DOMAIN with your actual domain
sudo certbot --nginx -d YOUR_DOMAIN

# Follow the prompts
# - Enter your email
# - Agree to terms of service
# - Choose whether to redirect HTTP to HTTPS (recommended: yes)
```

If you don't have a domain, you can access the API via HTTP at `http://YOUR_SERVER_IP/v1/`.

### 9. Install Systemd Service

To ensure the services start on boot:

```bash
cd /opt/bonding_bot/deploy/systemd
sudo ./install-service.sh
```

This will:
- Install the systemd service
- Enable it to start on boot
- Start the service immediately

---

## Post-Deployment

### Verify All Services

```bash
# Check Docker containers
docker ps

# Should show 4 containers:
# - bonding_postgres
# - bonding_redis
# - bonding_api
# - bonding_poller
```

### Test API Endpoints

```bash
# Health check (local)
curl http://localhost:8000/v1/health | jq

# Health check (external, replace with your IP/domain)
curl http://YOUR_SERVER_IP/v1/health | jq

# If SSL is configured:
curl https://YOUR_DOMAIN/v1/health | jq
```

### Test API Authentication

```bash
# Get your API key from .env
API_KEY=$(grep BONDING_API_KEY /opt/bonding_bot/deploy/.env | cut -d'=' -f2)

# Test authenticated endpoint
curl -H "X-API-Key: $API_KEY" http://localhost:8000/v1/bond_registry | jq
```

### Verify Market Polling

The poller service should automatically start fetching markets from Kalshi and Polymarket.

```bash
# Check poller logs
docker logs bonding_poller -f

# You should see logs like:
# "Polling Kalshi markets..."
# "Polling Polymarket markets..."
# "Kalshi: fetched 120 markets"
```

---

## Monitoring and Maintenance

### View Logs

```bash
# All services
docker-compose -f /opt/bonding_bot/deploy/docker-compose.production.yml logs -f

# Specific service
docker logs bonding_api -f
docker logs bonding_poller -f
docker logs bonding_postgres -f
docker logs bonding_redis -f

# Nginx logs
sudo tail -f /var/log/nginx/bonding_bot_access.log
sudo tail -f /var/log/nginx/bonding_bot_error.log

# Systemd logs
sudo journalctl -u bonding-bot -f
```

### Check Service Status

```bash
# Docker containers
docker ps

# Systemd service
sudo systemctl status bonding-bot

# Nginx
sudo systemctl status nginx
```

### Restart Services

```bash
# Restart all services
sudo systemctl restart bonding-bot

# Or using docker-compose directly
cd /opt/bonding_bot/deploy
sudo docker-compose -f docker-compose.production.yml restart

# Restart specific service
sudo docker-compose -f docker-compose.production.yml restart api
sudo docker-compose -f docker-compose.production.yml restart poller
```

### Update Code

```bash
cd /opt/bonding_bot

# Pull latest changes
sudo git pull origin master

# Rebuild and restart
cd deploy
sudo docker-compose -f docker-compose.production.yml build
sudo docker-compose -f docker-compose.production.yml up -d

# Run any new migrations
sudo docker exec bonding_api alembic upgrade head
```

### Database Backups

```bash
# Create backup directory
sudo mkdir -p /opt/bonding_bot/deploy/backups

# Backup database
sudo docker exec bonding_postgres pg_dump -U bonding_user bonding_agent > /opt/bonding_bot/deploy/backups/backup_$(date +%Y%m%d_%H%M%S).sql

# Compress backup
gzip /opt/bonding_bot/deploy/backups/backup_*.sql
```

To restore:

```bash
# Restore from backup
gunzip backup_TIMESTAMP.sql.gz
sudo docker exec -i bonding_postgres psql -U bonding_user bonding_agent < backup_TIMESTAMP.sql
```

### Automated Backups (Cron)

```bash
# Edit crontab
sudo crontab -e

# Add daily backup at 2 AM
0 2 * * * docker exec bonding_postgres pg_dump -U bonding_user bonding_agent | gzip > /opt/bonding_bot/deploy/backups/backup_$(date +\%Y\%m\%d_\%H\%M\%S).sql.gz

# Keep only last 7 days of backups
0 3 * * * find /opt/bonding_bot/deploy/backups -name "backup_*.sql.gz" -mtime +7 -delete
```

---

## Troubleshooting

### Services Not Starting

**Check Docker status:**
```bash
sudo systemctl status docker
sudo systemctl start docker
```

**Check container logs:**
```bash
docker logs bonding_api
docker logs bonding_poller
```

**Common issues:**
- Database not ready: Wait 10-20 seconds and restart API
- Port conflicts: Check if port 8000/5432/6379 is already in use
- Environment variables: Verify `.env` file has all required values

### Database Connection Errors

**Check PostgreSQL is running:**
```bash
docker ps | grep postgres
docker logs bonding_postgres
```

**Test database connection:**
```bash
docker exec -it bonding_postgres psql -U bonding_user -d bonding_agent -c "SELECT 1;"
```

**Check credentials in .env:**
```bash
grep POSTGRES /opt/bonding_bot/deploy/.env
```

### API Returns 502 Bad Gateway

**This means Nginx can't connect to the API.**

**Check API is running:**
```bash
docker ps | grep bonding_api
curl http://localhost:8000/v1/health
```

**Check Nginx configuration:**
```bash
sudo nginx -t
sudo systemctl status nginx
```

**Check Nginx logs:**
```bash
sudo tail -f /var/log/nginx/bonding_bot_error.log
```

### SSL Certificate Issues

**Check certificate status:**
```bash
sudo certbot certificates
```

**Renew certificate manually:**
```bash
sudo certbot renew --dry-run
sudo certbot renew
```

**Certbot automatic renewal:**
Certbot installs a cron job automatically. Verify with:
```bash
sudo systemctl status certbot.timer
```

### High Memory Usage

**Check memory usage:**
```bash
docker stats

# Or specific container
docker stats bonding_api
```

**If Redis is using too much memory:**
```bash
# Redis is configured with maxmemory 512mb in docker-compose.yml
# Check current usage
docker exec bonding_redis redis-cli INFO memory
```

**Restart service to free memory:**
```bash
sudo docker-compose -f /opt/bonding_bot/deploy/docker-compose.production.yml restart
```

### Poller Not Fetching Markets

**Check poller logs:**
```bash
docker logs bonding_poller -f
```

**Common issues:**
- API rate limiting: Check logs for HTTP 429 errors
- Network connectivity: Test external APIs from container
- Authentication errors: Verify API keys (though Kalshi/Polymarket public APIs don't need auth)

**Test external API connectivity:**
```bash
# Test Kalshi API
docker exec bonding_poller curl https://api.kalshi.com/v1/markets

# Test Polymarket API
docker exec bonding_poller curl https://gamma-api.polymarket.com/markets
```

---

## Security Recommendations

### 1. Change Default Passwords

**Always generate secure passwords for production:**
```bash
openssl rand -base64 32  # For PostgreSQL
openssl rand -base64 48  # For API key
```

### 2. Limit SSH Access

```bash
# Disable password authentication (use SSH keys only)
sudo vi /etc/ssh/sshd_config
# Set: PasswordAuthentication no
sudo systemctl restart sshd

# Limit SSH to specific IPs (optional)
sudo ufw allow from YOUR_IP to any port 22
```

### 3. Enable Fail2Ban

```bash
sudo apt-get install fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 4. Regular Updates

```bash
# Update system packages monthly
sudo apt-get update
sudo apt-get upgrade

# Update Docker images
cd /opt/bonding_bot/deploy
sudo docker-compose -f docker-compose.production.yml pull
sudo docker-compose -f docker-compose.production.yml up -d
```

### 5. Monitor Logs

Set up log monitoring with tools like:
- **Logrotate**: Prevent logs from filling disk
- **Fail2ban**: Block malicious IPs
- **Prometheus + Grafana**: Metrics and alerting

---

## Performance Tuning

### Optimize PostgreSQL

```bash
# Edit postgresql.conf in container
docker exec -it bonding_postgres bash
vi /var/lib/postgresql/data/postgresql.conf

# Recommended settings for 4GB RAM:
shared_buffers = 1GB
effective_cache_size = 3GB
maintenance_work_mem = 256MB
work_mem = 16MB
```

### Optimize Redis

```bash
# Redis is already configured in docker-compose.yml
# - maxmemory: 512mb
# - maxmemory-policy: allkeys-lru
# - appendonly: yes (persistence)

# Monitor Redis
docker exec bonding_redis redis-cli INFO stats
```

### Nginx Connection Limits

```bash
# Edit nginx.conf
sudo vi /etc/nginx/nginx.conf

# Add to http block:
worker_connections 2048;
keepalive_timeout 65;
```

---

## API Usage Examples

### Health Check

```bash
curl https://YOUR_DOMAIN/v1/health | jq
```

### Get Bond Registry

```bash
API_KEY="your_api_key_here"
curl -H "X-API-Key: $API_KEY" https://YOUR_DOMAIN/v1/bond_registry | jq
```

### Get Bonded Pairs for a Market

```bash
API_KEY="your_api_key_here"
curl -H "X-API-Key: $API_KEY" https://YOUR_DOMAIN/v1/pairs/kalshi/MARKET_ID | jq
```

### Get Candidate Markets

```bash
API_KEY="your_api_key_here"
curl -H "X-API-Key: $API_KEY" https://YOUR_DOMAIN/v1/markets/kalshi/MARKET_ID/candidates | jq
```

---

## Support and Resources

- **GitHub Repository**: https://github.com/ajoubaita/Bonding_Bot
- **System Design**: See [SYSTEM_DESIGN.md](SYSTEM_DESIGN.md)
- **Developer Guide**: See [CLAUDE.md](CLAUDE.md)
- **Getting Started**: See [GETTING_STARTED.md](GETTING_STARTED.md)
- **Test Results**: See [TEST_RESULTS.md](TEST_RESULTS.md)

---

## Summary

You should now have a fully deployed Bonding Bot running in production with:

- ✅ Docker containers for all services
- ✅ Nginx reverse proxy
- ✅ SSL/HTTPS (optional)
- ✅ Automatic restarts on boot
- ✅ Market polling from Kalshi and Polymarket
- ✅ REST API accessible externally
- ✅ Database backups configured
- ✅ Monitoring and logging set up

**Next Steps:**
1. Monitor the poller logs to see markets being ingested
2. Check the bond registry to see Tier 1 and Tier 2 bonds
3. Integrate your trading engine with the API
4. Set up alerting for Tier 1 bond mismatches
5. Monitor performance metrics

Happy trading! 🚀
