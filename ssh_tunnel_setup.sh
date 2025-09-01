#!/bin/bash

# SSH Tunnel Setup Script for Pi-hole Connection
# This script sets up an SSH tunnel from VPS to Raspberry Pi for Pi-hole access

set -e

# Configuration
PI_USER="pi"
PI_HOST="192.168.100.18"  # Update with your Pi's IP
PI_PORT="22"
LOCAL_PORT="8888"
REMOTE_PORT="80"  # Pi-hole web interface port
SSH_KEY_PATH="$HOME/.ssh/id_rsa"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if SSH key exists
if [ ! -f "$SSH_KEY_PATH" ]; then
    print_status "Generating SSH key pair..."
    ssh-keygen -t rsa -b 4096 -f "$SSH_KEY_PATH" -N ""
    print_status "SSH key generated at $SSH_KEY_PATH"
    print_warning "Please copy the public key to your Raspberry Pi:"
    echo "ssh-copy-id -i $SSH_KEY_PATH.pub $PI_USER@$PI_HOST"
    echo "Or manually add the following to ~/.ssh/authorized_keys on your Pi:"
    cat "$SSH_KEY_PATH.pub"
    echo ""
    read -p "Press Enter after copying the SSH key to your Pi..."
fi

# Test SSH connection
print_status "Testing SSH connection to Pi..."
if ssh -i "$SSH_KEY_PATH" -o ConnectTimeout=10 -o BatchMode=yes "$PI_USER@$PI_HOST" exit 2>/dev/null; then
    print_status "✅ SSH connection successful"
else
    print_error "❌ SSH connection failed"
    print_error "Please ensure:"
    print_error "1. Your Pi is accessible at $PI_HOST"
    print_error "2. SSH is enabled on your Pi"
    print_error "3. The SSH key is properly installed"
    exit 1
fi

# Create systemd service for SSH tunnel
print_status "Creating SSH tunnel service..."
sudo tee /etc/systemd/system/pihole-tunnel.service > /dev/null <<EOF
[Unit]
Description=SSH Tunnel to Pi-hole
After=network.target

[Service]
Type=simple
User=$(whoami)
ExecStart=/usr/bin/ssh -i $SSH_KEY_PATH -N -L $LOCAL_PORT:localhost:$REMOTE_PORT $PI_USER@$PI_HOST
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Enable and start the tunnel service
print_status "Starting SSH tunnel service..."
sudo systemctl daemon-reload
sudo systemctl enable pihole-tunnel.service
sudo systemctl start pihole-tunnel.service

# Check service status
sleep 5
if sudo systemctl is-active --quiet pihole-tunnel.service; then
    print_status "✅ SSH tunnel service is running"
    print_status "Pi-hole is now accessible at http://localhost:$LOCAL_PORT/admin"
else
    print_error "❌ SSH tunnel service failed to start"
    sudo systemctl status pihole-tunnel.service
    exit 1
fi

# Test tunnel connectivity
print_status "Testing tunnel connectivity..."
if curl -s --connect-timeout 5 "http://localhost:$LOCAL_PORT/admin/api.php" > /dev/null; then
    print_status "✅ Pi-hole API accessible through tunnel"
else
    print_warning "⚠️  Pi-hole API not immediately accessible, this may be normal"
    print_warning "Check Pi-hole status on your Raspberry Pi"
fi

print_status "🎉 SSH tunnel setup completed!"
echo ""
echo "📋 Service Management:"
echo "Check status: sudo systemctl status pihole-tunnel.service"
echo "View logs:    sudo journalctl -u pihole-tunnel.service -f"
echo "Restart:      sudo systemctl restart pihole-tunnel.service"
echo "Stop:         sudo systemctl stop pihole-tunnel.service"
echo ""
echo "🌐 Pi-hole Access:"
echo "Local URL:    http://localhost:$LOCAL_PORT/admin"
echo "Proxy URL:    https://api.quranoitratacademy.com/pihole/"
echo ""
print_warning "Remember to configure your Pi-hole to allow API access from this VPS!"

