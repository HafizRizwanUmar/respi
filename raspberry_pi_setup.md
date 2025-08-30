# Raspberry Pi Setup Guide for Ad Filter System

## Overview

This guide provides comprehensive instructions for setting up your Raspberry Pi as an intelligent network filter that integrates Pi-hole with cloud-based machine learning for enhanced ad blocking capabilities.

## Architecture Overview

The Raspberry Pi serves as the central hub of your ad filtering system, combining:

- **Pi-hole**: Local DNS filtering with static blocklists
- **Bridge Agent**: Python service that connects to your cloud ML API
- **Network Gateway**: Routes all household traffic through the filtering system

## Prerequisites

### Hardware Requirements

- Raspberry Pi 4 Model B (4GB RAM recommended)
- MicroSD card (32GB minimum, Class 10)
- Ethernet cable for stable internet connection
- Power supply (official Raspberry Pi power adapter recommended)

### Network Setup

Your Raspberry Pi will need two network connections:
1. **Ethernet port**: Connected to your router/modem for internet access
2. **WiFi adapter**: Can serve as access point for local devices (optional)

## Step 1: Raspberry Pi OS Installation

### 1.1 Download and Flash OS

```bash
# Download Raspberry Pi Imager
# Visit: https://www.raspberrypi.org/software/

# Flash Raspberry Pi OS Lite (64-bit) to SD card
# Enable SSH and configure WiFi during imaging process
```

### 1.2 Initial Boot and Configuration

```bash
# SSH into your Pi (replace with your Pi's IP)
ssh pi@192.168.1.100

# Update system
sudo apt update && sudo apt upgrade -y

# Configure timezone and locale
sudo raspi-config
# Navigate to: Localisation Options > Timezone
# Navigate to: Localisation Options > Locale

# Enable SSH permanently
sudo systemctl enable ssh
```

## Step 2: Pi-hole Installation

### 2.1 Install Pi-hole

```bash
# Download and run Pi-hole installer
curl -sSL https://install.pi-hole.net | bash

# During installation:
# - Choose your network interface (usually eth0)
# - Select upstream DNS provider (Cloudflare recommended: 1.1.1.1)
# - Choose blocklists (select all recommended lists)
# - Install web admin interface (Yes)
# - Install web server lighttpd (Yes)
# - Log queries (Yes)
# - Privacy mode (Show everything)
```

### 2.2 Configure Pi-hole

```bash
# Set a strong admin password
pihole -a -p

# Note the admin password and web interface URL
# Web interface will be available at: http://your-pi-ip/admin
```

### 2.3 Configure Router DNS Settings

Configure your router to use the Raspberry Pi as the primary DNS server:

1. Access your router's admin panel (usually 192.168.1.1 or 192.168.0.1)
2. Navigate to DHCP/DNS settings
3. Set Primary DNS to your Pi's IP address (e.g., 192.168.1.100)
4. Set Secondary DNS to a public DNS (e.g., 1.1.1.1)
5. Save and restart router

## Step 3: Bridge Agent Installation

### 3.1 Install Python Dependencies

```bash
# Install Python and pip
sudo apt install python3 python3-pip python3-venv git -y

# Create project directory
mkdir -p /home/pi/ad_filter_bridge
cd /home/pi/ad_filter_bridge

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install required packages
pip install requests schedule sqlite3
```

### 3.2 Download Bridge Agent

```bash
# Copy the bridge agent script to your Pi
# You can download it from your VPS or copy via SCP

# Create the bridge script
nano raspberry_pi_bridge.py
# Paste the bridge agent code here

# Make it executable
chmod +x raspberry_pi_bridge.py
```

### 3.3 Configure Bridge Agent

```bash
# Create configuration file
nano .env

# Add configuration:
ML_API_URL=http://your-vps-ip:8000/api/predict
PIHOLE_LOG_PATH=/var/log/pihole.log
PIHOLE_FTL_DB=/etc/pihole/pihole-FTL.db
PIHOLE_GRAVITY_DB=/etc/pihole/gravity.db
BRIDGE_DB_PATH=/home/pi/bridge_data.db
LOG_FILE=/var/log/pihole_bridge.log
CHECK_INTERVAL=300
BATCH_SIZE=100
CONFIDENCE_THRESHOLD=0.7
```

### 3.4 Set Up Logging

```bash
# Create log file
sudo touch /var/log/pihole_bridge.log
sudo chown pi:pi /var/log/pihole_bridge.log
sudo chmod 644 /var/log/pihole_bridge.log

# Set up log rotation
sudo nano /etc/logrotate.d/pihole_bridge

# Add log rotation configuration:
/var/log/pihole_bridge.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    copytruncate
}
```

## Step 4: Service Configuration

### 4.1 Create Systemd Service

```bash
# Create service file
sudo nano /etc/systemd/system/pihole-bridge.service

# Add service configuration:
[Unit]
Description=Pi-hole ML Bridge Agent
After=network.target pihole-FTL.service

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/home/pi/ad_filter_bridge
Environment="PATH=/home/pi/ad_filter_bridge/venv/bin"
EnvironmentFile=/home/pi/ad_filter_bridge/.env
ExecStart=/home/pi/ad_filter_bridge/venv/bin/python raspberry_pi_bridge.py
Restart=always
RestartSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### 4.2 Enable and Start Services

```bash
# Reload systemd
sudo systemctl daemon-reload

# Enable services
sudo systemctl enable pihole-bridge.service

# Start bridge service
sudo systemctl start pihole-bridge.service

# Check service status
sudo systemctl status pihole-bridge.service

# View logs
sudo journalctl -u pihole-bridge.service -f
```

## Step 5: Network Configuration

### 5.1 Configure Static IP

```bash
# Edit dhcpcd configuration
sudo nano /etc/dhcpcd.conf

# Add static IP configuration (adjust for your network):
interface eth0
static ip_address=192.168.1.100/24
static routers=192.168.1.1
static domain_name_servers=127.0.0.1

# Restart networking
sudo systemctl restart dhcpcd
```

### 5.2 Configure Firewall

```bash
# Install and configure UFW
sudo apt install ufw -y

# Allow SSH
sudo ufw allow 22/tcp

# Allow Pi-hole web interface
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Allow DNS
sudo ufw allow 53/tcp
sudo ufw allow 53/udp

# Allow DHCP (if using Pi as DHCP server)
sudo ufw allow 67/udp
sudo ufw allow 68/udp

# Enable firewall
sudo ufw --force enable

# Check status
sudo ufw status
```

## Step 6: Testing and Validation

### 6.1 Test Pi-hole Functionality

```bash
# Test DNS resolution
nslookup google.com 127.0.0.1

# Test ad blocking
nslookup ads.google.com 127.0.0.1

# Check Pi-hole query log
tail -f /var/log/pihole.log
```

### 6.2 Test Bridge Agent

```bash
# Check bridge service status
sudo systemctl status pihole-bridge.service

# View bridge logs
tail -f /var/log/pihole_bridge.log

# Test ML API connectivity
curl -X POST "http://your-vps-ip:8000/api/predict" \
  -H "Content-Type: application/json" \
  -d '{"domains": ["test.com"]}'
```

### 6.3 Validate Network Filtering

```bash
# From a client device, test DNS resolution
nslookup google.com

# Check if queries appear in Pi-hole logs
# Visit Pi-hole admin interface: http://your-pi-ip/admin
```

## Step 7: Advanced Configuration

### 7.1 Custom Blocklists

```bash
# Add custom blocklists to Pi-hole
pihole -b https://someonewhocares.org/hosts/zero/hosts

# Add individual domains
pihole -b malicious-domain.com

# Whitelist trusted domains
pihole -w trusted-domain.com
```

### 7.2 Performance Optimization

```bash
# Optimize Pi-hole database
pihole -f

# Configure DNS cache size
sudo nano /etc/dnsmasq.d/01-pihole.conf
# Add: cache-size=10000

# Restart Pi-hole
sudo systemctl restart pihole-FTL
```

### 7.3 Monitoring Setup

```bash
# Install monitoring tools
sudo apt install htop iotop -y

# Create monitoring script
nano /home/pi/monitor.sh

#!/bin/bash
echo "=== System Status ==="
uptime
echo ""
echo "=== Memory Usage ==="
free -h
echo ""
echo "=== Disk Usage ==="
df -h
echo ""
echo "=== Pi-hole Status ==="
pihole status
echo ""
echo "=== Bridge Status ==="
sudo systemctl status pihole-bridge.service --no-pager
echo ""
echo "=== Recent Bridge Logs ==="
tail -n 10 /var/log/pihole_bridge.log

chmod +x /home/pi/monitor.sh
```

## Step 8: Maintenance and Updates

### 8.1 Regular Maintenance Tasks

```bash
# Update Pi-hole
pihole -up

# Update system packages
sudo apt update && sudo apt upgrade -y

# Update bridge agent dependencies
cd /home/pi/ad_filter_bridge
source venv/bin/activate
pip install --upgrade requests schedule

# Restart services after updates
sudo systemctl restart pihole-bridge.service
sudo systemctl restart pihole-FTL
```

### 8.2 Backup Configuration

```bash
# Create backup script
nano /home/pi/backup.sh

#!/bin/bash
BACKUP_DIR="/home/pi/backups/$(date +%Y%m%d)"
mkdir -p "$BACKUP_DIR"

# Backup Pi-hole configuration
sudo cp -r /etc/pihole "$BACKUP_DIR/"

# Backup bridge configuration
cp -r /home/pi/ad_filter_bridge "$BACKUP_DIR/"

# Backup system configuration
sudo cp /etc/dhcpcd.conf "$BACKUP_DIR/"
sudo cp /etc/systemd/system/pihole-bridge.service "$BACKUP_DIR/"

echo "Backup completed: $BACKUP_DIR"

chmod +x /home/pi/backup.sh

# Run backup weekly
(crontab -l 2>/dev/null; echo "0 2 * * 0 /home/pi/backup.sh") | crontab -
```

## Troubleshooting

### Common Issues and Solutions

#### Bridge Agent Not Starting

```bash
# Check service logs
sudo journalctl -u pihole-bridge.service -n 50

# Common fixes:
# 1. Check Python virtual environment
source /home/pi/ad_filter_bridge/venv/bin/activate
python --version

# 2. Verify dependencies
pip list

# 3. Check configuration file
cat /home/pi/ad_filter_bridge/.env

# 4. Test ML API connectivity
curl -v http://your-vps-ip:8000/api/health
```

#### Pi-hole Not Blocking Ads

```bash
# Check Pi-hole status
pihole status

# Verify DNS settings
cat /etc/resolv.conf

# Check if clients are using Pi-hole
pihole -t

# Update gravity (blocklists)
pihole -g
```

#### Network Connectivity Issues

```bash
# Check network interface
ip addr show

# Test internet connectivity
ping 8.8.8.8

# Check routing
ip route show

# Verify firewall rules
sudo ufw status verbose
```

### Performance Monitoring

```bash
# Monitor system resources
htop

# Check disk I/O
iotop

# Monitor network traffic
sudo netstat -tuln

# Check Pi-hole query volume
pihole -c -e
```

## Security Considerations

### 8.1 Secure SSH Access

```bash
# Change default password
passwd

# Configure SSH key authentication
ssh-keygen -t rsa -b 4096
# Copy public key to authorized_keys

# Disable password authentication
sudo nano /etc/ssh/sshd_config
# Set: PasswordAuthentication no
# Set: PermitRootLogin no

sudo systemctl restart ssh
```

### 8.2 Regular Security Updates

```bash
# Enable automatic security updates
sudo apt install unattended-upgrades -y
sudo dpkg-reconfigure unattended-upgrades

# Configure update notifications
sudo nano /etc/apt/apt.conf.d/50unattended-upgrades
```

### 8.3 Network Security

```bash
# Monitor failed login attempts
sudo tail -f /var/log/auth.log

# Install fail2ban for intrusion prevention
sudo apt install fail2ban -y
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

## Integration with Cloud ML API

The bridge agent automatically:

1. **Monitors Pi-hole queries** in real-time
2. **Extracts unique domains** from DNS logs
3. **Sends batches to ML API** for analysis
4. **Applies ML suggestions** to Pi-hole blocklists
5. **Maintains statistics** and logs for monitoring

### API Communication Flow

```
Pi-hole DNS Query → Bridge Agent → ML API → Analysis → Auto-Block Decision
```

The system ensures:
- **Low latency**: Queries are processed in batches
- **Reliability**: Failed API calls don't affect DNS resolution
- **Privacy**: Only domain names are sent to the API
- **Efficiency**: Domains are cached to avoid duplicate analysis

## Conclusion

Your Raspberry Pi is now configured as an intelligent ad filtering gateway that combines the reliability of Pi-hole with the power of machine learning. The system will continuously learn and adapt to new ad patterns while maintaining fast, reliable DNS resolution for your entire network.

For ongoing support and updates, monitor the bridge agent logs and ensure your VPS ML API remains accessible. The system is designed to be resilient and will continue basic ad blocking even if the ML API is temporarily unavailable.

