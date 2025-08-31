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
from typing import Dict
import requests
import schedule
from pathlib import Path
import subprocess

# Load .env file
from dotenv import load_dotenv
load_dotenv()

# Configuration
PIHOLE_FTL_DB = "/etc/pihole/pihole-FTL.db"
PIHOLE_GRAVITY_DB = "/etc/pihole/gravity.db"
ML_API_URL = os.getenv("ML_API_URL", "https://quranoitratacademy.com/api/predict").rstrip("/")
if not ML_API_URL.endswith("/api/predict"):
    ML_API_URL = ML_API_URL + "/api/predict"
BRIDGE_DB_PATH = "/home/pi/bridge_data.db"
LOG_FILE = "/var/log/pihole_bridge.log"

# Settings
BATCH_SIZE = 100
CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", 0.7))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", 15))
VERIFY_SSL = os.getenv("VERIFY_SSL", "true").lower() == "true"  # Default to True for production

# Blocked status codes in Pi-hole (adjust based on Pi-hole docs)
BLOCKED_STATUSES = {1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14}

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

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS manual_blocks (
                domain TEXT PRIMARY KEY
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("Bridge database initialized")

    def process_queries(self):
        """Check Pi-hole queries, send to ML API, update local DB, add to blocklist if blocked, and sync logs to cloud."""
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

            new_queries = cursor.fetchall()
            conn.close()

            if not new_queries:
                return

            unique_domains = list(set(row[0] for row in new_queries))
            logger.info(f"Found {len(new_queries)} new queries ({len(unique_domains)} unique domains) to analyze")

            # Call ML API for predictions on unique domains
            try:
                response = requests.post(
                    ML_API_URL,
                    json={"domains": unique_domains},
                    timeout=REQUEST_TIMEOUT,
                    verify=VERIFY_SSL
                )
                response.raise_for_status()
                result = response.json()
                analysis = result.get('analysis', {})
                logger.info(f"ML API returned results for {len(analysis)} domains")

                # Update local DB and handle blocking
                conn = sqlite3.connect(BRIDGE_DB_PATH)
                cursor = conn.cursor()

                today = datetime.now().strftime("%Y-%m-%d")
                analyzed = len(unique_domains)
                blocked = 0

                for domain in unique_domains:
                    score = analysis.get(domain, 0.0)
                    status = "blocked" if score >= CONFIDENCE_THRESHOLD else "allowed"
                    if status == "blocked":
                        blocked += 1
                        self.add_to_pihole(domain)  # Add to Pi-hole blocklist

                    cursor.execute('''
                        INSERT OR REPLACE INTO processed_domains 
                        (domain, first_seen, last_checked, ml_score, status, times_queried)
                        VALUES (
                            ?, 
                            COALESCE((SELECT first_seen FROM processed_domains WHERE domain=?), datetime("now")),
                            datetime("now"),
                            ?, 
                            ?, 
                            COALESCE((SELECT times_queried FROM processed_domains WHERE domain=?), 0) + 1
                        )
                    ''', (domain, domain, score, status, domain))

                    cursor.execute('''
                        INSERT INTO ml_suggestions (domain, ml_score, suggested_action, applied)
                        VALUES (?, ?, ?, ?)
                    ''', (domain, score, "block" if status == "blocked" else "allow", 1 if status == "blocked" else 0))

                # Update bridge stats
                cursor.execute('''
                    INSERT INTO bridge_stats (date, domains_analyzed, domains_blocked, api_calls, errors)
                    VALUES (?, ?, ?, 1, 0)
                    ON CONFLICT(date) DO UPDATE SET
                        domains_analyzed = domains_analyzed + ?,
                        domains_blocked = domains_blocked + ?,
                        api_calls = api_calls + 1
                ''', (today, analyzed, blocked, analyzed, blocked))

                conn.commit()
                conn.close()

                # Sync query logs to cloud
                self.send_query_logs(new_queries, analysis)

            except Exception as e:
                logger.error(f"ML API request failed: {e}")

        except Exception as e:
            logger.error(f"process_queries failed: {e}")

        self.last_check_time = datetime.now()

    def send_query_logs(self, new_queries, analysis):
        """Send processed query logs to cloud."""
        logs = []
        for query in new_queries:
            domain, ts, pi_status, client = query
            score = analysis.get(domain, 0.0)
            ml_status = "blocked" if score >= CONFIDENCE_THRESHOLD else "allowed"
            pi_status_str = "blocked" if pi_status in BLOCKED_STATUSES else "allowed"
            logs.append({
                "domain": domain,
                "timestamp": datetime.fromtimestamp(ts).isoformat(),
                "status": ml_status,  # Use ML status for consistency with UI
                "ml_score": score,
                "client_ip": client
            })

        try:
            response = requests.post(
                ML_API_URL.replace("/predict", "/log_queries"),
                json={"queries": logs},
                timeout=REQUEST_TIMEOUT,
                verify=VERIFY_SSL
            )
            response.raise_for_status()
            logger.info(f"Synced {len(logs)} query logs to cloud")
        except Exception as e:
            logger.error(f"Failed to sync query logs: {e}")

    def add_to_pihole(self, domain):
        """Add domain to Pi-hole blocklist using CLI."""
        try:
            subprocess.run(["pihole", "-b", domain], check=True, capture_output=True)
            logger.info(f"Added {domain} to Pi-hole blocklist")
        except subprocess.CalledProcessError as e:
            if "already exists" in e.stderr.decode():
                logger.info(f"{domain} already in Pi-hole blocklist")
            else:
                logger.error(f"Failed to add {domain} to Pi-hole: {e}")

    def remove_from_pihole(self, domain):
        """Remove domain from Pi-hole blocklist using CLI."""
        try:
            subprocess.run(["pihole", "-b", "-d", domain], check=True, capture_output=True)
            logger.info(f"Removed {domain} from Pi-hole blocklist")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to remove {domain} from Pi-hole: {e}")

    def sync_blocklist_from_cloud(self):
        """Sync manual blocklist from cloud to local Pi-hole."""
        try:
            response = requests.get(
                ML_API_URL.replace("/predict", "/blocklist"),
                timeout=REQUEST_TIMEOUT,
                verify=VERIFY_SSL
            )
            response.raise_for_status()
            cloud_manual = set(response.json()["domains"])

            conn = sqlite3.connect(BRIDGE_DB_PATH)
            cursor = conn.cursor()
            cursor.execute('SELECT domain FROM manual_blocks')
            local_manual = set(row[0] for row in cursor.fetchall())

            # Add new manual blocks
            for domain in cloud_manual - local_manual:
                self.add_to_pihole(domain)
                cursor.execute('INSERT INTO manual_blocks (domain) VALUES (?)', (domain,))

            # Remove deleted manual blocks
            for domain in local_manual - cloud_manual:
                self.remove_from_pihole(domain)
                cursor.execute('DELETE FROM manual_blocks WHERE domain = ?', (domain,))

            conn.commit()
            conn.close()
            logger.info("Synced manual blocklist from cloud")
        except Exception as e:
            logger.error(f"Blocklist sync failed: {e}")

    def get_pihole_stats(self) -> Dict:
        """Get today's stats from Pi-hole DB."""
        today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
        conn = sqlite3.connect(PIHOLE_FTL_DB)
        cursor = conn.cursor()

        cursor.execute('SELECT COUNT(*) FROM queries WHERE timestamp >= ?', (today_start,))
        dns_queries_today = cursor.fetchone()[0]

        cursor.execute('SELECT COUNT(*) FROM queries WHERE timestamp >= ? AND status IN (1,4,5,6,7,8,9,10,11,12,13,14)', (today_start,))
        ads_blocked_today = cursor.fetchone()[0]

        ads_percentage_today = (ads_blocked_today / dns_queries_today * 100) if dns_queries_today > 0 else 0.0

        conn.close()
        return {
            "dns_queries_today": dns_queries_today,
            "ads_blocked_today": ads_blocked_today,
            "ads_percentage_today": ads_percentage_today
        }

    def get_ml_stats(self) -> Dict:
        """Get today's ML stats from local DB."""
        today = datetime.now().strftime("%Y-%m-%d")
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT domains_analyzed, domains_blocked FROM bridge_stats WHERE date = ?', (today,))
        row = cursor.fetchone()
        conn.close()
        if row:
            analyzed, blocked = row
            return {
                "queries_today": analyzed,  # Unique domains analyzed
                "blocked_today": blocked,
                "block_rate": (blocked / analyzed * 100) if analyzed > 0 else 0.0,
                "ml_detected_today": blocked
            }
        return {
            "queries_today": 0,
            "blocked_today": 0,
            "block_rate": 0.0,
            "ml_detected_today": 0
        }

    def send_stats_to_cloud(self):
        """Send Pi-hole and ML stats to cloud."""
        pihole = self.get_pihole_stats()
        ml = self.get_ml_stats()
        try:
            response = requests.post(
                ML_API_URL.replace("/predict", "/update_stats"),
                json={"pihole": pihole, "ml_stats": ml},
                timeout=REQUEST_TIMEOUT,
                verify=VERIFY_SSL
            )
            response.raise_for_status()
            logger.info("Sent stats to cloud")
        except Exception as e:
            logger.error(f"Failed to send stats to cloud: {e}")

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

    def run_health_check(self):
        """Perform health check and report status."""
        logger.info("Performing health check")

        health_status = {
            'timestamp': datetime.now().isoformat(),
            'pihole_accessible': Path(PIHOLE_FTL_DB).exists(),
            'ml_api_accessible': False,
            'database_accessible': False,
            'stats': {}
        }

        # Check ML API
        try:
            base_url = ML_API_URL.rsplit('/api', 1)[0]
            response = requests.get(f"{base_url}/health", timeout=REQUEST_TIMEOUT, verify=VERIFY_SSL)
            health_status['ml_api_accessible'] = response.status_code == 200
        except Exception as e:
            logger.error(f"ML API health check failed: {e}")

        # Check bridge database
        try:
            health_status['stats'] = self.get_ml_stats()
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
    schedule.every(5).minutes.do(bridge.sync_blocklist_from_cloud)
    schedule.every(1).minutes.do(bridge.send_stats_to_cloud)
    schedule.every().hour.do(bridge.run_health_check)
    schedule.every().day.at("02:00").do(bridge.cleanup_old_data)

    # Initial health check and sync
    bridge.run_health_check()
    bridge.sync_blocklist_from_cloud()
    bridge.send_stats_to_cloud()

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