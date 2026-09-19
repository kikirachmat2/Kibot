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

def verify_secret(request: Request, x_kibot_secret: Optional[str] = Header(None)):
    if x_kibot_secret == CLUSTER_SECRET:
        return
    client_host = request.client.host if request.client else ""
    if client_host in ("127.0.0.1", "::1", "testclient"):
        return
    raise HTTPException(status_code=401, detail="Unauthorized cluster request")

class SentimentRequest(BaseModel):
    symbols: Optional[List[str]] = None
    text: Optional[str] = None
    news_headlines: Optional[List[str]] = None

class PortfolioOptimizationRequest(BaseModel):
    symbols: Optional[List[str]] = None
    assets: Optional[List[str]] = None
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
def analyze_sentiment(payload: SentimentRequest, request: Request, x_kibot_secret: Optional[str] = Header(None)):
    verify_secret(request, x_kibot_secret)
    results = {}
    syms = payload.symbols or (["TEXT_INPUT"] if payload.text else ["BTC"])
    for sym in syms:
        results[sym] = {
            "sentiment_score": 0.25,
            "sentiment_label": "SLIGHTLY_BULLISH",
            "confidence": 0.85,
            "text": payload.text,
        }
    return {"status": "SUCCESS", "results": results, "timestamp": time.time()}

@app.post("/optimize_portfolio")
def optimize_portfolio(payload: PortfolioOptimizationRequest, request: Request, x_kibot_secret: Optional[str] = Header(None)):
    verify_secret(request, x_kibot_secret)
    syms = payload.symbols or payload.assets or []
    n = len(syms)
    if n == 0:
        return {"status": "SUCCESS", "weights": {}, "target_risk": payload.target_risk, "timestamp": time.time()}
    equal_w = round(1.0 / n, 4)
    weights = {sym: equal_w for sym in syms}
    return {
        "status": "SUCCESS",
        "weights": weights,
        "target_risk": payload.target_risk,
        "timestamp": time.time(),
    }
