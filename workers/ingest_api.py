import importlib.util as import_util
import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List

import numpy as np
import pandas as pd

from workers.config import load_all
from workers.utils import download_api_pages, read_hcris_multi, stream_csv

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_RAW = os.path.join(ROOT, "data", "raw")
DATA_CURATED = os.path.join(ROOT, "data", "curated")
STAGING_DIR = os.path.join(DATA_CURATED, "staging")


def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def abs_path(relative: str) -> str:
    return os.path.abspath(os.path.join(ROOT, relative))


def normalize_zip(value: str) -> str:
    if value is None or value == "":
        return ""
    cleaned = str(value).strip().replace(" ", "")
    if len(cleaned) >= 5:
        return cleaned[:5]
    return cleaned


def write_parquet(df: pd.DataFrame, path: str) -> None:
    ensure_dir(os.path.dirname(path))
    engine_available = import_util.find_spec('pyarrow') is not None
    if df.empty:
        empty = pd.DataFrame()
        if engine_available:
            empty.to_parquet(path, index=False)
        else:
            empty.to_csv(path.replace('.parquet', '.csv'), index=False)
        return
    if engine_available:
        df.to_parquet(path, index=False)
    else:
        df.to_csv(path.replace('.parquet', '.csv'), index=False)


# --- NPI robust loader --------------------------------------------------------

NPI_COL_ALIASES: Dict[str, List[str]] = {
    "npi": ["NPI"],
    "org_name": [
        "Provider Organization Name (Legal Business Name)",
        "Provider Organization Name (Legal Business Name) ",
    ],
    "entity_type": ["Entity Type Code"],
    "city": [
        "Provider Business Practice Location Address City Name",
        "Provider Business Practice Location City Name",
    ],
    "state": [
        "Provider Business Practice Location Address State Name",
        "Provider Business Practice Location State Name",
    ],
    "zip": [
        "Provider Business Practice Location Address Postal Code",
        "Provider Business Practice Location Postal Code",
    ],
    "phone": [
        "Provider Business Practice Location Address Telephone Number",
        "Provider Business Practice Location Telephone Number",
    ],
    "tax1": ["Healthcare Provider Taxonomy Code_1", "Healthcare Provider Taxonomy Code 1"],
    "tax2": ["Healthcare Provider Taxonomy Code_2", "Healthcare Provider Taxonomy Code 2"],
    "tax3": ["Healthcare Provider Taxonomy Code_3", "Healthcare Provider Taxonomy Code 3"],
}

def _resolve_npi_renames(actual_cols: List[str]) -> Dict[str, str]:
    renames: Dict[str, str] = {}
    for canon, variants in NPI_COL_ALIASES.items():
        found = next((col for col in variants if col in actual_cols), None)
        if found:
            renames[found] = canon
    return renames

def process_npi(source_cfg: Dict) -> pd.DataFrame:
    path_cfg = source_cfg.get("url")
    if not path_cfg:
        raise ValueError("NPI config missing url")
    path = abs_path(path_cfg)
    if not os.path.exists(path):
        print(f"Skipping NPI ingestion; file not found: {path}")
        return pd.DataFrame(columns=["npi", "org_name", "city", "state", "zip", "phone", "tax1", "tax2", "tax3"])

    frames: List[pd.DataFrame] = []
    first_chunk = True
    rename_map: Dict[str, str] = {}

    for chunk in stream_csv(
        path,
        chunksize=100_000,
        dtype={"NPI": "string", "Entity Type Code": "string"},
        encoding="latin-1",
    ):
        if first_chunk:
            rename_map = _resolve_npi_renames(list(chunk.columns))
            if "npi" not in rename_map.values() and "NPI" not in chunk.columns:
                raise ValueError(f"NPI column not found. Got columns: {list(chunk.columns)[:20]}")
            process_npi._rename_map = rename_map  # type: ignore[attr-defined]
            first_chunk = False
        else:
            rename_map = getattr(process_npi, "_rename_map")  # type: ignore[attr-defined]

        chunk = chunk.rename(columns=rename_map)
        keep = [c for c in ["npi", "org_name", "entity_type", "city", "state", "zip", "phone", "tax1", "tax2", "tax3"] if c in chunk.columns]
        chunk = chunk[keep]
        if "entity_type" in chunk.columns:
            chunk = chunk[chunk["entity_type"] == "2"]
        if chunk.empty:
            continue
        frames.append(chunk)

    if not frames:
        return pd.DataFrame(columns=["npi", "org_name", "city", "state", "zip", "phone", "tax1", "tax2", "tax3"])

    out = pd.concat(frames, ignore_index=True)
    if "zip" in out.columns:
        out["zip"] = out["zip"].astype(str).str.extract(r"(^\d{5})", expand=False)
    if "state" in out.columns:
        out["state"] = out["state"].astype(str).str.upper().str[:2]
    out["npi"] = out["npi"].astype(str)
    return out





def process_hrsa(source_cfg: Dict) -> pd.DataFrame:
    path = abs_path(source_cfg.get("url"))
    if not os.path.exists(path):
        print(f'Skipping HRSA ingestion; file not found: {path}')
        return pd.DataFrame(columns=["site_id", "org_name", "site_name", "address", "city", "state", "zip", "npi", "fqhc_flag"])
    df = pd.read_csv(path, dtype="string", low_memory=False)

    def first_match(candidates: List[str]) -> str:
        for candidate in candidates:
            if candidate in df.columns:
                return candidate
        return ""

    def column_or_blank(col_name: str) -> pd.Series:
        if col_name and col_name in df.columns:
            return df[col_name].fillna("").astype(str)
        return pd.Series(["" for _ in range(len(df))], index=df.index)

    name_col = first_match(["site_name", "Site Name", "site"])
    org_col = first_match(["parent_organization_name", "Parent Organization", "organization_name", "Health Center Name", name_col])
    state_col = first_match(["state", "State", "state_abbr", "Site State Abbreviation"])
    city_col = first_match(["city", "City", "Site City"])
    zip_col = first_match(["zip", "Zip", "zip_code", "Site Postal Code"])
    address_col = first_match(["address", "Site Address", "street_address", "Street Address"])
    npi_col = first_match(["npi", "NPI", "FQHC Site NPI Number"])

    site_ids = column_or_blank("site_id") if "site_id" in df.columns else pd.Series(df.index.astype(str), index=df.index)

    data = pd.DataFrame(
        {
            "site_id": site_ids,
            "org_name": column_or_blank(org_col).str.upper(),
            "site_name": column_or_blank(name_col),
            "address": column_or_blank(address_col),
            "city": column_or_blank(city_col).str.title(),
            "state": column_or_blank(state_col).str.upper(),
            "zip": column_or_blank(zip_col).map(normalize_zip),
            "npi": column_or_blank(npi_col),
            "fqhc_flag": 1,  # All HRSA records are FQHCs or Look-Alikes by definition
        }
    )

    mask = data["org_name"] == ""
    if mask.any():
        data.loc[mask, "org_name"] = data.loc[mask, "site_name"].str.upper()

    staging_path = os.path.join(STAGING_DIR, "stg_hrsa_sites.parquet")
    write_parquet(data, staging_path)
    return data


def write_jsonl(rows: Iterable[Dict], path: str) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row))
            handle.write("\n")


def process_api(source_name: str, source_cfg: Dict) -> pd.DataFrame:
    if not source_cfg:
        return pd.DataFrame()
    url = source_cfg.get("url")
    if not url:
        return pd.DataFrame()
    raw_dir = os.path.join(DATA_RAW, source_name)
    ensure_dir(raw_dir)
    dump_path = os.path.join(raw_dir, "dump.jsonl")
    rows: List[Dict] = []
    with open(dump_path, "w", encoding="utf-8") as handle:
        for record in download_api_pages(source_cfg):
            handle.write(json.dumps(record))
            handle.write("\n")
            rows.append(record)
    if len(rows) == 0:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def process_pecos(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["npi", "org_name", "state", "specialties", "address"])

    def first_match(columns, candidates):
        for candidate in candidates:
            if candidate in columns:
                return candidate
        return ""

    columns = df.columns
    npi_col = first_match(columns, ["npi", "npi_id", "organization_npi"])
    name_col = first_match(columns, ["org_name", "organization_name", "legal_business_name", "organization"])
    state_col = first_match(columns, [col for col in columns if str(col).lower().endswith("state")])
    address_col = first_match(columns, [col for col in columns if "address" in str(col).lower() and "practice" in str(col).lower()])

    def series_or_blank(col_name: str) -> pd.Series:
        if col_name:
            return df[col_name].fillna("").astype(str)
        return pd.Series(["" for _ in range(len(df))], index=df.index)

    npi_series = series_or_blank(npi_col).str.zfill(10)
    org_series = series_or_blank(name_col)
    state_series = series_or_blank(state_col).str.upper()
    address_series = series_or_blank(address_col)

    specialty_cols = [col for col in columns if str(col).lower().startswith("taxonomy") or "specialty" in str(col).lower()]
    if specialty_cols:
        specialties = df[specialty_cols].fillna("").astype(str).agg(lambda row: ";".join([val for val in row if val != ""]), axis=1)
    else:
        specialties = pd.Series(["" for _ in range(len(df))], index=df.index)

    subset = pd.DataFrame(
        {
            "npi": npi_series,
            "org_name": org_series,
            "state": state_series,
            "address": address_series,
            "specialties": specialties,
        }
    )
    subset = subset[subset["org_name"] != ""]
    subset = subset.drop_duplicates(subset=["npi"])
    staging_path = os.path.join(STAGING_DIR, "stg_pecos_orgs.parquet")
    write_parquet(subset, staging_path)
    return subset


def process_aco(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["participant_id", "org_name", "state", "aco_id"])
    name_col = "par_lbn" if "par_lbn" in df.columns else "organization_name"
    state_col = "aco_service_area" if "aco_service_area" in df.columns else "state"
    id_col = "aco_id" if "aco_id" in df.columns else "aco_identifier"
    participant_col = None
    for candidate in ["participant_tin", "participant_npi", "participant_id"]:
        if candidate in df.columns:
            participant_col = candidate
            break
    data = pd.DataFrame(
        {
            "participant_id": df.get(participant_col, df.index.astype(str)).astype(str),
            "org_name": df.get(name_col, "").fillna("").astype(str),
            "state": df.get(state_col, "").fillna("").astype(str),
            "aco_id": df.get(id_col, "").fillna("").astype(str),
        }
    )
    data = data[data["org_name"] != ""]
    staging_path = os.path.join(STAGING_DIR, "stg_aco_orgs.parquet")
    write_parquet(data, staging_path)
    return data


def process_physician_util(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["npi", "services_count", "allowed_amt", "bene_count"])
    util = df.copy()
    npi_col = None
    for candidate in ["npi", "npi_id", "nppes_provider_npi"]:
        if candidate in util.columns:
            npi_col = candidate
            break
    if npi_col is None:
        return pd.DataFrame(columns=["npi", "services_count", "allowed_amt", "bene_count"])
    service_col = next((col for col in util.columns if "tot_srvcs" in str(col).lower()), None)
    allowed_col = next((col for col in util.columns if "allowed_amt" in str(col).lower()), None)
    bene_col = next((col for col in util.columns if "bene" in str(col).lower()), None)
    util["npi"] = util[npi_col].astype(str).str.zfill(10)
    for col in [service_col, allowed_col, bene_col]:
        if col is None:
            continue
        util[col] = pd.to_numeric(util[col], errors="coerce").fillna(0)
    agg_map = {}
    if service_col:
        agg_map[service_col] = "sum"
    if allowed_col:
        agg_map[allowed_col] = "sum"
    if bene_col:
        agg_map[bene_col] = "sum"
    if not agg_map:
        grouped = util.groupby("npi", as_index=False).size().rename(columns={"size": "services_count"})
        grouped["allowed_amt"] = 0
        grouped["bene_count"] = 0
        return grouped[["npi", "services_count", "allowed_amt", "bene_count"]]
    grouped = util.groupby("npi", as_index=False).agg(agg_map)
    if service_col and service_col in grouped.columns:
        grouped = grouped.rename(columns={service_col: "services_count"})
    else:
        grouped["services_count"] = 0
    if allowed_col and allowed_col in grouped.columns:
        grouped = grouped.rename(columns={allowed_col: "allowed_amt"})
    else:
        grouped["allowed_amt"] = 0
    if bene_col and bene_col in grouped.columns:
        grouped = grouped.rename(columns={bene_col: "bene_count"})
    else:
        grouped["bene_count"] = 0
    grouped = grouped[["npi", "services_count", "allowed_amt", "bene_count"]]
    staging_path = os.path.join(STAGING_DIR, "stg_physician_util.parquet")
    write_parquet(grouped, staging_path)
    return grouped


def process_hcris(name: str, files: Dict[str, str], facility_type: str) -> pd.DataFrame:
    if not files:
        return pd.DataFrame(columns=["provider_num", "facility_type"])
    readers = read_hcris_multi(files)
    provider_numbers = set()
    for record in readers["alphnmrc"]:
        provider_num = record.get("provider_num", "").strip()
        if provider_num != "":
            provider_numbers.add(provider_num)
    metrics = pd.DataFrame(
        {
            "provider_num": list(provider_numbers),
            "facility_type": facility_type,
        }
    )
    staging_path = os.path.join(STAGING_DIR, f"stg_hcris_{name}.parquet")
    write_parquet(metrics, staging_path)
    return metrics


def main():
    cfg = load_all()
    sources = cfg["sources"]
    bulk = sources.get("bulk_sources", {})
    ensure_dir(DATA_RAW)
    ensure_dir(DATA_CURATED)
    ensure_dir(STAGING_DIR)

    counts = {}

    from pathlib import Path
    import duckdb

    prebuilt = Path(os.path.join(STAGING_DIR, "stg_npi_orgs.parquet"))
    if prebuilt.exists():
        print(f"NPI: using prebuilt parquet -> {prebuilt}")
        npi = duckdb.query(f"SELECT * FROM read_parquet('{prebuilt}')").to_df()
    else:
        print("NPI: parquet not found; building from CSV (slow)")
        npi = process_npi(bulk.get("npi_registry", {}))
    print("NPI rows:", len(npi))

    if not npi.empty:
        taxonomy_cols = [col for col in ["tax1", "tax2", "tax3"] if col in npi.columns]
        if taxonomy_cols:
            npi["taxonomy"] = npi[taxonomy_cols].fillna("").agg(
                lambda row: ";".join([val for val in row if val != ""]), axis=1
            )
        else:
            npi["taxonomy"] = ""
        for col in ["address", "phone"]:
            if col not in npi.columns:
                npi[col] = ""
        for col in ["city", "state", "zip"]:
            if col not in npi.columns:
                npi[col] = ""
        order = ["npi", "org_name", "address", "city", "state", "zip", "phone", "taxonomy"]
        npi = npi[[col for col in order if col in npi.columns]]
        write_parquet(npi, os.path.join(STAGING_DIR, "stg_npi_orgs.parquet"))
    counts["stg_npi_orgs"] = len(npi)

    hrsa = process_hrsa(bulk.get("hrsa_fqhc_sites", {}))
    counts["stg_hrsa_sites"] = len(hrsa)

    pecos_df = process_api("cms_pecos_enrollment_api", bulk.get("cms_pecos_enrollment_api", {}))
    pecos = process_pecos(pecos_df)
    counts["stg_pecos_orgs"] = len(pecos)

    aco_df = process_api("cms_aco_participants_api", bulk.get("cms_aco_participants_api", {}))
    aco = process_aco(aco_df)
    counts["stg_aco_orgs"] = len(aco)

    util_df = process_api("cms_physician_utilization_api", bulk.get("cms_physician_utilization_api", {}))
    util = process_physician_util(util_df)
    counts["stg_physician_util"] = len(util)

    process_hcris("fqhc", bulk.get("cost_reports_fqhc", {}).get("files", {}), "FQHC")
    process_hcris("rhc", bulk.get("cost_reports_rhc", {}).get("files", {}), "RHC")
    process_hcris("hospital", bulk.get("cost_reports_hospitals", {}).get("files", {}), "Hospital")
    process_hcris("hha", bulk.get("cost_reports_hha_2025", {}).get("files", {}), "HHA")

    print("Staging counts:")
    for key, value in counts.items():
        print(key, value)


if __name__ == "__main__":
    main()
