import os
from typing import Dict

import pandas as pd

from workers.config import load_all

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_CURATED = os.path.join(ROOT, "data", "curated")


def read_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    return pd.read_csv(path)


def load_weights() -> Dict[str, float]:
    cfg = load_all()
    scoring = cfg.get("scoring")
    if scoring and "icf" in scoring:
        return scoring["icf"].get("weights", {})
    return {
        "segment_fit": 0.25,
        "scale_velocity": 0.20,
        "emr_friction": 0.15,
        "coding_complexity": 0.15,
        "denial_pressure": 0.15,
        "roi_readiness": 0.10,
    }


def normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    total = sum(weights.values())
    if total == 0:
        return weights
    return {key: value / total for key, value in weights.items()}


def main():
    clinics_path = os.path.join(DATA_CURATED, "clinics_seed.csv")
    clinics = read_csv(clinics_path)
    if clinics.empty:
        print("No clinics to score. Run enrich_features first.")
        return

    weights = load_weights()
    if weights and max(weights.values()) > 1:
        weights = normalize_weights(weights)

    metrics = [
        "segment_fit",
        "scale_velocity",
        "emr_friction",
        "coding_complexity",
        "denial_pressure",
        "roi_readiness",
    ]
    for column in metrics:
        if column not in clinics.columns:
            clinics[column] = 0
        clinics[column] = pd.to_numeric(clinics[column], errors="coerce").fillna(0)

    icf = 0
    for metric in metrics:
        weight = weights.get(metric, 0)
        icf = icf + clinics[metric] * weight

    clinics["icf_score"] = icf.round(2)

    scores_path = os.path.join(DATA_CURATED, "scores_seed.csv")
    clinics[["clinic_id", "icf_score"] + metrics].to_csv(scores_path, index=False)

    scored = clinics.copy()
    clinics_scored_path = os.path.join(DATA_CURATED, "clinics_scored.csv")
    scored.to_csv(clinics_scored_path, index=False)

    print("Wrote:", scores_path, "rows=", len(clinics))
    print("Wrote:", clinics_scored_path, "rows=", len(scored))


if __name__ == "__main__":
    main()
