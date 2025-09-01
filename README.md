# Enhanced Ad Filter System with FastAPI and ML

A comprehensive ad filtering solution that combines Pi-hole with cloud-based machine learning for intelligent, real-time ad detection and blocking.

## 🚀 Features

- **FastAPI Backend**: High-performance API with ML-powered ad detection
- **Modern Dashboard**: Real-time monitoring and management interface
- **Pi-hole Integration**: Seamless connection with existing Pi-hole installations
- **Machine Learning**: Adaptive ad detection using supervised learning
- **Public Accessibility**: Deploy anywhere with full internet access
- **Raspberry Pi Bridge**: Intelligent agent for local network filtering
- **Real-time Analytics**: Live statistics and query monitoring
- **Manual Controls**: Admin interface for blocklist management

## 🏗️ Architecture

```
Internet → Router → Raspberry Pi (Pi-hole + Bridge) → Local Devices
                           ↓
                    Cloud VPS (FastAPI + ML + Dashboard)
```

### Components

1. **VPS Server**: Hosts the FastAPI application with ML capabilities
2. **Raspberry Pi**: Runs Pi-hole and bridge agent for local filtering
3. **Bridge Agent**: Connects Pi-hole with cloud ML API
4. **Admin Dashboard**: Web interface for monitoring and management

## 📋 Prerequisites

### VPS Requirements
- Ubuntu 20.04+ or similar Linux distribution
- 2GB RAM minimum (4GB recommended)
- 20GB storage
- Public IP address
- Python 3.8+

### Raspberry Pi Requirements
- Raspberry Pi 4 Model B (4GB RAM recommended)
- 32GB microSD card (Class 10)
- Ethernet connection
- Raspberry Pi OS Lite

## 🚀 Quick Start

### 1. VPS Deployment

```bash
# Clone or download the project files to your VPS
cd /home/your-username
git clone <your-repo> ad_filter_system
cd ad_filter_system

# Run the deployment script
chmod +x deploy.sh
./deploy.sh

# Configure environment variables
cp .env.example .env
nano .env
# Update PIHOLE_URL and PIHOLE_TOKEN

# Restart services
sudo systemctl restart ad-filter-api nginx
```

### 2. Test Your API

```bash
# Test the API locally
python3 test_api.py

# Test from external machine
python3 test_api.py --url http://YOUR_VPS_IP

# Manual API test
curl -X POST "http://YOUR_VPS_IP/api/predict" \
  -H "Content-Type: application/json" \
  -d '{"domains": ["ads.example.com", "safe.example.com"]}'
```

### 3. Access Dashboard

1. Open your browser and navigate to `http://YOUR_VPS_IP`
2. Login with default credentials:
   - Username: `admin`
   - Password: `admin123`
3. Change the default password immediately

### 4. Raspberry Pi Setup

Follow the detailed guide in `raspberry_pi_setup.md` to:
1. Install Pi-hole on your Raspberry Pi
2. Configure the bridge agent
3. Connect to your VPS API
4. Set up network routing

## 📁 Project Structure

```
ad_filter_system/
├── main.py                 # FastAPI application
├── requirements.txt        # Python dependencies
├── deploy.sh              # VPS deployment script
├── test_api.py            # API testing script
├── .env.example           # Environment variables template
├── templates/
│   └── dashboard.html     # Admin dashboard
├── static/               # Static files (CSS, JS, images)
├── data/                 # Database and logs
├── models/               # ML model files
├── raspberry_pi_bridge.py # Pi bridge agent
├── raspberry_pi_setup.md  # Pi setup guide
└── README.md             # This file
```

## 🔧 Configuration

### Environment Variables

Create a `.env` file with the following variables:

```bash
# Pi-hole Configuration
PIHOLE_URL=http://192.168.1.100/admin/api.php
PIHOLE_TOKEN=your_pihole_api_token

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
DEBUG=False

# Security
SECRET_KEY=your_secret_key_here
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Database
DATABASE_PATH=data/ad_filter.db

# Logging
LOG_LEVEL=INFO
LOG_FILE=/var/log/ad_filter_api.log
```

### Nginx Configuration

The deployment script automatically configures Nginx with:
- Reverse proxy to FastAPI application
- Rate limiting for API endpoints
- Security headers
- Gzip compression

To customize, edit `/etc/nginx/sites-available/ad-filter`

## 🔒 Security

### Default Security Measures

- Rate limiting on API endpoints
- CORS protection
- SQL injection prevention
- Input validation
- Secure password hashing
- Access logging

### Recommended Additional Security

1. **Enable HTTPS**:
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

2. **Restrict API Access**:
Edit Nginx config to allow only your Pi-hole IP:
```nginx
location /api/predict {
    allow 192.168.1.100;  # Your Pi-hole IP
    deny all;
    proxy_pass http://127.0.0.1:8000;
}
```

3. **Change Default Credentials**:
- Login to dashboard
- Navigate to user settings
- Change admin password

## 📊 API Endpoints

### Public Endpoints

- `GET /` - Admin dashboard
- `POST /api/login` - User authentication
- `GET /api/health` - Health check

### Protected Endpoints

- `POST /api/predict` - ML domain analysis
- `GET /api/stats` - System statistics
- `GET /api/recent-queries` - Recent DNS queries
- `POST /api/blocklist` - Manage blocklist

### API Usage Examples

#### Domain Analysis
```bash
curl -X POST "http://your-vps-ip/api/predict" \
  -H "Content-Type: application/json" \
  -d '{
    "domains": [
      "ads.google.com",
      "github.com",
      "malicious-ads.example.com"
    ]
  }'
```

Response:
```json
{
  "block_domains": ["ads.google.com", "malicious-ads.example.com"],
  "analysis": {
    "ads.google.com": 0.95,
    "github.com": 0.02,
    "malicious-ads.example.com": 0.87
  }
}
```

#### Add Domain to Blocklist
```bash
curl -X POST "http://your-vps-ip/api/blocklist" \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "unwanted-ads.com",
    "action": "add"
  }'
```

## 🔍 Monitoring and Logs

### Service Status
```bash
# Check API service
sudo systemctl status ad-filter-api

# Check Nginx
sudo systemctl status nginx

# View API logs
sudo journalctl -u ad-filter-api -f

# View Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### Application Logs
```bash
# API application logs
tail -f /var/log/ad_filter_api.log

# Pi bridge logs (on Raspberry Pi)
tail -f /var/log/pihole_bridge.log
```

### Performance Monitoring
```bash
# System resources
htop

# Network connections
sudo netstat -tuln

# Disk usage
df -h

# Memory usage
free -h
```

## 🧪 Testing

### Automated Testing
```bash
# Run comprehensive API tests
python3 test_api.py

# Test with custom URL
python3 test_api.py --url http://your-vps-ip

# Test specific endpoints
python3 test_api.py --url http://your-vps-ip --username admin --password your-password
```

### Manual Testing

1. **Dashboard Access**: Visit `http://your-vps-ip` and login
2. **API Health**: `curl http://your-vps-ip/api/health`
3. **ML Prediction**: Use the curl examples above
4. **Pi-hole Integration**: Check Pi-hole logs for ML suggestions

### End-to-End Testing

1. Configure Raspberry Pi with bridge agent
2. Generate DNS queries from client devices
3. Verify queries appear in dashboard
4. Check ML analysis results
5. Confirm automatic blocking of flagged domains

## 🔧 Troubleshooting

### Common Issues

#### API Not Accessible
```bash
# Check if service is running
sudo systemctl status ad-filter-api

# Check port binding
sudo netstat -tuln | grep 8000

# Check firewall
sudo ufw status

# Test local access
curl http://localhost:8000/api/health
```

#### Dashboard Not Loading
```bash
# Check Nginx status
sudo systemctl status nginx

# Test Nginx config
sudo nginx -t

# Check Nginx logs
sudo tail -f /var/log/nginx/error.log
```

#### ML Predictions Not Working
```bash
# Check model files
ls -la models/

# Check application logs
tail -f /var/log/ad_filter_api.log

# Test prediction endpoint
curl -X POST "http://localhost:8000/api/predict" \
  -H "Content-Type: application/json" \
  -d '{"domains": ["test.com"]}'
```

#### Pi-hole Integration Issues
```bash
# On Raspberry Pi, check bridge service
sudo systemctl status pihole-bridge

# Check bridge logs
tail -f /var/log/pihole_bridge.log

# Test API connectivity from Pi
curl -X POST "http://your-vps-ip/api/predict" \
  -H "Content-Type: application/json" \
  -d '{"domains": ["test.com"]}'
```

### Performance Issues

#### High CPU Usage
- Check for infinite loops in logs
- Monitor query volume
- Consider increasing server resources

#### High Memory Usage
- Check for memory leaks
- Monitor ML model size
- Restart services if needed

#### Slow API Response
- Check network latency
- Monitor database performance
- Consider caching frequently accessed data

## 🔄 Updates and Maintenance

### Regular Maintenance
```bash
# Update system packages
sudo apt update && sudo apt upgrade -y

# Update Python dependencies
cd /path/to/ad_filter_system
source venv/bin/activate
pip install --upgrade -r requirements.txt

# Restart services
sudo systemctl restart ad-filter-api nginx
```

### Backup
```bash
# Backup database
cp data/ad_filter.db data/ad_filter.db.backup

# Backup configuration
tar -czf backup-$(date +%Y%m%d).tar.gz .env data/ models/
```

### Updates
```bash
# Pull latest code
git pull origin main

# Install new dependencies
pip install -r requirements.txt

# Restart services
sudo systemctl restart ad-filter-api
```

## 🌐 Cloud Platform Alternatives

If you prefer alternatives to your current VPS provider:

### Amazon Web Services (AWS)
- **EC2**: Virtual servers with flexible configurations
- **Elastic IP**: Static IP addresses
- **Security Groups**: Built-in firewall
- **CloudWatch**: Monitoring and logging

### Google Cloud Platform (GCP)
- **Compute Engine**: Virtual machines
- **Cloud DNS**: Managed DNS service
- **Cloud Logging**: Centralized logging
- **Load Balancing**: High availability

### DigitalOcean
- **Droplets**: Simple virtual servers
- **Floating IPs**: Reserved IP addresses
- **Cloud Firewalls**: Network security
- **Monitoring**: Built-in metrics

### Microsoft Azure
- **Virtual Machines**: Scalable compute
- **Public IP**: Static IP addresses
- **Network Security Groups**: Firewall rules
- **Azure Monitor**: Comprehensive monitoring

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For support and questions:

1. Check the troubleshooting section
2. Review application logs
3. Test individual components
4. Create an issue with detailed information

## 🎯 Roadmap

- [ ] Web-based configuration interface
- [ ] Advanced ML model training
- [ ] Multi-tenant support
- [ ] API rate limiting per user
- [ ] Real-time WebSocket updates
- [ ] Mobile app for monitoring
- [ ] Integration with other DNS filters
- [ ] Advanced analytics and reporting

---

**Note**: This system is designed for educational and personal use. Ensure compliance with your local laws and network policies when deploying ad filtering solutions.

#   r e s p i  
 #   r e s p b e r y  
 