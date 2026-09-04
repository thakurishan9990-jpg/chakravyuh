from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
import hashlib
import sys
import os

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "generator"))
from db import (init_db, insert_transaction, insert_many,
                fetch_all_transactions, clear_transactions)
from generator import generate_dataset, CITIES, CATEGORY_RISK

app = FastAPI(title="Mock UPI Gateway")

init_db()


class Transaction(BaseModel):
    sender: str
    receiver: str
    amount: float
    type: str = "deposit"
    timestamp: Optional[str] = None
    is_scam: Optional[bool] = False
    scheme_id: Optional[str] = None
    category: Optional[str] = "p2p"
    city: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/transaction")
def create_transaction(tx: Transaction):
    record = tx.dict()
    record["timestamp"] = record["timestamp"] or datetime.utcnow().isoformat()
    record["is_scam"] = int(record["is_scam"])

    # If a city was given but no coordinates, fill them in
    if record["city"] and record["lat"] is None:
        if record["city"] in CITIES:
            record["lat"], record["lon"] = CITIES[record["city"]]

    insert_transaction(record)
    return {"stored": True, "transaction": record}


@app.get("/transactions")
def list_transactions():
    return fetch_all_transactions()


@app.delete("/transactions")
def reset_transactions():
    clear_transactions()
    return {"cleared": True}


@app.get("/cities")
def list_cities():
    return {"cities": list(CITIES.keys())}


@app.get("/categories")
def list_categories():
    return {"categories": CATEGORY_RISK}


@app.post("/simulate")
def simulate(num_days: int = 14, normal_txns_per_day: int = 400, num_schemes: int = 3):
    """Generates a synthetic dataset (normal + Ponzi transactions) and loads
    it into the gateway, as if it had streamed in from real UPI traffic."""
    clear_transactions()
    data = generate_dataset(
        num_days=num_days,
        normal_txns_per_day=normal_txns_per_day,
        num_schemes=num_schemes,
    )
    for tx in data:
        tx["is_scam"] = int(tx["is_scam"])
    insert_many(data)
    scam_count = sum(1 for t in data if t["is_scam"])
    return {
        "loaded": len(data),
        "scam_labeled": scam_count,
        "scam_pct": round(scam_count / len(data) * 100, 1),
    }


# ---------------------------------------------------------------------------
# Mock VPA reputation service.
#
# IMPORTANT: this is NOT a real Paytm/PhonePe/NPCI API. No such public
# "is this VPA a scam" endpoint exists - their APIs are for merchants to
# accept payments and require full KYC onboarding. This endpoint simulates
# the SHAPE of a PSP-side reputation lookup so the integration pattern can be
# demonstrated honestly. Swap it for a real provider contract in production.
# ---------------------------------------------------------------------------

SUSPICIOUS_HANDLES = ["scheme-", "invest", "profit", "double", "earn", "daily"]
KNOWN_PSP_SUFFIXES = ["@upi", "@paytm", "@ybl", "@okaxis", "@ibl", "@apl"]


@app.get("/verify/{vpa}")
def verify_vpa(vpa: str):
    """Mock reputation check for a VPA. Deterministic (same VPA always gets
    the same answer) so demos are reproducible."""
    vpa_l = vpa.lower()

    valid_format = "@" in vpa_l and len(vpa_l.split("@")[0]) >= 2
    if not valid_format:
        raise HTTPException(status_code=400, detail="Malformed VPA")

    handle, _, suffix = vpa_l.partition("@")
    known_psp = any(vpa_l.endswith(s) for s in KNOWN_PSP_SUFFIXES)

    reasons = []
    score = 0

    for token in SUSPICIOUS_HANDLES:
        if token in handle:
            score += 40
            reasons.append(f"Handle contains high-risk keyword: '{token}'")
            break

    if not known_psp:
        score += 20
        reasons.append(f"Unrecognised PSP suffix: '@{suffix}'")

    # Deterministic pseudo-random component standing in for a real
    # reputation database lookup
    h = int(hashlib.sha256(vpa_l.encode()).hexdigest(), 16) % 100
    if h < 8:
        score += 35
        reasons.append("Appears on simulated community report list")

    score = min(score, 100)

    if score >= 60:
        verdict = "high_risk"
    elif score >= 30:
        verdict = "caution"
    else:
        verdict = "clean"
        if not reasons:
            reasons.append("No adverse signals in simulated registry")

    return {
        "vpa": vpa,
        "verdict": verdict,
        "reputation_score": score,
        "reasons": reasons,
        "source": "mock_reputation_service",
        "disclaimer": (
            "Simulated data. Not a real Paytm, PhonePe or NPCI lookup - no "
            "public API of that kind exists."
        ),
    }
