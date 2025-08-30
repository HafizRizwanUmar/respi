"""
Enhanced FastAPI Ad Filtering System
Provides ML-based ad detection, Pi-hole integration, and admin dashboard
"""

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
import requests
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
PIHOLE_URL = os.getenv("PIHOLE_URL", "http://192.168.1.100/admin/api.php")
PIHOLE_TOKEN = os.getenv("PIHOLE_TOKEN", "")
REQUEST_TIMEOUT = 10
MODEL_PATH = "models"
DATABASE_PATH = "data/ad_filter.db"

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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

# Database initialization
def init_database():
    """Initialize SQLite database for storing logs and settings."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Create tables
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
    
    # Create default admin user if not exists
    cursor.execute('SELECT COUNT(*) FROM users WHERE username = ?', ('admin',))
    if cursor.fetchone()[0] == 0:
        password_hash = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cursor.execute(
            'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
            ('admin', password_hash, 'admin')
        )
    
    conn.commit()
    conn.close()

# ML Model class
class AdFilterModel:
    def __init__(self):
        self.vectorizer = None
        self.classifier = None
        self.model_loaded = False
        self.load_or_train_model()
    
    def load_or_train_model(self):
        """Load existing model or train a new one."""
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
        """Train the ML model with sample data."""
        logger.info("Training new ML model...")
        
        # Sample training data (in production, use real data)
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
        
        # Create training dataset
        domains = ad_domains + safe_domains
        labels = [1] * len(ad_domains) + [0] * len(safe_domains)
        
        # Train vectorizer and classifier
        self.vectorizer = TfidfVectorizer(analyzer='char', ngram_range=(2, 4), max_features=1000)
        X = self.vectorizer.fit_transform(domains)
        
        self.classifier = RandomForestClassifier(n_estimators=100, random_state=42)
        self.classifier.fit(X, labels)
        
        # Save model
        joblib.dump(self.vectorizer, f"{MODEL_PATH}/vectorizer.pkl")
        joblib.dump(self.classifier, f"{MODEL_PATH}/classifier.pkl")
        
        self.model_loaded = True
        logger.info("ML model trained and saved successfully")
    
    def predict(self, domains: List[str]) -> Dict[str, float]:
        """Predict if domains are ads."""
        if not self.model_loaded:
            return {}
        
        try:
            X = self.vectorizer.transform(domains)
            probabilities = self.classifier.predict_proba(X)
            
            results = {}
            for i, domain in enumerate(domains):
                # Get probability of being an ad (class 1)
                ad_probability = probabilities[i][1] if len(probabilities[i]) > 1 else 0.0
                results[domain] = float(ad_probability)
            
            return results
        except Exception as e:
            logger.error(f"Prediction error: {e}")
            return {}

# Initialize components
init_database()
ml_model = AdFilterModel()

# Authentication functions
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against hash."""
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def authenticate_user(username: str, password: str) -> Optional[Dict]:
    """Authenticate user credentials."""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT username, password_hash, role FROM users WHERE username = ?', (username,))
    user = cursor.fetchone()
    conn.close()
    
    if user and verify_password(password, user[1]):
        return {"username": user[0], "role": user[2]}
    return None

def create_access_token(data: dict) -> str:
    """Create a simple access token."""
    return hashlib.sha256(f"{data['username']}{secrets.token_hex(16)}".encode()).hexdigest()

# Pi-hole integration functions
async def fetch_pihole_summary() -> Dict:
    """Fetch Pi-hole summary statistics."""
    try:
        response = requests.get(f"{PIHOLE_URL}?summary", timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        logger.info("Fetched Pi-hole summary successfully")
        return data
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Pi-hole summary: {e}")
        return {}

async def fetch_pihole_query_log(limit: int = 100) -> List[Dict]:
    """Fetch recent Pi-hole query logs."""
    try:
        response = requests.get(
            f"{PIHOLE_URL}?getQueryLog&limit={limit}&auth={PIHOLE_TOKEN}",
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
        logger.info(f"Fetched {limit} query logs")
        return data.get('data', [])
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Pi-hole query log: {e}")
        return []

async def add_to_pihole_blocklist(domain: str) -> bool:
    """Add domain to Pi-hole blocklist."""
    try:
        response = requests.post(
            f"{PIHOLE_URL}?list=black&add={domain}&auth={PIHOLE_TOKEN}",
            timeout=REQUEST_TIMEOUT
        )
        response.raise_for_status()
        logger.info(f"Added {domain} to Pi-hole blocklist")
        return True
    except requests.RequestException as e:
        logger.error(f"Failed to add {domain} to Pi-hole blocklist: {e}")
        return False

# API Routes
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Main dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})

@app.post("/api/login")
async def login(login_data: LoginRequest):
    """User login endpoint."""
    user = authenticate_user(login_data.username, login_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    token = create_access_token(user)
    return {"access_token": token, "token_type": "bearer", "user": user}

@app.post("/api/predict", response_model=DomainResponse)
async def predict_domains(request: DomainRequest):
    """ML prediction endpoint for domain analysis."""
    try:
        # Get ML predictions
        predictions = ml_model.predict(request.domains)
        
        # Determine which domains to block (threshold: 0.7)
        block_domains = [domain for domain, score in predictions.items() if score > 0.7]
        
        # Log predictions to database
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        for domain in request.domains:
            score = predictions.get(domain, 0.0)
            cursor.execute(
                'INSERT INTO query_logs (domain, query_type, status, ml_score) VALUES (?, ?, ?, ?)',
                (domain, 'A', 'blocked' if score > 0.7 else 'allowed', score)
            )
        
        conn.commit()
        conn.close()
        
        logger.info(f"Analyzed {len(request.domains)} domains, blocking {len(block_domains)}")
        
        return DomainResponse(
            block_domains=block_domains,
            analysis=predictions
        )
    
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        raise HTTPException(status_code=500, detail="Prediction failed")

@app.get("/api/stats")
async def get_stats():
    """Get system statistics."""
    try:
        # Get Pi-hole stats
        pihole_stats = await fetch_pihole_summary()
        
        # Get database stats
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM query_logs WHERE timestamp > datetime("now", "-24 hours")')
        queries_today = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM query_logs WHERE status = "blocked" AND timestamp > datetime("now", "-24 hours")')
        blocked_today = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(*) FROM blocked_domains')
        total_blocked_domains = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            "pihole": pihole_stats,
            "ml_stats": {
                "queries_today": queries_today,
                "blocked_today": blocked_today,
                "total_blocked_domains": total_blocked_domains,
                "block_rate": (blocked_today / queries_today * 100) if queries_today > 0 else 0
            }
        }
    
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch stats")

@app.get("/api/recent-queries")
async def get_recent_queries(limit: int = 50):
    """Get recent query logs."""
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
    """Add or remove domains from blocklist."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        if request.action == "add":
            # Add to local database
            cursor.execute(
                'INSERT OR IGNORE INTO blocked_domains (domain, source) VALUES (?, ?)',
                (request.domain, 'manual')
            )
            
            # Add to Pi-hole
            success = await add_to_pihole_blocklist(request.domain)
            
            conn.commit()
            conn.close()
            
            if success:
                return {"message": f"Domain {request.domain} added to blocklist"}
            else:
                return {"message": f"Domain {request.domain} added locally but failed to sync with Pi-hole"}
        
        elif request.action == "remove":
            cursor.execute('DELETE FROM blocked_domains WHERE domain = ?', (request.domain,))
            conn.commit()
            conn.close()
            
            return {"message": f"Domain {request.domain} removed from blocklist"}
        
        else:
            raise HTTPException(status_code=400, detail="Invalid action")
    
    except Exception as e:
        logger.error(f"Blocklist management error: {e}")
        raise HTTPException(status_code=500, detail="Failed to manage blocklist")

@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "ml_model_loaded": ml_model.model_loaded,
        "pihole_connected": bool(await fetch_pihole_summary())
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

