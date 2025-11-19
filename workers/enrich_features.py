import os
from pathlib import Path

import numpy as np
import pandas as pd
from slugify import slugify

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_CURATED = os.path.join(ROOT, "data", "curated")
STAGING_DIR = os.path.join(DATA_CURATED, "staging")


def read_parquet(path: str) -> pd.DataFrame:
    csv_path = path.replace('.parquet', '.csv')
    if os.path.exists(csv_path):
        try:
            return pd.read_csv(csv_path)
        except pd.errors.EmptyDataError:
            return pd.DataFrame()
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def safe_merge(left: pd.DataFrame, right: pd.DataFrame, on: str, how: str = "left") -> pd.DataFrame:
    if right.empty:
        return left
    return left.merge(right, on=on, how=how)


def normalize_name(value: str) -> str:
    if value is None:
        return ""
    return str(value).strip().upper()


def build_site_features(hrsa: pd.DataFrame) -> pd.DataFrame:
    if hrsa.empty:
        return pd.DataFrame(columns=["org_name_norm", "zip", "site_count", "fqhc_flag"])
    hrsa = hrsa.copy()
    hrsa["org_name_norm"] = hrsa["org_name"].map(normalize_name)
    hrsa["zip"] = hrsa["zip"].fillna("")
    grouped = hrsa.groupby(["org_name_norm", "zip"], as_index=False).agg(
        site_count=("site_id", "count"),
        fqhc_flag=("fqhc_flag", "max"),
    )
    return grouped


def build_pecos_features(pecos: pd.DataFrame) -> pd.DataFrame:
    if pecos.empty:
        return pd.DataFrame(columns=["npi", "pecos_enrolled", "pecos_specialties"])
    pecos = pecos.copy()
    pecos["npi"] = pecos["npi"].astype(str).str.zfill(10)
    pecos["pecos_enrolled"] = 1
    pecos = pecos[["npi", "pecos_enrolled", "specialties"]].rename(
        columns={"specialties": "pecos_specialties"}
    )
    return pecos.drop_duplicates(subset=["npi"])


def build_aco_features(aco: pd.DataFrame) -> pd.DataFrame:
    if aco.empty:
        return pd.DataFrame(columns=["npi", "aco_member"])
    records = []
    for _, row in aco.iterrows():
        participant = str(row.get("participant_id", "")).strip()
        if len(participant) == 10:
            records.append({"npi": participant.zfill(10), "aco_member": 1})
    if len(records) == 0:
        return pd.DataFrame(columns=["npi", "aco_member"])
    df = pd.DataFrame(records)
    df = df.drop_duplicates(subset=["npi"])
    return df


def build_util_features(util: pd.DataFrame) -> pd.DataFrame:
    if util.empty:
        return pd.DataFrame(columns=["npi", "services_count", "allowed_amt", "bene_count"])
    util = util.copy()
    util["npi"] = util["npi"].astype(str).str.zfill(10)
    numeric_cols = [col for col in util.columns if col != "npi"]
    for col in numeric_cols:
        util[col] = pd.to_numeric(util[col], errors="coerce").fillna(0)
    agg = util.groupby("npi", as_index=False).agg(
        services_count=(numeric_cols[0], "sum"),
        allowed_amt=(numeric_cols[1] if len(numeric_cols) > 1 else numeric_cols[0], "sum"),
        bene_count=(numeric_cols[2] if len(numeric_cols) > 2 else numeric_cols[0], "sum"),
    )
    return agg


def build_oig_leie_features() -> pd.DataFrame:
    """
    Load OIG LEIE matches and create features.
    
    Returns:
        DataFrame with clinic_id, oig_leie_flag, oig_exclusion_type
    """
    oig_matches_path = os.path.join(STAGING_DIR, "oig_leie_matches.csv")
    
    if not os.path.exists(oig_matches_path):
        print("No OIG LEIE matches found. Run enrich_oig_leie first.")
        return pd.DataFrame(columns=["clinic_id", "oig_leie_flag", "oig_exclusion_type"])
    
    try:
        matches = pd.read_csv(oig_matches_path, low_memory=False)
        if matches.empty:
            return pd.DataFrame(columns=["clinic_id", "oig_leie_flag", "oig_exclusion_type"])
        
        # Create features: flag and exclusion type
        features = matches[["clinic_id", "exclusion_type"]].copy()
        features["oig_leie_flag"] = True
        features = features.rename(columns={"exclusion_type": "oig_exclusion_type"})
        
        # If multiple matches per clinic, take the first (most recent would be better, but we don't have dates sorted)
        features = features.drop_duplicates(subset=["clinic_id"], keep="first")
        
        print(f"Loaded OIG LEIE features for {len(features)} clinics")
        return features
    except Exception as e:
        print(f"Error loading OIG LEIE matches: {e}")
        return pd.DataFrame(columns=["clinic_id", "oig_leie_flag", "oig_exclusion_type"])


def main():
    staging = Path(STAGING_DIR)
    npi = read_parquet(str(staging / "stg_npi_orgs.parquet"))
    if npi.empty:
        print("No NPI orgs found. Run ingest_api first.")
        return

    hrsa = read_parquet(str(staging / "stg_hrsa_sites.parquet"))
    pecos = read_parquet(str(staging / "stg_pecos_orgs.parquet"))
    aco = read_parquet(str(staging / "stg_aco_orgs.parquet"))
    util = read_parquet(str(staging / "stg_physician_util.parquet"))

    site_features = build_site_features(hrsa)
    pecos_features = build_pecos_features(pecos)
    aco_features = build_aco_features(aco)
    util_features = build_util_features(util)
    oig_features = build_oig_leie_features()

    df = npi.copy()
    df["org_name_norm"] = df["org_name"].map(normalize_name)
    df["zip"] = df["zip"].fillna("")

    if not site_features.empty:
        df = df.merge(site_features, on=["org_name_norm", "zip"], how="left")
    else:
        df["site_count"] = 1
        df["fqhc_flag"] = 0

    if "site_count" not in df.columns:
        df["site_count"] = 1
    df["site_count"] = df["site_count"].fillna(0)
    if "fqhc_flag" not in df.columns:
        df["fqhc_flag"] = 0
    df["fqhc_flag"] = df["fqhc_flag"].fillna(0)

    df = safe_merge(df, pecos_features, on="npi")
    df = safe_merge(df, aco_features, on="npi")
    df = safe_merge(df, util_features, on="npi")

    if "pecos_enrolled" not in df.columns:
        df["pecos_enrolled"] = 0
    else:
        df["pecos_enrolled"] = df["pecos_enrolled"].fillna(0)

    if "aco_member" not in df.columns:
        df["aco_member"] = 0
    else:
        df["aco_member"] = df["aco_member"].fillna(0)

    for metric in ["services_count", "allowed_amt", "bene_count"]:
        if metric not in df.columns:
            df[metric] = 0
        df[metric] = pd.to_numeric(df[metric], errors="coerce").fillna(0)

    df["taxonomy_count"] = df["taxonomy"].fillna("").astype(str).str.split(";").map(lambda items: len([item for item in items if item != ""]))

    services_max = max(df["services_count"].max(), 1)
    site_max = max(df["site_count"].max(), 1)

    df["segment_fit"] = 8.0
    taxonomy_text = df["taxonomy"].fillna("").str.upper()
    df.loc[taxonomy_text.str.contains("FAMILY"), "segment_fit"] += 6
    df.loc[taxonomy_text.str.contains("INTERNAL"), "segment_fit"] += 6
    df.loc[taxonomy_text.str.contains("PEDIATR"), "segment_fit"] += 5
    df.loc[df["fqhc_flag"] == 1, "segment_fit"] += 8
    df.loc[df["taxonomy_count"] > 3, "segment_fit"] += 4
    df["segment_fit"] = df["segment_fit"].clip(0, 25)

    df["scale_velocity"] = 3.0 + (np.log1p(df["services_count"]) / np.log1p(services_max) * 12)
    df["scale_velocity"] += np.log1p(df["site_count"]) / np.log1p(site_max) * 5
    df.loc[df["scale_velocity"].isna(), "scale_velocity"] = 3.0
    df["scale_velocity"] = df["scale_velocity"].clip(0, 20)

    df["emr_friction"] = 6.0
    df.loc[df["pecos_enrolled"] == 1, "emr_friction"] += 4
    df.loc[df["aco_member"] == 1, "emr_friction"] += 3
    df.loc[df["site_count"] > 10, "emr_friction"] -= 3
    df["emr_friction"] = df["emr_friction"].clip(0, 15)

    df["coding_complexity"] = 5.0
    df.loc[df["taxonomy_count"] >= 4, "coding_complexity"] += 6
    df.loc[df["taxonomy"].str.contains("HOSP", case=False, na=False), "coding_complexity"] += 4
    df.loc[df["services_count"] > services_max * 0.5, "coding_complexity"] += 3
    df["coding_complexity"] = df["coding_complexity"].clip(0, 15)

    df["allowed_per_bene"] = np.where(df["bene_count"] > 0, df["allowed_amt"] / df["bene_count"], 0)
    variance_threshold = df["allowed_per_bene"].median() + df["allowed_per_bene"].std()
    df["denial_pressure"] = 5.0
    df.loc[df["allowed_per_bene"] > variance_threshold, "denial_pressure"] += 6
    df.loc[df["pecos_enrolled"] == 0, "denial_pressure"] += 2
    df.loc[df["aco_member"] == 1, "denial_pressure"] += 3
    df["denial_pressure"] = df["denial_pressure"].clip(0, 15)

    df["roi_readiness"] = 0.0
    df.loc[df["aco_member"] == 1, "roi_readiness"] += 5
    df.loc[df["pecos_enrolled"] == 1, "roi_readiness"] += 3
    df.loc[df["services_count"] > services_max * 0.25, "roi_readiness"] += 2
    df["roi_readiness"] = df["roi_readiness"].clip(0, 10)

    df["state_code"] = df["state"].fillna("").astype(str).str.upper()
    df["org_like"] = 1

    df["clinic_id"] = df.apply(
        lambda row: slugify(f"{row['org_name']} {row['state_code']}") if row["org_name"] else slugify(row["npi"]),
        axis=1,
    )

    # Merge OIG LEIE features by clinic_id
    if not oig_features.empty:
        df = safe_merge(df, oig_features, on="clinic_id")
    else:
        df["oig_leie_flag"] = False
        df["oig_exclusion_type"] = None

    # Set defaults for OIG fields if missing
    if "oig_leie_flag" not in df.columns:
        df["oig_leie_flag"] = False
    else:
        df["oig_leie_flag"] = df["oig_leie_flag"].fillna(False)
    
    if "oig_exclusion_type" not in df.columns:
        df["oig_exclusion_type"] = None
    else:
        df["oig_exclusion_type"] = df["oig_exclusion_type"].fillna(None)

    clinics = df[
        [
            "clinic_id",
            "npi",
            "org_name",
            "state_code",
            "address",
            "city",
            "site_count",
            "fqhc_flag",
            "aco_member",
            "org_like",
            "segment_fit",
            "scale_velocity",
            "emr_friction",
            "coding_complexity",
            "denial_pressure",
            "roi_readiness",
            "pecos_enrolled",
            "services_count",
            "allowed_amt",
            "bene_count",
            "oig_leie_flag",
            "oig_exclusion_type",
        ]
    ].drop_duplicates(subset=["clinic_id"])

    clinics_path = os.path.join(DATA_CURATED, "clinics_seed.csv")
    clinics.to_csv(clinics_path, index=False)
    print("Wrote:", clinics_path, "rows=", len(clinics))


if __name__ == "__main__":
    main()
