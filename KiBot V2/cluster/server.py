from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
import os

app = FastAPI()
CLUSTER_SECRET = os.getenv("KIBOT_CLUSTER_SECRET", "change-me")

class AnalyzeRequest(BaseModel):
    pairs: list[str]
    context: str = ""

@app.get("/health")
def health():
    return {"status": "ok", "node": "executor"}

@app.post("/analyze")
def analyze(req: AnalyzeRequest, x_kibot_secret: str = Header(None)):
    if x_kibot_secret != CLUSTER_SECRET:
        raise HTTPException(status_code=401, detail="unauthorized")
    # Skeleton — implementasi detail nanti
    return {"pairs": req.pairs, "analysis": "not_implemented", "confidence": 0.0}
