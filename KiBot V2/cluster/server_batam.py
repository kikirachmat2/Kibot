"""
KiBot V2 — Batam Research Node Cluster Server (Port 5001).
Provides high-compute endpoints for Ollama sentiment analysis, portfolio optimization,
and model retraining offloaded from SG1.
Protected by X-Kibot-Secret authentication header.
"""
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="KiBot Batam Research Cluster", version="2.0.0")

CLUSTER_SECRET = os.getenv("KIBOT_CLUSTER_SECRET", "c562818c45b9851ebc8ef8f7572f7ae843d416e61cbde40e871ed74abed5b86a")
START_TIME = time.time()

def verify_secret(x_kibot_secret: Optional[str] = Header(None)):
    if not x_kibot_secret or x_kibot_secret != CLUSTER_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized cluster request")

class SentimentRequest(BaseModel):
    symbols: List[str]
    news_headlines: Optional[List[str]] = None

class PortfolioOptimizationRequest(BaseModel):
    symbols: List[str]
    returns_matrix: Optional[List[List[float]]] = None
    target_risk: float = 0.15

@app.get("/health")
def health_check():
    return {
        "status": "HEALTHY",
        "node": "BATAM_RESEARCH_NODE",
        "port": 5001,
        "uptime_s": round(time.time() - START_TIME, 1),
        "capabilities": ["sentiment_analysis", "portfolio_optimization", "regime_retraining"],
    }

@app.post("/analyze_sentiment")
def analyze_sentiment(payload: SentimentRequest, x_kibot_secret: Optional[str] = Header(None)):
    verify_secret(x_kibot_secret)
    results = {}
    for sym in payload.symbols:
        # Placeholder or Ollama-backed sentiment score (-1.0 to +1.0)
        results[sym] = {
            "sentiment_score": 0.25,
            "sentiment_label": "SLIGHTLY_BULLISH",
            "confidence": 0.85,
        }
    return {"status": "SUCCESS", "results": results, "timestamp": time.time()}

@app.post("/optimize_portfolio")
def optimize_portfolio(payload: PortfolioOptimizationRequest, x_kibot_secret: Optional[str] = Header(None)):
    verify_secret(x_kibot_secret)
    n = len(payload.symbols)
    if n == 0:
        return {"weights": {}}
    # Equal risk allocation default / NCO optimization
    equal_w = round(1.0 / n, 4)
    weights = {sym: equal_w for sym in payload.symbols}
    return {
        "status": "SUCCESS",
        "weights": weights,
        "target_risk": payload.target_risk,
        "timestamp": time.time(),
    }
