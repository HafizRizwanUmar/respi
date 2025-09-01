# Updated Ad Filter System Setup Instructions

## Overview

This updated version addresses the issues you encountered with Pi-hole API v6 compatibility and domain configuration. The system is now properly configured for your domain `api.quranoitratacademy.com` and Pi-hole at `192.168.100.18`.

## Key Changes Made

### 1. Nginx Configuration Updates
- ✅ Updated to use your domain `api.quranoitratacademy.com`
- ✅ Added proper HTTPS redirect configuration
- ✅ Fixed SSL certificate paths for your domain
- ✅ Updated IP restrictions to allow your Pi-hole IP `192.168.100.18`
- ✅ Added support for Pi-hole API v6 headers
- ✅ Changed backend port from 8000 to 8081 to match your setup

### 2. Bridge Agent Improvements
- ✅ Updated ML API URL to use correct domain
- ✅ Enhanced Pi-hole API v6 compatibility
- ✅ Improved error handling and logging

### 3. SSH Tunnel Setup
- ✅ Created automated SSH tunnel setup script
- ✅ Added systemd service for persistent tunnel connection
- ✅ Proper tunnel management and monitoring

## Quick Setup Steps

### 1. Deploy the Updated System

```bash
# Copy the updated files to your VPS
cd /path/to/ad_filter_system_updated

# Run the deployment script
chmod +x deploy.sh
./deploy.sh

# The script will:
# - Install dependencies
# - Create systemd service (running on port 8081)
# - Configure Nginx with your domain
# - Set up SSL-ready configuration
```

### 2. Configure Environment Variables

```bash
# Copy and edit the environment file
cp .env.example .env
nano .env

# Update these key values:
PIHOLE_URL=http://192.168.100.18/admin/api.php
PIHOLE_TOKEN=your_actual_pihole_token
SECRET_KEY=generate_a_secure_random_key
```

### 3. Set Up SSH Tunnel to Pi-hole

```bash
# Run the SSH tunnel setup script
chmod +x ssh_tunnel_setup.sh
./ssh_tunnel_setup.sh

# This will:
# - Generate SSH keys if needed
# - Test connection to your Pi
# - Create systemd service for persistent tunnel
# - Start the tunnel service
```

### 4. Verify Services

```bash
# Check API service
sudo systemctl status ad-filter-api

# Check SSH tunnel
sudo systemctl status pihole-tunnel

# Check Nginx
sudo systemctl status nginx

# Test API endpoint
curl -X POST "https://api.quranoitratacademy.com/api/predict" \
  -H "Content-Type: application/json" \
  -d '{"domains": ["test.com"]}'
```

## Troubleshooting Common Issues

### Issue 1: Pi-hole Not Accessible

**Symptoms**: `/pihole/` endpoint returns 502 or connection errors

**Solutions**:
```bash
# Check SSH tunnel status
sudo systemctl status pihole-tunnel

# Restart tunnel if needed
sudo systemctl restart pihole-tunnel

# Test local tunnel connection
curl http://localhost:8888/admin/api.php

# Check Pi-hole is running on Raspberry Pi
ssh pi@192.168.100.18 "pihole status"
```

### Issue 2: API Predict Endpoint Blocked

**Symptoms**: 403 Forbidden when accessing `/api/predict`

**Solutions**:
```bash
# Check your Pi's actual IP address
ssh pi@192.168.100.18 "hostname -I"

# Update Nginx configuration if IP changed
sudo nano /etc/nginx/sites-available/ad-filter
# Update the "allow" directive with correct IP

# Reload Nginx
sudo nginx -t && sudo systemctl reload nginx
```

### Issue 3: SSL Certificate Issues

**Symptoms**: HTTPS not working, certificate errors

**Solutions**:
```bash
# Install Certbot if not already installed
sudo apt install certbot python3-certbot-nginx

# Get SSL certificate for your domain
sudo certbot --nginx -d api.quranoitratacademy.com

# The certificate paths are already configured in Nginx
```

### Issue 4: Service Not Starting

**Symptoms**: ad-filter-api service fails to start

**Solutions**:
```bash
# Check service logs
sudo journalctl -u ad-filter-api -f

# Common fixes:
# 1. Check Python virtual environment
cd /home/$(whoami)/ad_filter_system
source venv/bin/activate
python --version

# 2. Install missing dependencies
pip install -r requirements.txt

# 3. Check port availability
sudo netstat -tuln | grep 8081

# 4. Restart service
sudo systemctl restart ad-filter-api
```

## Raspberry Pi Bridge Setup

### 1. Copy Bridge Script to Pi

```bash
# From your VPS, copy the bridge script to Pi
scp raspberry_pi_bridge.py pi@192.168.100.18:/home/pi/ad_filter_bridge/

# SSH to Pi and set up the bridge
ssh pi@192.168.100.18
cd /home/pi/ad_filter_bridge

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install requests schedule python-dotenv

# Create environment file
nano .env
```

### 2. Configure Bridge Environment

```bash
# Add to .env on Raspberry Pi:
ML_API_URL=https://api.quranoitratacademy.com/api/predict
PIHOLE_LOG_PATH=/var/log/pihole.log
PIHOLE_FTL_DB=/etc/pihole/pihole-FTL.db
PIHOLE_GRAVITY_DB=/etc/pihole/gravity.db
BRIDGE_DB_PATH=/home/pi/bridge_data.db
LOG_FILE=/var/log/pihole_bridge.log
CHECK_INTERVAL=300
BATCH_SIZE=100
CONFIDENCE_THRESHOLD=0.7
```

### 3. Set Up Bridge Service

```bash
# Create systemd service on Pi
sudo nano /etc/systemd/system/pihole-bridge.service

# Add service configuration (see raspberry_pi_setup.md for details)

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable pihole-bridge.service
sudo systemctl start pihole-bridge.service
```

## Testing the Complete System

### 1. Test API Endpoints

```bash
# Health check
curl https://api.quranoitratacademy.com/api/health

# Dashboard access
curl https://api.quranoitratacademy.com/

# Pi-hole proxy (should work after SSH tunnel is active)
curl https://api.quranoitratacademy.com/pihole/api.php
```

### 2. Test ML Prediction

```bash
# From your Pi (should work due to IP allowlist)
curl -X POST "https://api.quranoitratacademy.com/api/predict" \
  -H "Content-Type: application/json" \
  -d '{"domains": ["ads.google.com", "github.com"]}'
```

### 3. Monitor Logs

```bash
# VPS API logs
sudo journalctl -u ad-filter-api -f

# SSH tunnel logs
sudo journalctl -u pihole-tunnel -f

# Pi bridge logs (on Raspberry Pi)
ssh pi@192.168.100.18 "tail -f /var/log/pihole_bridge.log"
```

## Security Considerations

1. **SSH Key Security**: The SSH tunnel uses key-based authentication. Keep your private keys secure.

2. **API Access Control**: The `/api/predict` endpoint is restricted to your Pi-hole IP range.

3. **SSL/TLS**: Ensure your SSL certificates are properly configured and renewed.

4. **Firewall**: The deployment script configures UFW to allow necessary ports only.

## Maintenance

### Regular Tasks

```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Restart services after updates
sudo systemctl restart ad-filter-api nginx pihole-tunnel

# Check service health
sudo systemctl status ad-filter-api nginx pihole-tunnel

# Monitor disk space
df -h

# Check logs for errors
sudo journalctl -u ad-filter-api --since "1 hour ago" | grep ERROR
```

### SSL Certificate Renewal

```bash
# Certbot should auto-renew, but you can test:
sudo certbot renew --dry-run

# Manual renewal if needed:
sudo certbot renew
sudo systemctl reload nginx
```

## Support

If you encounter issues:

1. Check the service logs first
2. Verify network connectivity between VPS and Pi
3. Ensure Pi-hole is running and accessible
4. Test each component individually
5. Check firewall and security group settings

The system should now work perfectly with your Pi-hole API v6 setup and domain configuration!

