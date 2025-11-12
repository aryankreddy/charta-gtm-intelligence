# api/app.py
import os
from functools import lru_cache
from typing import List, Dict, Any

import pandas as pd
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Charta Clinic Intelligence API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Paths --------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CURATED = os.path.join(ROOT, "data", "curated")
STAGING = os.path.join(CURATED, "staging")
PRIMARY_FILE = os.path.join(CURATED, "clinics_scored.csv")
FALLBACK_FILE = os.path.join(CURATED, "scores_seed.csv")


def _derive_display_name_from_id(clinic_id: str) -> str:
    if not isinstance(clinic_id, str) or clinic_id.strip() == "":
        return "Unknown"
    parts = clinic_id.rsplit("-", 1)
    base = parts[0] if len(parts) == 2 and len(parts[1]) in (2, 3) else clinic_id
    return base.replace("-", " ").title()


@lru_cache(maxsize=1)
def load_clinics() -> pd.DataFrame:
    # Prefer enriched file; fallback to seed
    path = PRIMARY_FILE if os.path.exists(PRIMARY_FILE) else FALLBACK_FILE
    if not os.path.exists(path):
        return pd.DataFrame()

    dtypes = {
        "clinic_id": "string",
        "account_name": "string",
        "org_name": "string",
        "state_code": "string",
    }
    df = pd.read_csv(path, dtype=dtypes, low_memory=False)

    # Make a robust display_name
    if "display_name" not in df.columns:
        if "org_name" in df.columns:
            disp = df["account_name"].fillna("").replace("", pd.NA)
            df["display_name"] = disp.fillna(df["org_name"]).fillna("Unknown")
        elif "account_name" in df.columns:
            df["display_name"] = df["account_name"].fillna("Unknown")
        else:
            # derive from clinic_id
            df["display_name"] = df["clinic_id"].fillna("").apply(_derive_display_name_from_id)

    if "icf_score" not in df.columns:
        df["icf_score"] = 0.0

    # Normalize state_code
    if "state_code" in df.columns:
        df["state_code"] = df["state_code"].fillna("").str.upper().str[:2]

    return df


@lru_cache(maxsize=8)
def load_staging(filename: str) -> pd.DataFrame:
    """Load parquet or csv from /data/curated/staging with a small cache."""
    path = os.path.join(STAGING, filename)
    csv_path = path.replace(".parquet", ".csv")
    if os.path.exists(csv_path):
        try:
            return pd.read_csv(csv_path, low_memory=False)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


@app.get("/health")
def health() -> Dict[str, Any]:
    src = PRIMARY_FILE if os.path.exists(PRIMARY_FILE) else (FALLBACK_FILE if os.path.exists(FALLBACK_FILE) else None)
    df = load_clinics()
    return {"ok": True, "source": src, "rows": int(df.shape[0])}


@app.get("/clinics")
def clinics(
    limit: int = Query(200, ge=1, le=5000),
    min_score: float = Query(0.0, ge=0, le=100),
    state: str = Query("", max_length=2),
    q: str = Query("", max_length=120),
):
    df = load_clinics().copy()
    if df.empty:
        return {"total": 0, "rows": []}

    # filters
    if min_score > 0:
        df = df[df["icf_score"] >= min_score]
    if state:
        df = df[df["state_code"] == state.upper()]
    if q:
        qlower = q.strip().lower()
        cols = [c for c in ["display_name", "account_name", "org_name", "clinic_id"] if c in df.columns]
        if cols:
            mask = False
            for c in cols:
                mask = mask | df[c].astype(str).str.lower().str.contains(qlower, na=False)
            df = df[mask]

    df = df.sort_values("icf_score", ascending=False)

    total = len(df)
    if limit > 0:
        df = df.head(limit)

    keep = [c for c in [
        "clinic_id","display_name","org_name","state_code","icf_score",
        "segment","sector","segment_label",
        "structural_fit_score","propensity_score","icf_tier","primary_driver",
        "segment_fit","scale_velocity","emr_friction","coding_complexity",
        "denial_pressure","roi_readiness","aco_member","org_like","site_count",
        "fqhc_flag","pecos_enrolled","services_count","allowed_amt","bene_count"
    ] if c in df.columns]
    records = df[keep].to_dict(orient="records")
    # Normalize GTM fields for proper JSON serialization
    records = [normalize_gtm_fields(r) for r in records]
    return {"total": total, "rows": records}


def normalize_gtm_fields(record: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize GTM intelligence fields to proper types, handling NaN/None."""
    if "structural_fit_score" in record:
        val = record["structural_fit_score"]
        record["structural_fit_score"] = float(val) if pd.notna(val) and val is not None else None
    if "propensity_score" in record:
        val = record["propensity_score"]
        record["propensity_score"] = float(val) if pd.notna(val) and val is not None else None
    if "icf_tier" in record:
        val = record["icf_tier"]
        record["icf_tier"] = int(float(val)) if pd.notna(val) and val is not None else None
    if "segment_label" in record:
        val = record["segment_label"]
        record["segment_label"] = str(val) if pd.notna(val) and val is not None else None
    if "primary_driver" in record:
        val = record["primary_driver"]
        record["primary_driver"] = str(val) if pd.notna(val) and val is not None else None
    return record


def build_driver_payload(row: pd.Series) -> List[dict]:
    drivers = []
    mapping = {
        "segment_fit": "Segment Fit",
        "scale_velocity": "Scale & Velocity",
        "emr_friction": "Integration Ease",
        "coding_complexity": "Coding Complexity",
        "denial_pressure": "Denial Pressure",
        "roi_readiness": "ROI Readiness",
    }
    for key, label in mapping.items():
        if key in row:
            drivers.append({"axis": key, "label": label, "score": float(row.get(key, 0) or 0)})
    return drivers


@app.get("/clinics/{clinic_id}")
def clinic_detail(clinic_id: str):
    df = load_clinics()
    if df.empty:
        return {"clinic": None}
    match = df[df["clinic_id"] == clinic_id]
    if match.empty:
        return {"clinic": None}
    row = match.iloc[0].copy()
    if "display_name" not in row or not row["display_name"]:
        row["display_name"] = _derive_display_name_from_id(row.get("clinic_id", ""))
    payload = row.to_dict()
    
    # Normalize GTM intelligence fields for proper JSON serialization
    payload = normalize_gtm_fields(payload)
    
    payload["drivers"] = build_driver_payload(row)
    return {"clinic": payload}
