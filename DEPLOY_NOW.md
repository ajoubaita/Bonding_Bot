# Deploy to Your DigitalOcean Server

**Server IP**: 142.93.182.218

## Quick Deployment (5 minutes)

### Step 1: Push Code to GitHub

First, push the committed code to GitHub:

```bash
cd /Users/adamoubaita/Bonding_Bot

# If you have SSH keys:
git remote set-url origin git@github.com:ajoubaita/Bonding_Bot.git
git push -u origin master

# Or use HTTPS with personal access token:
git push -u origin master
# (will prompt for GitHub username and token)
```

Verify at: https://github.com/ajoubaita/Bonding_Bot

### Step 2: SSH to Your Server

```bash
ssh root@142.93.182.218
# Password: PolyMarket123$a
```

### Step 3: Run Automated Deployment

```bash
# Download deployment script
curl -O https://raw.githubusercontent.com/ajoubaita/Bonding_Bot/master/deploy/deploy.sh

# Make executable
chmod +x deploy.sh

# Run deployment
./deploy.sh
```

The script will:
1. ✓ Install Docker, Nginx, certbot, firewall
2. ✓ Clone repository to /opt/bonding_bot
3. ✓ Generate secure passwords
4. ✓ Build Docker images
5. ✓ Start all services (postgres, redis, api, poller)
6. ✓ Configure Nginx reverse proxy
7. ✓ Optionally set up SSL

### Step 4: Verify Deployment

```bash
# Check services are running
docker ps

# Should show 4 containers:
# - bonding_postgres
# - bonding_redis
# - bonding_api
# - bonding_poller

# Test health endpoint
curl http://localhost:8000/v1/health | jq
```

Expected response:
```json
{
  "status": "healthy",
  "components": {
    "database": "connected",
    "redis": "connected"
  },
  "metrics": {...}
}
```

### Step 5: Test External Access

From your local machine:

```bash
# Test health endpoint (replace with your IP)
curl http://142.93.182.218/v1/health | jq
```

### Step 6: Get Your API Key

On the server:

```bash
# Get the generated API key
grep BONDING_API_KEY /opt/bonding_bot/deploy/.env
```

**Save this API key securely!** You'll need it for API calls.

### Step 7: Test API with Authentication

```bash
# Replace YOUR_API_KEY with the key from step 6
curl -H "X-API-Key: YOUR_API_KEY" http://142.93.182.218/v1/bond_registry | jq
```

---

## Manual Deployment (if automated script fails)

If the automated script fails, follow the manual steps in DEPLOYMENT.md:

```bash
# On your server
cat /opt/bonding_bot/DEPLOYMENT.md
# Or view at: https://github.com/ajoubaita/Bonding_Bot/blob/master/DEPLOYMENT.md
```

---

## Optional: Set Up SSL/HTTPS

If you have a domain name pointing to 142.93.182.218:

```bash
# On your server
sudo certbot --nginx -d yourdomain.com

# Follow prompts:
# - Enter email
# - Agree to terms
# - Choose to redirect HTTP to HTTPS (recommended)
```

Then access via:
```bash
curl https://yourdomain.com/v1/health | jq
```

---

## Monitoring

### View Logs

```bash
# All services
docker-compose -f /opt/bonding_bot/deploy/docker-compose.production.yml logs -f

# Just the API
docker logs bonding_api -f

# Just the poller
docker logs bonding_poller -f
```

### Check Market Polling

```bash
# Watch poller logs
docker logs bonding_poller -f

# Should see:
# "Polling Kalshi markets..."
# "Kalshi: fetched 120 markets"
# "Polling Polymarket markets..."
# "Polymarket: fetched 85 markets"
```

### Restart Services

```bash
# Restart all
docker-compose -f /opt/bonding_bot/deploy/docker-compose.production.yml restart

# Restart specific service
docker-compose -f /opt/bonding_bot/deploy/docker-compose.production.yml restart api
```

---

## Security Notes

**Important**: After deployment, consider:

1. **Change SSH password**:
   ```bash
   passwd
   ```

2. **Set up SSH keys** (more secure than password):
   ```bash
   # From your local machine
   ssh-copy-id root@142.93.182.218

   # Then disable password auth on server
   vi /etc/ssh/sshd_config
   # Set: PasswordAuthentication no
   systemctl restart sshd
   ```

3. **Limit SSH to your IP**:
   ```bash
   ufw allow from YOUR_IP to any port 22
   ```

4. **Set up fail2ban**:
   ```bash
   apt-get install fail2ban
   systemctl enable fail2ban
   systemctl start fail2ban
   ```

---

## Troubleshooting

### Services won't start

```bash
# Check Docker
systemctl status docker
systemctl start docker

# Check logs
docker-compose -f /opt/bonding_bot/deploy/docker-compose.production.yml logs
```

### Can't access API externally

```bash
# Check Nginx
systemctl status nginx
nginx -t

# Check firewall
ufw status
```

### Database connection errors

```bash
# Check PostgreSQL
docker logs bonding_postgres

# Test connection
docker exec -it bonding_postgres psql -U bonding_user -d bonding_agent -c "SELECT 1;"
```

---

## Next Steps After Deployment

1. **Monitor market polling**: Check logs to ensure markets are being fetched
2. **Check bond registry**: Query `/v1/bond_registry` to see Tier 1 and Tier 2 bonds
3. **Set up monitoring**: Consider Prometheus + Grafana for metrics
4. **Configure backups**: Set up automated database backups (see DEPLOYMENT.md)
5. **Integrate trading engine**: Use the API endpoints to execute arbitrage trades

---

## API Endpoints

Once deployed, you can access:

- **Health**: `GET http://142.93.182.218/v1/health`
- **Bond Registry**: `GET http://142.93.182.218/v1/bond_registry` (requires API key)
- **Bonded Pairs**: `GET http://142.93.182.218/v1/pairs/{platform}/{market_id}` (requires API key)
- **Candidates**: `GET http://142.93.182.218/v1/markets/{platform}/{market_id}/candidates` (requires API key)
- **API Docs**: `http://142.93.182.218/docs` (interactive Swagger UI)

---

## Support

For detailed documentation, see:
- **DEPLOYMENT.md** - Complete deployment guide
- **SYSTEM_DESIGN.md** - System architecture and design
- **GETTING_STARTED.md** - Development setup
- **TEST_RESULTS.md** - Test results and validation

Repository: https://github.com/ajoubaita/Bonding_Bot

---

**Ready to deploy? Start with Step 1 above!** 🚀
