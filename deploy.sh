#!/bin/bash

# Ad Filter System Deployment Script
# This script sets up the FastAPI ad filtering system on your VPS

set -e

echo "🚀 Starting Ad Filter System Deployment..."

# Configuration
PROJECT_DIR="/home/$(whoami)/ad_filter_system"
SERVICE_USER=$(whoami)
VENV_PATH="$PROJECT_DIR/venv"
LOG_DIR="/var/log"

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

# Check if running as root
if [ "$EUID" -eq 0 ]; then
    print_error "Please don't run this script as root. Run as your regular user."
    exit 1
fi

# Update system packages
print_status "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# Install required system packages
print_status "Installing system dependencies..."
sudo apt install -y python3 python3-pip python3-venv nginx sqlite3 curl

# Create project directory if it doesn't exist
if [ ! -d "$PROJECT_DIR" ]; then
    print_error "Project directory $PROJECT_DIR not found!"
    print_error "Please ensure you've copied the project files to this location."
    exit 1
fi

cd "$PROJECT_DIR"

# Create virtual environment
print_status "Creating Python virtual environment..."
python3 -m venv "$VENV_PATH"
source "$VENV_PATH/bin/activate"

# Install Python dependencies
print_status "Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# Create necessary directories
print_status "Creating necessary directories..."
mkdir -p data models static templates logs

# Set up environment file
if [ ! -f ".env" ]; then
    print_status "Creating environment file..."
    cp .env.example .env
    print_warning "Please edit .env file with your Pi-hole configuration!"
fi

# Set up logging
print_status "Setting up logging..."
sudo touch "$LOG_DIR/ad_filter_api.log"
sudo chown "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR/ad_filter_api.log"
sudo chmod 644 "$LOG_DIR/ad_filter_api.log"

# Create systemd service file
print_status "Creating systemd service..."
sudo tee /etc/systemd/system/ad-filter-api.service > /dev/null <<EOF
[Unit]
Description=Ad Filter API Service
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$PROJECT_DIR
Environment="PATH=$VENV_PATH/bin"
EnvironmentFile=$PROJECT_DIR/.env
ExecStart=$VENV_PATH/bin/uvicorn main:app --host 0.0.0.0 --port 8081 --workers 4
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Create nginx configuration
print_status "Creating Nginx configuration..."
sudo tee /etc/nginx/sites-available/ad-filter > /dev/null <<'EOF'
# HTTP server - redirect to HTTPS
server {
    listen 80;
    server_name api.quranoitratacademy.com;

    # Redirect all HTTP traffic to HTTPS
    return 301 https://$host$request_uri;
}

# HTTPS server
server {
    listen 443 ssl;
    server_name api.quranoitratacademy.com;

    # SSL configuration (managed by Certbot)
    ssl_certificate /etc/letsencrypt/live/api.quranoitratacademy.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.quranoitratacademy.com/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;
    add_header Content-Security-Policy "default-src 'self' http: https: data: blob: 'unsafe-inline'" always;

    # Gzip compression
    gzip on;
    gzip_vary on;
    gzip_min_length 1024;
    gzip_proxied expired no-cache no-store private auth;
    gzip_types text/plain text/css text/xml text/javascript application/x-javascript application/xml+rss application/json;

    # Rate limiting for API endpoints
    location /api/ {
        limit_req zone=api burst=20 nodelay;
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Restrict /api/predict to Pi-hole network range
    location /api/predict {
        # Allow Pi-hole IP address (update as needed)
        allow 192.168.100.18;
        # Allow common private network ranges for Pi-hole
        allow 192.168.0.0/16;
        allow 10.0.0.0/8;
        allow 172.16.0.0/12;
        # Allow localhost for testing
        allow 127.0.0.1;
        deny all;
        
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Forward requests to Pi-hole via SSH tunnel
    location /pihole/ {
        proxy_pass http://127.0.0.1:8888/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Handle Pi-hole API v6 specific headers
        proxy_set_header X-Pi-hole-Authenticate $http_x_pi_hole_authenticate;
    }

    # Dashboard and static files
    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support for real-time updates
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

# Configure nginx rate limiting
print_status "Configuring Nginx rate limiting..."
sudo tee /etc/nginx/conf.d/rate-limit.conf > /dev/null <<EOF
# Rate limiting zones
limit_req_zone \$binary_remote_addr zone=api:10m rate=10r/s;
limit_req_zone \$binary_remote_addr zone=login:10m rate=5r/m;
EOF

# Enable nginx site
print_status "Enabling Nginx site..."
sudo ln -sf /etc/nginx/sites-available/ad-filter /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default

# Test nginx configuration
print_status "Testing Nginx configuration..."
sudo nginx -t

# Configure firewall
print_status "Configuring firewall..."
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

# Start and enable services
print_status "Starting services..."
sudo systemctl daemon-reload
sudo systemctl enable ad-filter-api
sudo systemctl start ad-filter-api
sudo systemctl enable nginx
sudo systemctl restart nginx

# Check service status
print_status "Checking service status..."
sleep 5

if sudo systemctl is-active --quiet ad-filter-api; then
    print_status "✅ Ad Filter API service is running"
else
    print_error "❌ Ad Filter API service failed to start"
    sudo systemctl status ad-filter-api
fi

if sudo systemctl is-active --quiet nginx; then
    print_status "✅ Nginx service is running"
else
    print_error "❌ Nginx service failed to start"
    sudo systemctl status nginx
fi

# Get server IP
SERVER_IP=$(curl -s ifconfig.me || curl -s ipinfo.io/ip || echo "Unable to detect IP")

print_status "🎉 Deployment completed!"
echo ""
echo "📋 Next Steps:"
echo "1. Edit $PROJECT_DIR/.env with your Pi-hole configuration"
echo "2. Update Nginx config with your Pi-hole IP address:"
echo "   sudo nano /etc/nginx/sites-available/ad-filter"
echo "3. Restart services:"
echo "   sudo systemctl restart ad-filter-api nginx"
echo ""
echo "🌐 Access your dashboard at: http://$SERVER_IP"
echo "🔑 Default login: admin / admin123"
echo ""
echo "🧪 Test API endpoint:"
echo "curl -X POST \"http://$SERVER_IP/api/predict\" \\"
echo "  -H \"Content-Type: application/json\" \\"
echo "  -d '{\"domains\": [\"ads.example.com\", \"safe.example.com\"]}'"
echo ""
echo "📊 Check service status:"
echo "sudo systemctl status ad-filter-api"
echo "sudo journalctl -u ad-filter-api -f"
echo ""
print_warning "Remember to configure SSL/HTTPS for production use!"

