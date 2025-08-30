#!/usr/bin/env python3
"""
Raspberry Pi Bridge Agent for Ad Filter System
Connects Pi-hole with the cloud-based ML API for real-time ad filtering
"""

import os
import time
import logging
import sqlite3
from datetime import datetime, timedelta
from typing import List, Dict
import requests
import schedule
from pathlib import Path

# ⚡ Load .env file
from dotenv import load_dotenv
load_dotenv()

# Configuration
PIHOLE_LOG_PATH = "/var/log/pihole.log"
PIHOLE_FTL_DB = "/etc/pihole/pihole-FTL.db"
PIHOLE_GRAVITY_DB = "/etc/pihole/gravity.db"

# ⚡ Read ML API URL from .env (fallback if missing)
ML_API_URL = os.getenv("ML_API_URL", "http://localhost:8000/api/predict")

BRIDGE_DB_PATH = "/home/pi/bridge_data.db"
LOG_FILE = "/var/log/pihole_bridge.log"
CHECK_INTERVAL = 300  # 5 minutes
BATCH_SIZE = 100
CONFIDENCE_THRESHOLD = 0.7

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PiHoleBridge:
    """Bridge between Pi-hole and ML API for enhanced ad filtering."""
    
    def __init__(self):
        self.last_check_time = datetime.now() - timedelta(hours=1)
        self.processed_domains = set()
        self.init_database()
        
    def init_database(self):
        """Initialize local database for tracking processed domains."""
        Path(BRIDGE_DB_PATH).parent.mkdir(exist_ok=True)
        
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_domains (
                domain TEXT PRIMARY KEY,
                first_seen DATETIME,
                last_checked DATETIME,
                ml_score REAL,
                status TEXT,
                times_queried INTEGER DEFAULT 1
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS ml_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT,
                ml_score REAL,
                suggested_action TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                applied BOOLEAN DEFAULT 0
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bridge_stats (
                date TEXT PRIMARY KEY,
                domains_analyzed INTEGER DEFAULT 0,
                domains_blocked INTEGER DEFAULT 0,
                api_calls INTEGER DEFAULT 0,
                errors INTEGER DEFAULT 0
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Bridge database initialized")

    def process_queries(self):
        """Check Pi-hole queries, send to ML API, and update local DB."""
        logger.info("Processing queries...")

        if not Path(PIHOLE_FTL_DB).exists():
            logger.info("Pi-hole DB not found, skipping query processing")
            return

        try:
            conn = sqlite3.connect(PIHOLE_FTL_DB)
            cursor = conn.cursor()
            timestamp_threshold = int(self.last_check_time.timestamp())

            cursor.execute('''
                SELECT domain, timestamp, status, client
                FROM queries
                WHERE timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (timestamp_threshold, BATCH_SIZE))

            domains = [row[0] for row in cursor.fetchall()]
            conn.close()

            unique_domains = list(set(domains))
            logger.info(f"Found {len(unique_domains)} new domains to analyze")

            if not unique_domains:
                return

            # Call ML API
            try:
                response = requests.post(
                    ML_API_URL,
                    json={"domains": unique_domains},
                    timeout=15
                )
                response.raise_for_status()
                result = response.json()
                logger.info(f"ML API result: {result}")
            except Exception as e:
                logger.error(f"ML API request failed: {e}")

        except Exception as e:
            logger.error(f"process_queries failed: {e}")

        self.last_check_time = datetime.now()

    def cleanup_old_data(self):
        """Clean up old records in local bridge DB."""
        logger.info("Cleaning up old data...")
        try:
            conn = sqlite3.connect(BRIDGE_DB_PATH)
            cursor = conn.cursor()

            cursor.execute('''
                DELETE FROM processed_domains 
                WHERE last_checked < datetime('now', '-30 days')
            ''')

            cursor.execute('''
                DELETE FROM ml_suggestions 
                WHERE timestamp < datetime('now', '-7 days')
            ''')

            conn.commit()
            conn.close()
            logger.info("Old data cleaned successfully")
        except Exception as e:
            logger.error(f"cleanup_old_data failed: {e}")

    def get_stats(self):
        """Return DB stats for health check."""
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM processed_domains")
        total = cursor.fetchone()[0]
        conn.close()
        return {"total_domains_processed": total}

    def run_health_check(self):
        """Perform health check and report status."""
        logger.info("Performing health check")
        
        health_status = {
            'timestamp': datetime.now().isoformat(),
            'pihole_accessible': False,
            'ml_api_accessible': False,
            'database_accessible': False,
            'stats': {}
        }
        
        # ⚡ Check Pi-hole database only if file exists
        if Path(PIHOLE_FTL_DB).exists():
            try:
                conn = sqlite3.connect(PIHOLE_FTL_DB)
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM queries LIMIT 1')
                conn.close()
                health_status['pihole_accessible'] = True
            except Exception as e:
                logger.error(f"Pi-hole database check failed: {e}")
        else:
            logger.info("Pi-hole not detected, skipping Pi-hole DB check")

        # Check ML API access
        try:
            response = requests.get(f"{ML_API_URL.replace('/predict', '/health')}", timeout=10)
            health_status['ml_api_accessible'] = response.status_code == 200
        except Exception as e:
            logger.error(f"ML API health check failed: {e}")
        
        # Check bridge database
        try:
            health_status['stats'] = self.get_stats()
            health_status['database_accessible'] = True
        except Exception as e:
            logger.error(f"Bridge database check failed: {e}")
        
        logger.info(f"Health check completed: {health_status}")
        return health_status

def main():
    """Main function to run the bridge agent."""
    logger.info("Starting Pi-hole Bridge Agent")
    
    # Initialize bridge
    bridge = PiHoleBridge()
    
    # Schedule tasks
    schedule.every(5).minutes.do(bridge.process_queries)
    schedule.every().hour.do(bridge.run_health_check)
    schedule.every().day.at("02:00").do(bridge.cleanup_old_data)
    
    # Initial health check
    bridge.run_health_check()
    
    logger.info("Bridge agent started, entering main loop")
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    except KeyboardInterrupt:
        logger.info("Bridge agent stopped by user")
    except Exception as e:
        logger.error(f"Bridge agent crashed: {e}")
        raise

if __name__ == "__main__":
    main()
