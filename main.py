import os
import logging
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import json
import hashlib
import secrets
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Depends, Request, Form, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pandas as pd
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier
import joblib
import sqlite3
import bcrypt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/ad_filter_api.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
REQUEST_TIMEOUT = 10
MODEL_PATH = "models"
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/ad_filter.db")  # Use env for Azure

# Stored synced stats (global for simplicity; use DB/Redis in prod)
pihole_stats: Dict = {}
ml_stats: Dict = {}

# Create directories
Path(MODEL_PATH).mkdir(exist_ok=True)
Path("data").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)
Path("templates").mkdir(exist_ok=True)

# FastAPI app
app = FastAPI(
    title="Ad Filter System API",
    description="ML-powered ad filtering with Pi-hole integration",
    version="1.0.0"
)

# CORS middleware
allowed_origins = [
    "https://quranoitratacademy.com",
    "https://www.quranoitratacademy.com",
    "https://api.quranoitratacademy.com"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Security
security = HTTPBearer()

# Pydantic models
class DomainRequest(BaseModel):
    domains: List[str]

class DomainResponse(BaseModel):
    block_domains: List[str]
    analysis: Dict[str, float]

class LoginRequest(BaseModel):
    username: str
    password: str

class BlocklistRequest(BaseModel):
    domain: str
    action: str  # "add" or "remove"

class QueryLog(BaseModel):
    queries: List[Dict]

# Database initialization
def init_database():
    """Initialize SQLite database for storing logs and settings."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()

    # Create tables (added client_ip)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS query_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            domain TEXT NOT NULL,
            client_ip TEXT,
            query_type TEXT,
            status TEXT,
            ml_score REAL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocked_domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT UNIQUE NOT NULL,
            added_by TEXT DEFAULT 'admin',
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT DEFAULT 'manual'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_hash TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_used DATETIME,
            is_active BOOLEAN DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ml_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL,
            ml_score REAL,
            suggested_action TEXT,
            applied INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create default admin user if not exists (change password in prod)
    cursor.execute('SELECT COUNT(*) FROM users WHERE username = ?', ('admin',))
    if cursor.fetchone()[0] == 0:
        password_hash = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
            ('admin', password_hash, 'admin')
        )

    conn.commit()
    conn.close()

# ML Model class (no changes, but train with more data in prod)
class AdFilterModel:
    def __init__(self):
        self.vectorizer = None
        self.classifier = None
        self.model_loaded = False
        self.load_or_train_model()

    def load_or_train_model(self):
        vectorizer_path = f"{MODEL_PATH}/vectorizer.pkl"
        classifier_path = f"{MODEL_PATH}/classifier.pkl"

        if os.path.exists(vectorizer_path) and os.path.exists(classifier_path):
            try:
                self.vectorizer = joblib.load(vectorizer_path)
                self.classifier = joblib.load(classifier_path)
                self.model_loaded = True
                logger.info("ML model loaded successfully")
                return
            except Exception as e:
                logger.error(f"Failed to load model: {e}")

        # Train new model
        self.train_model()

    def train_model(self):
        logger.info("Training new ML model...")

        ad_domains = [
            'ads.google.com', 'doubleclick.net', 'googleadservices.com',
            'googlesyndication.com', 'amazon-adsystem.com', 'facebook.com/tr',
            'analytics.google.com', 'googletagmanager.com', 'scorecardresearch.com',
            'outbrain.com', 'taboola.com', 'adsystem.amazon.com'
        ]
        safe_domains = [
            'google.com', 'youtube.com', 'facebook.com', 'twitter.com',
            'github.com', 'stackoverflow.com', 'wikipedia.org', 'reddit.com',
            'amazon.com', 'netflix.com', 'microsoft.com', 'apple.com'
        ]

        domains = ad_domains + safe_domains
        labels = [1] * len(ad_domains) + [0] * len(safe_domains)

        self.vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=1000)
        X = self.vectorizer.fit_transform(domains)

        self.classifier = RandomForestClassifier(n_estimators=100, random_state=42)
        self.classifier.fit(X, labels)

        joblib.dump(self.vectorizer, f"{MODEL_PATH}/vectorizer.pkl")
        joblib.dump(self.classifier, f"{MODEL_PATH}/classifier.pkl")

        self.model_loaded = True
        logger.info("ML model trained and saved successfully")

    def predict(self, domains: List[str]) -> Dict[str, float]:
        if not self.model_loaded:
            return {}
        try:
            X = self.vectorizer.transform(domains)
            probabilities = self.classifier.predict_proba(X)
            return {d: float(prob[1]) for d, prob in zip(domains, probabilities)}
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return {}

# Initialize components
init_database()
ml_model = AdFilterModel()

# API Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.post("/api/login")
async def login(login_data: LoginRequest):
    """User login endpoint."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT password_hash FROM users WHERE username = ?', (login_data.username,))
    row = cursor.fetchone()
    conn.close()
    if row and bcrypt.checkpw(login_data.password.encode('utf-8'), row[0].encode('utf-8')):
        # Create token (simplified; use JWT in prod)
        token = secrets.token_hex(32)
        return {"access_token": token, "token_type": "bearer"}
    raise HTTPException(status_code=401, detail="Invalid credentials")

@app.post("/api/predict", response_model=DomainResponse)
async def predict_domains(request: DomainRequest):
    """ML prediction endpoint for domain analysis."""
    try:
        predictions = ml_model.predict(request.domains)
        block_domains = [d for d, score in predictions.items() if score > 0.7]

        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        for domain, score in predictions.items():
            suggested_action = "block" if score > 0.7 else "allow"
            cursor.execute(
                'INSERT INTO ml_suggestions (domain, ml_score, suggested_action, applied) VALUES (?, ?, ?, ?)',
                (domain, score, suggested_action, 1 if suggested_action == "block" else 0)
            )

        conn.commit()
        conn.close()

        logger.info(f"Analyzed {len(request.domains)} domains, suggesting block for {len(block_domains)}")

        return DomainResponse(
            block_domains=block_domains,
            analysis=predictions
        )

    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail="Prediction failed")

@app.post("/api/log_queries")
async def log_queries(data: Dict):
    """Receive and log query logs from bridge."""
    queries = data.get("queries", [])
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        for q in queries:
            cursor.execute(
                'INSERT INTO query_logs (domain, timestamp, status, ml_score, client_ip, query_type) VALUES (?, ?, ?, ?, ?, ?)',
                (q["domain"], q["timestamp"], q["status"], q["ml_score"], q.get("client_ip"), 'A')  # Assume type A
            )
        conn.commit()
        conn.close()
        logger.info(f"Logged {len(queries)} queries from bridge")
        return {"status": "logged"}
    except Exception as e:
        logger.error(f"Log queries error: {e}")
        raise HTTPException(status_code=500, detail="Failed to log queries")

@app.post("/api/update_stats")
async def update_stats(data: Dict):
    """Receive stats update from bridge."""
    global pihole_stats, ml_stats
    pihole_stats = data.get("pihole", {})
    ml_stats = data.get("ml_stats", {})
    logger.info("Updated stats from bridge")
    return {"status": "updated"}

@app.get("/api/stats")
async def get_stats():
    """Get system statistics (synced from bridge)."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()

        # Queries in the last 24h (from synced logs)
        cursor.execute('''
            SELECT COUNT(*) 
            FROM query_logs 
            WHERE timestamp > datetime("now", "-24 hours")
        ''')
        queries_today = cursor.fetchone()[0]

        # Blocked
        cursor.execute('''
            SELECT COUNT(*) 
            FROM query_logs 
            WHERE status = "blocked" 
              AND timestamp > datetime("now", "-24 hours")
        ''')
        blocked_today = cursor.fetchone()[0]

        # ML detections (from suggestions)
        cursor.execute('''
            SELECT COUNT(*) 
            FROM ml_suggestions 
            WHERE applied = 1 
              AND timestamp > datetime("now", "-24 hours")
        ''')
        ml_detections_today = cursor.fetchone()[0]

        conn.close()

        # Override with synced ml_stats if available
        synced_ml = ml_stats or {
            "queries_today": queries_today,
            "blocked_today": blocked_today,
            "ml_detections": ml_detections_today,
            "block_rate": (blocked_today / queries_today * 100) if queries_today > 0 else 0
        }

        return {
            "pihole": pihole_stats,
            "ml_stats": synced_ml
        }

    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stats")

@app.get("/api/recent-queries")
async def get_recent_queries(limit: int = 50):
    """Get recent query logs (synced from bridge)."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT domain, timestamp, status, ml_score 
            FROM query_logs 
            ORDER BY timestamp DESC 
            LIMIT ?
        ''', (limit,))
        
        queries = []
        for row in cursor.fetchall():
            queries.append({
                "domain": row[0],
                "timestamp": row[1],
                "status": row[2],
                "ml_score": row[3]
            })
        
        conn.close()
        return {"queries": queries}
    
    except Exception as e:
        logger.error(f"Recent queries error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch recent queries")

@app.post("/api/blocklist")
async def manage_blocklist(request: BlocklistRequest):
    """Add or remove domains from manual blocklist (synced to Pi by bridge)."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        if request.action == "add":
            cursor.execute(
                'INSERT OR IGNORE INTO blocked_domains (domain, source) VALUES (?, ?)',
                (request.domain, 'manual')
            )
            conn.commit()
            conn.close()
            return {"message": f"Domain {request.domain} added to manual blocklist (will sync to Pi-hole)"}
        
        elif request.action == "remove":
            cursor.execute('DELETE FROM blocked_domains WHERE domain = ?', (request.domain,))
            conn.commit()
            conn.close()
            return {"message": f"Domain {request.domain} removed from manual blocklist (will sync to Pi-hole)"}
        
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
    
    except Exception as e:
        logger.error(f"Blocklist management error: {e}")
        raise HTTPException(status_code=500, detail="Failed to manage blocklist")

@app.get("/api/blocklist")
async def get_blocklist():
    """Get manual blocklist for bridge sync."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT domain FROM blocked_domains')
        domains = [row[0] for row in cursor.fetchall()]
        conn.close()
        return {"domains": domains}
    except Exception as e:
        logger.error(f"Get blocklist error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch blocklist")

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "ml_model_loaded": ml_model.model_loaded
    }

if __name__ == "__main__":
    port = int(os.getenv("API_PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info"
    )