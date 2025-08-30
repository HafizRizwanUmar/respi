#!/usr/bin/env python3
"""
Raspberry Pi Bridge Agent for Ad Filter System
Connects Pi-hole with the cloud-based ML API for real-time ad filtering
"""

import os
import time
import logging
import json
import sqlite3
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Set, Optional
import requests
import schedule
from pathlib import Path

# Configuration
PIHOLE_LOG_PATH = "/var/log/pihole.log"
PIHOLE_FTL_DB = "/etc/pihole/pihole-FTL.db"
PIHOLE_GRAVITY_DB = "/etc/pihole/gravity.db"
ML_API_URL = os.getenv("ML_API_URL", "http://api.quranoitratacademy/api/predict")
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
    
    def get_recent_queries(self) -> List[Dict]:
        """Extract recent DNS queries from Pi-hole FTL database."""
        queries = []
        
        try:
            # Connect to Pi-hole FTL database
            conn = sqlite3.connect(PIHOLE_FTL_DB)
            cursor = conn.cursor()
            
            # Get queries since last check
            timestamp_threshold = int(self.last_check_time.timestamp())
            
            cursor.execute('''
                SELECT domain, timestamp, status, client
                FROM queries 
                WHERE timestamp > ? 
                AND status IN (1, 2, 3)  # Allowed queries
                ORDER BY timestamp DESC
                LIMIT ?
            ''', (timestamp_threshold, BATCH_SIZE * 2))
            
            for row in cursor.fetchall():
                domain, timestamp, status, client = row
                queries.append({
                    'domain': domain,
                    'timestamp': datetime.fromtimestamp(timestamp),
                    'status': status,
                    'client': client
                })
            
            conn.close()
            logger.info(f"Retrieved {len(queries)} recent queries")
            
        except sqlite3.Error as e:
            logger.error(f"Failed to read Pi-hole database: {e}")
        except Exception as e:
            logger.error(f"Unexpected error reading queries: {e}")
        
        return queries
    
    def extract_unique_domains(self, queries: List[Dict]) -> List[str]:
        """Extract unique domains that haven't been processed recently."""
        unique_domains = set()
        
        # Get domains from queries
        for query in queries:
            domain = query['domain']
            if domain and not domain.startswith('.') and '.' in domain:
                unique_domains.add(domain.lower())
        
        # Filter out recently processed domains
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        
        filtered_domains = []
        for domain in unique_domains:
            cursor.execute('''
                SELECT last_checked FROM processed_domains 
                WHERE domain = ? AND last_checked > datetime('now', '-1 hour')
            ''', (domain,))
            
            if not cursor.fetchone():  # Not processed in last hour
                filtered_domains.append(domain)
        
        conn.close()
        
        # Limit batch size
        return filtered_domains[:BATCH_SIZE]
    
    def query_ml_api(self, domains: List[str]) -> Dict[str, float]:
        """Send domains to ML API for analysis."""
        if not domains:
            return {}
        
        try:
            response = requests.post(
                ML_API_URL,
                json={"domains": domains},
                timeout=30,
                headers={'Content-Type': 'application/json'}
            )
            response.raise_for_status()
            
            data = response.json()
            analysis = data.get('analysis', {})
            
            # Update stats
            self.update_stats('api_calls', 1)
            
            logger.info(f"ML API analyzed {len(domains)} domains, {len(data.get('block_domains', []))} flagged for blocking")
            return analysis
            
        except requests.RequestException as e:
            logger.error(f"ML API request failed: {e}")
            self.update_stats('errors', 1)
            return {}
        except Exception as e:
            logger.error(f"Unexpected error querying ML API: {e}")
            self.update_stats('errors', 1)
            return {}
    
    def update_processed_domains(self, analysis: Dict[str, float]):
        """Update database with ML analysis results."""
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        
        for domain, score in analysis.items():
            cursor.execute('''
                INSERT OR REPLACE INTO processed_domains 
                (domain, first_seen, last_checked, ml_score, status, times_queried)
                VALUES (?, 
                        COALESCE((SELECT first_seen FROM processed_domains WHERE domain = ?), datetime('now')),
                        datetime('now'), 
                        ?, 
                        ?,
                        COALESCE((SELECT times_queried FROM processed_domains WHERE domain = ?) + 1, 1))
            ''', (domain, domain, score, 'blocked' if score > CONFIDENCE_THRESHOLD else 'allowed', domain))
        
        conn.commit()
        conn.close()
    
    def add_to_pihole_blocklist(self, domains: List[str]) -> int:
        """Add domains to Pi-hole's gravity database."""
        if not domains:
            return 0
        
        added_count = 0
        
        try:
            conn = sqlite3.connect(PIHOLE_GRAVITY_DB)
            cursor = conn.cursor()
            
            for domain in domains:
                try:
                    # Add to gravity database
                    cursor.execute('''
                        INSERT OR IGNORE INTO gravity 
                        (domain, adlist_id) 
                        VALUES (?, 0)
                    ''', (domain,))
                    
                    if cursor.rowcount > 0:
                        added_count += 1
                        logger.info(f"Added {domain} to Pi-hole blocklist")
                        
                        # Record suggestion as applied
                        self.record_ml_suggestion(domain, 'block', applied=True)
                    
                except sqlite3.Error as e:
                    logger.error(f"Failed to add {domain} to blocklist: {e}")
            
            conn.commit()
            conn.close()
            
            # Restart Pi-hole DNS to reload gravity
            if added_count > 0:
                os.system("sudo pihole restartdns reload-lists")
                logger.info(f"Reloaded Pi-hole DNS with {added_count} new blocked domains")
            
        except sqlite3.Error as e:
            logger.error(f"Failed to access gravity database: {e}")
        except Exception as e:
            logger.error(f"Unexpected error adding to blocklist: {e}")
        
        return added_count
    
    def record_ml_suggestion(self, domain: str, action: str, applied: bool = False):
        """Record ML suggestion in database."""
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO ml_suggestions (domain, suggested_action, applied)
            VALUES (?, ?, ?)
        ''', (domain, action, applied))
        
        conn.commit()
        conn.close()
    
    def update_stats(self, metric: str, increment: int = 1):
        """Update daily statistics."""
        today = datetime.now().strftime('%Y-%m-%d')
        
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        
        cursor.execute(f'''
            INSERT OR IGNORE INTO bridge_stats (date, {metric})
            VALUES (?, 0)
        ''', (today,))
        
        cursor.execute(f'''
            UPDATE bridge_stats 
            SET {metric} = {metric} + ?
            WHERE date = ?
        ''', (increment, today))
        
        conn.commit()
        conn.close()
    
    def get_stats(self) -> Dict:
        """Get bridge statistics."""
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        
        # Today's stats
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT domains_analyzed, domains_blocked, api_calls, errors
            FROM bridge_stats WHERE date = ?
        ''', (today,))
        
        today_stats = cursor.fetchone()
        if not today_stats:
            today_stats = (0, 0, 0, 0)
        
        # Total processed domains
        cursor.execute('SELECT COUNT(*) FROM processed_domains')
        total_domains = cursor.fetchone()[0]
        
        # Pending suggestions
        cursor.execute('SELECT COUNT(*) FROM ml_suggestions WHERE applied = 0')
        pending_suggestions = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'today': {
                'domains_analyzed': today_stats[0],
                'domains_blocked': today_stats[1],
                'api_calls': today_stats[2],
                'errors': today_stats[3]
            },
            'total_domains_processed': total_domains,
            'pending_suggestions': pending_suggestions,
            'last_check': self.last_check_time.isoformat()
        }
    
    def process_queries(self):
        """Main processing function - analyze recent queries with ML."""
        logger.info("Starting query processing cycle")
        
        try:
            # Get recent queries
            queries = self.get_recent_queries()
            if not queries:
                logger.info("No new queries to process")
                return
            
            # Extract unique domains
            domains = self.extract_unique_domains(queries)
            if not domains:
                logger.info("No new domains to analyze")
                return
            
            logger.info(f"Analyzing {len(domains)} domains with ML API")
            
            # Query ML API
            analysis = self.query_ml_api(domains)
            if not analysis:
                logger.warning("No analysis results from ML API")
                return
            
            # Update processed domains
            self.update_processed_domains(analysis)
            self.update_stats('domains_analyzed', len(domains))
            
            # Find domains to block
            domains_to_block = [
                domain for domain, score in analysis.items() 
                if score > CONFIDENCE_THRESHOLD
            ]
            
            if domains_to_block:
                logger.info(f"ML suggests blocking {len(domains_to_block)} domains")
                
                # Add to Pi-hole blocklist
                blocked_count = self.add_to_pihole_blocklist(domains_to_block)
                self.update_stats('domains_blocked', blocked_count)
                
                # Record suggestions
                for domain in domains_to_block:
                    self.record_ml_suggestion(domain, 'block', applied=True)
            
            # Update last check time
            self.last_check_time = datetime.now()
            
            logger.info("Query processing cycle completed successfully")
            
        except Exception as e:
            logger.error(f"Error in process_queries: {e}")
            self.update_stats('errors', 1)
    
    def cleanup_old_data(self):
        """Clean up old data from database."""
        logger.info("Cleaning up old data")
        
        conn = sqlite3.connect(BRIDGE_DB_PATH)
        cursor = conn.cursor()
        
        # Remove old processed domains (older than 30 days)
        cursor.execute('''
            DELETE FROM processed_domains 
            WHERE last_checked < datetime('now', '-30 days')
        ''')
        
        # Remove old suggestions (older than 7 days)
        cursor.execute('''
            DELETE FROM ml_suggestions 
            WHERE timestamp < datetime('now', '-7 days')
        ''')
        
        # Remove old stats (older than 90 days)
        cursor.execute('''
            DELETE FROM bridge_stats 
            WHERE date < date('now', '-90 days')
        ''')
        
        conn.commit()
        conn.close()
        
        logger.info("Data cleanup completed")
    
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
        
        # Check Pi-hole database access
        try:
            conn = sqlite3.connect(PIHOLE_FTL_DB)
            cursor = conn.cursor()
            cursor.execute('SELECT COUNT(*) FROM queries LIMIT 1')
            conn.close()
            health_status['pihole_accessible'] = True
        except Exception as e:
            logger.error(f"Pi-hole database check failed: {e}")
        
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

