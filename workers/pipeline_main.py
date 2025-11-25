"""
TOTAL DATA CAPTURE PIPELINE
Author: Charta Health GTM Data Engineering
Description: Integrates Physician Util, Cost Reports, ACO, and HRSA data into the Master Seed File.
             Applies 'Hierarchy of Truth' to resolve data conflicts.
             Executes v3.1 ICP Scoring.
"""

import pandas as pd
import numpy as np
import os
import sys
import warnings
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Import Scoring Engine
from workers.score_icp import calculate_score

# Configuration
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_RAW = os.path.join(ROOT, "data", "raw")
DATA_CURATED = os.path.join(ROOT, "data", "curated")
DATA_STAGING = os.path.join(DATA_CURATED, "staging")

SEED_FILE = os.path.join(DATA_CURATED, "clinics_seed.csv")
OUTPUT_FILE = os.path.join(DATA_CURATED, "clinics_enriched_scored.csv")

# PECOS Paths
PECOS_DIR = os.path.join(DATA_RAW, "pecos", "Medicare Fee-For-Service  Public Provider Enrollment", "2025-Q3")
PECOS_REASSIGN = os.path.join(PECOS_DIR, "PPEF_Reassignment_Extract_2025.10.01.csv")
PECOS_ENROLL = os.path.join(PECOS_DIR, "PPEF_Enrollment_Extract_2025.10.01.csv")

warnings.filterwarnings('ignore')

def print_section(title):
    print("\n" + "="*80)
    print(f" {title}")
    print("="*80)

def normalize_name(name):
    """Normalize organization name for matching."""
    if pd.isna(name): return ""
    name = str(name).upper().strip()
    name = name.replace(".", "").replace(",", "").replace(" INC", "").replace(" LLC", "").replace(" PC", "")
    name = name.replace(" CLINIC", "").replace(" CENTER", "").replace(" HEALTH", "")
    return name

def load_ccn_to_npi_crosswalk():
    """
    Load CCN-to-NPI crosswalk from third-party file.
    Returns a dictionary mapping CCN -> NPI.
    
    File: crosswalk_npi2ccn_one2many_updated_20240429.csv
    Columns: npi, ccn, first_observed_date, last_observed_date, facility_type
    """
    print("   Loading CCN-to-NPI Crosswalk...")
    
    # Path to third-party crosswalk
    crosswalk_path = os.path.join(DATA_RAW, "crosswalk_npi2ccn_one2many_updated_20240429.csv")
    
    if not os.path.exists(crosswalk_path):
        print(f"   ⚠️  CCN-to-NPI crosswalk file not found: {crosswalk_path}")
        print(f"   💡 Using fuzzy name matching as fallback.")
        return {}
    
    print(f"   ✅ Found crosswalk file: {crosswalk_path}")
    
    try:
        # Load crosswalk
        xwalk = pd.read_csv(crosswalk_path)
        
        # Filter for recent relationships (>= 2023-01-01)
        xwalk['last_observed_date'] = pd.to_datetime(xwalk['last_observed_date'])
        xwalk_recent = xwalk[xwalk['last_observed_date'] >= '2023-01-01'].copy()
        
        print(f"   Loaded {len(xwalk):,} total links")
        print(f"   Filtered to {len(xwalk_recent):,} active links (since 2023-01-01)")
        
        # Dedup: If CCN maps to multiple NPIs, pick the one with latest date
        # Sort by last_observed_date descending, then take first per CCN
        xwalk_recent = xwalk_recent.sort_values('last_observed_date', ascending=False)
        xwalk_dedup = xwalk_recent.drop_duplicates(subset='ccn', keep='first')
        
        print(f"   Deduplicated to {len(xwalk_dedup):,} unique CCN-to-NPI mappings")
        
        # Create dictionary: CCN (string) -> NPI (int)
        xwalk_dedup['ccn_str'] = xwalk_dedup['ccn'].astype(str)
        xwalk_dict = dict(zip(xwalk_dedup['ccn_str'], xwalk_dedup['npi'].astype(int)))
        
        # Report by facility type
        print(f"   Facility types:")
        for ftype, count in xwalk_dedup['facility_type'].value_counts().head(5).items():
            print(f"     - {ftype}: {count:,}")
        
        return xwalk_dict
        
    except Exception as e:
        print(f"   ⚠️  Error loading crosswalk: {e}")
        print(f"   💡 Using fuzzy name matching as fallback.")
        return {}


def load_seed():
    print(f"Loading Seed File: {SEED_FILE}")
    if not os.path.exists(SEED_FILE):
        raise FileNotFoundError(f"Seed file not found: {SEED_FILE}")
    df = pd.read_csv(SEED_FILE, low_memory=False)
    # Ensure NPI is int64
    if 'npi' in df.columns:
        df['npi'] = pd.to_numeric(df['npi'], errors='coerce').fillna(0).astype(np.int64)
    
    # Create normalized name for matching
    if 'org_name' in df.columns:
        df['norm_name'] = df['org_name'].apply(normalize_name)
    else:
        df['norm_name'] = ""
        
    return df

# ============================================================================
# 1. PHYSICIAN UTILIZATION (The "Work Logs") + REASSIGNMENT BRIDGE
# ============================================================================
def load_pecos_bridge():
    print("   Loading PECOS Reassignment Bridge...")
    if not os.path.exists(PECOS_REASSIGN) or not os.path.exists(PECOS_ENROLL):
        print("   ⚠️  PECOS files not found. Skipping Bridge.")
        return None

    # 1. Load Enrollment (Map ID -> NPI)
    # We only need NPI and ENRLMT_ID
    print("   Loading Enrollment Map...")
    enrl = pd.read_csv(PECOS_ENROLL, usecols=['NPI', 'ENRLMT_ID'], dtype={'NPI': 'int64', 'ENRLMT_ID': str}, encoding='latin1')
    
    # 2. Load Reassignment (Map Indiv ID -> Org ID)
    print("   Loading Reassignment Map...")
    reas = pd.read_csv(PECOS_REASSIGN, usecols=['REASGN_BNFT_ENRLMT_ID', 'RCV_BNFT_ENRLMT_ID'], dtype=str, encoding='latin1')
    
    # 3. Join to get Indiv NPI -> Org NPI
    # Map Indiv ID -> NPI
    merged = reas.merge(enrl, left_on='REASGN_BNFT_ENRLMT_ID', right_on='ENRLMT_ID', how='inner')
    merged.rename(columns={'NPI': 'indiv_npi'}, inplace=True)
    
    # Map Org ID -> NPI
    merged = merged.merge(enrl, left_on='RCV_BNFT_ENRLMT_ID', right_on='ENRLMT_ID', how='inner')
    merged.rename(columns={'NPI': 'org_npi'}, inplace=True)
    
    bridge = merged[['indiv_npi', 'org_npi']].drop_duplicates()
    print(f"   ✅ Built Bridge: {len(bridge):,} links (Indiv -> Org)")
    return bridge

def integrate_physician_util(df):
    print_section("1. INTEGRATING PHYSICIAN UTILIZATION (WITH BRIDGE)")
    
    path = os.path.join(DATA_STAGING, "stg_physician_util.parquet")
    if not os.path.exists(path):
        print(f"⚠️  Parquet not found: {path}. Skipping.")
        return df
    
    print(f"   Loading {path}...")
    util = pd.read_parquet(path)
    
    # Ensure NPI is int64
    util['npi'] = pd.to_numeric(util['npi'], errors='coerce').fillna(0).astype(np.int64)
    
    # Load Bridge
    bridge = load_pecos_bridge()
    
    if bridge is not None:
        print("   Applying Bridge Logic (Roll-up)...")
        # Join Util (Indiv) to Bridge
        util_bridged = util.merge(bridge, left_on='npi', right_on='indiv_npi', how='inner')
        
        print(f"   Mapped {len(util_bridged):,} utilization records to organizations.")
        
        # Aggregate by Org NPI
        # Ensure numeric columns
        print(f"   Util Columns before agg: {util_bridged.columns.tolist()}")
        
        # Map columns if needed
        vol_col = 'line_srvc_cnt'
        rev_col = 'average_Medicare_allowed_amt'
        
        if vol_col not in util_bridged.columns:
            # Try to find volume column
            candidates = [c for c in util_bridged.columns if 'srvc' in c.lower() or 'cnt' in c.lower()]
            if candidates: vol_col = candidates[0]
            
        if rev_col not in util_bridged.columns:
             # Try to find revenue column
            candidates = [c for c in util_bridged.columns if 'allowed' in c.lower() or 'pymt' in c.lower()]
            if candidates: rev_col = candidates[0]
            
        print(f"   Aggregating using Volume: {vol_col}, Revenue: {rev_col}")
        
        if vol_col in util_bridged.columns:
            util_bridged[vol_col] = pd.to_numeric(util_bridged[vol_col], errors='coerce').fillna(0)
        else:
            util_bridged[vol_col] = 0
            
        if rev_col in util_bridged.columns:
            util_bridged[rev_col] = pd.to_numeric(util_bridged[rev_col], errors='coerce').fillna(0)
        else:
            util_bridged[rev_col] = 0
                
        util_agg = util_bridged.groupby('org_npi').agg({
            vol_col: 'sum',
            rev_col: 'sum'
        }).reset_index()
        
        util_agg.rename(columns={'org_npi': 'npi', vol_col: 'real_annual_encounters', rev_col: 'real_medicare_revenue'}, inplace=True)
        print(f"   Aggregated into {len(util_agg):,} unique organizations.")
        
    else:
        print("   ⚠️  No Bridge. Using direct NPI match (likely low overlap).")
        # Fallback to direct aggregation
        if util['npi'].duplicated().any():
            cols_to_sum = ['line_srvc_cnt', 'average_Medicare_allowed_amt']
            for c in cols_to_sum:
                if c in util.columns:
                    util[c] = pd.to_numeric(util[c], errors='coerce').fillna(0)
            util_agg = util.groupby('npi').agg({
                'line_srvc_cnt': 'sum',
                'average_Medicare_allowed_amt': 'sum'
            }).reset_index()
        else:
            util_agg = util

    # Rename for merge
    util_agg.rename(columns={
        'line_srvc_cnt': 'real_annual_encounters',
        'average_Medicare_allowed_amt': 'real_medicare_revenue'
    }, inplace=True)
    
    # Handle missing columns
    if 'real_medicare_revenue' not in util_agg.columns:
        util_agg['real_medicare_revenue'] = np.nan
    if 'real_annual_encounters' not in util_agg.columns:
        util_agg['real_annual_encounters'] = np.nan

    # Merge
    print(f"   Merging {len(util_agg):,} records...")
    merged = df.merge(util_agg[['npi', 'real_annual_encounters', 'real_medicare_revenue']], on='npi', how='left')
    
    matches = merged['real_annual_encounters'].notnull().sum()
    print(f"   ✅ Matched {matches:,} clinics with Real Volume/Revenue.")
    return merged

def integrate_undercoding_metrics(df):
    print_section("1B. INTEGRATING UNDERCODING METRICS")
    
    path = os.path.join(DATA_STAGING, "stg_undercoding_metrics.csv")
    if not os.path.exists(path):
        print(f"   ⚠️  Undercoding metrics not found: {path}. Run workers/mine_cpt_codes.py first.")
        return df
        
    print(f"   Loading {path}...")
    metrics = pd.read_csv(path)
    
    # Ensure NPI is int64
    metrics['npi'] = pd.to_numeric(metrics['npi'], errors='coerce').fillna(0).astype(np.int64)
    
    # Merge
    print(f"   Merging {len(metrics):,} undercoding records...")
    merged = df.merge(metrics[['npi', 'undercoding_ratio', 'total_eval_codes']], on='npi', how='left')
    
    matches = merged['undercoding_ratio'].notnull().sum()
    print(f"   ✅ Matched {matches:,} clinics with Undercoding Metrics.")
    
    # Flag severe undercoding
    severe = merged[merged['undercoding_ratio'] < 0.30]
    print(f"   🚨 {len(severe):,} clinics show severe undercoding (< 0.30).")
    
    return merged

# ============================================================================
# 2. FQHC COST REPORTS (The "Bank Statements")
# ============================================================================
def integrate_fqhc_reports(df):
    print_section("2. INTEGRATING FQHC COST REPORTS")
    
    enriched_path = os.path.join(DATA_STAGING, "fqhc_enriched_2024.csv")
    
    if not os.path.exists(enriched_path):
        print("   ⚠️  Enriched FQHC data not found. Run extract_fqhc_hcris.py first.")
        return df
        
    print(f"   Loading {enriched_path}...")
    fqhc = pd.read_csv(enriched_path)
    
    # Rename columns
    fqhc.rename(columns={
        'total_revenue': 'fqhc_revenue',
        'total_expenses': 'fqhc_expenses',
        'net_margin': 'fqhc_margin'
    }, inplace=True)
    
    # 1. Try CCN-to-NPI Crosswalk (Exact Match)
    ccn_to_npi = load_ccn_to_npi_crosswalk()
    
    if ccn_to_npi and 'PRVDR_NUM' in fqhc.columns:
        print("   Matching by CCN-to-NPI Crosswalk...")
        fqhc['ccn'] = fqhc['PRVDR_NUM'].astype(str).str.strip()
        fqhc['npi_xwalk'] = fqhc['ccn'].map(ccn_to_npi)
        
        # Use crosswalk NPI if available
        fqhc['npi'] = fqhc['npi_xwalk'].fillna(0).astype(np.int64)
        
        # Filter for matches
        fqhc_matched = fqhc[fqhc['npi'] != 0].copy()
        print(f"   Mapped {len(fqhc_matched):,} FQHCs to NPIs via crosswalk")
        
        if len(fqhc_matched) > 0:
            merged = df.merge(fqhc_matched[['npi', 'fqhc_revenue', 'fqhc_expenses', 'fqhc_margin']], on='npi', how='left', suffixes=('', '_new'))
            
            # Update columns
            for col in ['fqhc_revenue', 'fqhc_expenses', 'fqhc_margin']:
                new_col = f'{col}_new'
                if new_col in merged.columns:
                    merged[col] = merged[new_col].fillna(merged[col])
                    merged.drop(columns=[new_col], inplace=True)
            
            matches = merged['fqhc_revenue'].notnull().sum()
            print(f"   ✅ Matched {matches:,} FQHCs via CCN-to-NPI (Exact).")
            
            # Flag Segment B
            merged.loc[merged['fqhc_revenue'].notnull(), 'segment_label'] = 'Segment B'
            
            # Identify unmatched FQHCs for name matching
            matched_npis = set(merged[merged['fqhc_revenue'].notnull()]['npi'])
            unmatched_fqhc = fqhc[~fqhc['npi'].isin(matched_npis)].copy()
        else:
            merged = df
            unmatched_fqhc = fqhc.copy()
            
    elif 'npi' in fqhc.columns:
        print("   Matching by NPI (Direct)...")
        fqhc['npi'] = pd.to_numeric(fqhc['npi'], errors='coerce').fillna(0).astype(np.int64)
        
        # Split into matched and unmatched
        merged = df.merge(fqhc[['npi', 'fqhc_revenue', 'fqhc_expenses', 'fqhc_margin']], on='npi', how='left')
        
        matches = merged['fqhc_revenue'].notnull().sum()
        print(f"   ✅ Matched {matches:,} FQHCs by NPI.")
        
        # Flag Segment B
        merged.loc[merged['fqhc_revenue'].notnull(), 'segment_label'] = 'Segment B'
        
        # Identify unmatched FQHCs for name matching
        matched_npis = set(merged[merged['fqhc_revenue'].notnull()]['npi'])
        unmatched_fqhc = fqhc[~fqhc['npi'].isin(matched_npis)].copy()
    else:
        print("   ⚠️  NPI not found in FQHC data. All FQHCs are candidates for Name Matching.")
        unmatched_fqhc = fqhc.copy()
        merged = df
        # Initialize columns if not present
        for col in ['fqhc_revenue', 'fqhc_expenses', 'fqhc_margin']:
            if col not in merged.columns:
                merged[col] = np.nan

    # 2. Fuzzy Name Match (The "Soft" Join)
    print("   Attempting Name Match for unmatched FQHCs...")
    
    # Load Alpha File to get Names
    # Assuming path structure based on raw data location
    alpha_path = os.path.join(DATA_RAW, "cost_reports_fqhc", "FQHC14-ALL-YEARS (1)", "FQHC14_2024_alpha.csv")
    
    if os.path.exists(alpha_path):
        print(f"   Loading Alpha File: {alpha_path}...")
        # Alpha cols: RPT_REC_NUM, WKSHT_CD, LINE_NUM, CLMN_NUM, VALUE
        # We want WKSHT_CD='S100001', LINE_NUM='00100', CLMN_NUM='00100'
        # Note: CSV might not have headers or might use different names. 
        # Based on inspection: 39215,S100001,00100,00100,PRIMARY HEALTH...
        
        alpha = pd.read_csv(alpha_path, header=None, names=['RPT_REC_NUM', 'WKSHT_CD', 'LINE_NUM', 'CLMN_NUM', 'VALUE'], dtype=str)
        
        # Filter for Name
        names = alpha[
            (alpha['WKSHT_CD'] == 'S100001') & 
            (alpha['LINE_NUM'] == '00100') & 
            (alpha['CLMN_NUM'] == '00100')
        ][['RPT_REC_NUM', 'VALUE']]
        
        names.rename(columns={'VALUE': 'fqhc_name'}, inplace=True)
        
        # Ensure RPT_REC_NUM is numeric for merge
        names['RPT_REC_NUM'] = pd.to_numeric(names['RPT_REC_NUM'], errors='coerce')
        unmatched_fqhc['RPT_REC_NUM'] = pd.to_numeric(unmatched_fqhc['RPT_REC_NUM'], errors='coerce')
        
        # Join Names to Unmatched FQHCs
        unmatched_fqhc = unmatched_fqhc.merge(names, on='RPT_REC_NUM', how='inner')
        
        if len(unmatched_fqhc) > 0:
            print(f"   Found names for {len(unmatched_fqhc):,} unmatched FQHCs.")
            
            # Normalize
            unmatched_fqhc['norm_name'] = unmatched_fqhc['fqhc_name'].apply(normalize_name)
            
            # Create Map: NormName -> Financials
            # Handle duplicates by taking first (or max revenue?)
            fqhc_map = unmatched_fqhc.sort_values('fqhc_revenue', ascending=False).drop_duplicates('norm_name').set_index('norm_name')
            
            # Match against Seed
            # We only want to match rows that don't already have FQHC data
            mask_candidate = merged['fqhc_revenue'].isnull() & (merged['norm_name'] != "")
            
            # Map values
            # This is a vectorized map
            # We need to map 'norm_name' in merged to 'fqhc_revenue' in fqhc_map
            
            # Get common names
            common_names = set(merged.loc[mask_candidate, 'norm_name']).intersection(set(fqhc_map.index))
            print(f"   Found {len(common_names):,} name matches.")
            
            if len(common_names) > 0:
                # Update merged dataframe
                # We can't easily use .map on the whole column if we only want to update nulls
                # So we'll iterate or use a temporary merge
                
                # Let's use a temp merge
                matches_df = fqhc_map.loc[list(common_names)][['fqhc_revenue', 'fqhc_expenses', 'fqhc_margin']]
                
                # Update logic
                # We set the index of merged to norm_name temporarily? No, duplicates.
                # We iterate? Slow.
                # We merge and coalesce.
                
                name_matches = merged[mask_candidate].merge(matches_df, left_on='norm_name', right_index=True, how='inner', suffixes=('', '_new'))
                
                # Now update the main df using the index of name_matches
                merged.loc[name_matches.index, 'fqhc_revenue'] = name_matches['fqhc_revenue_new']
                merged.loc[name_matches.index, 'fqhc_expenses'] = name_matches['fqhc_expenses_new']
                merged.loc[name_matches.index, 'fqhc_margin'] = name_matches['fqhc_margin_new']
                merged.loc[name_matches.index, 'segment_label'] = 'Segment B'
                
                print(f"   ✅ Matched {len(name_matches):,} FQHCs by Name.")
        else:
            print("   ⚠️  No unmatched FQHCs found in Alpha file (or join failed).")
            
    else:
        print("   ⚠️  Alpha file not found. Skipping Name Match.")

    return merged

# ============================================================================
# 3. HOSPITAL COST REPORTS (Segment F) - SAS FILES
# ============================================================================
def integrate_hospital_reports(df):
    print_section("3. INTEGRATING HOSPITAL COST REPORTS (SAS)")
    
    # Path to SAS files
    sas_dir = os.path.join(DATA_RAW, "cost_reports_hospitals", "hosp10-sas ")
    
    # Use latest year (2024)
    sas_file = os.path.join(sas_dir, "prds_hosp10_yr2024.sas7bdat")
    
    if not os.path.exists(sas_file):
        print(f"   ⚠️  SAS file not found: {sas_file}")
        return df
    
    try:
        import pyreadstat
    except ImportError:
        print("   ⚠️  pyreadstat not installed. Run: pip install pyreadstat")
        return df
    
    print(f"   Loading SAS file: {sas_file}...")
    try:
        hosp, meta = pyreadstat.read_sas7bdat(sas_file, encoding='iso-8859-1')
        print(f"   ✅ Loaded {len(hosp):,} hospital records")
    except Exception as e:
        print(f"   ⚠️  Error reading SAS file: {e}")
        return df
    
    # Extract Key Metrics
    # G3_C1_1 = Total Patient Revenue (Line 1)
    # G3_C1_29 = Net Income (Line 29)
    # prvdr_num = Provider Number (CCN)
    
    # Select relevant columns
    hosp_extract = hosp[['prvdr_num', 'G3_C1_1', 'G3_C1_29']].copy()
    hosp_extract.rename(columns={
        'prvdr_num': 'ccn',
        'G3_C1_1': 'hosp_revenue',
        'G3_C1_29': 'hosp_net_income'
    }, inplace=True)
    
    # Calculate margin
    hosp_extract['hosp_margin'] = hosp_extract.apply(
        lambda row: (row['hosp_net_income'] / row['hosp_revenue']) if pd.notnull(row['hosp_revenue']) and row['hosp_revenue'] > 0 else np.nan,
        axis=1
    )

    # Clean CCN (remove leading zeros, convert to string)
    hosp_extract['ccn'] = hosp_extract['ccn'].astype(str).str.strip()
    
    # Remove rows with missing financials
    hosp_extract = hosp_extract[hosp_extract['hosp_revenue'].notnull() | hosp_extract['hosp_net_income'].notnull()]
    
    print(f"   Found {len(hosp_extract):,} hospitals with financial data")
    
    # Load CCN-to-NPI Crosswalk
    ccn_to_npi = load_ccn_to_npi_crosswalk()
    
    # Initialize columns if not present
    for col in ['hosp_revenue', 'hosp_net_income', 'hosp_margin']:
        if col not in df.columns:
            df[col] = np.nan
    
    if ccn_to_npi:
        # Map CCN to NPI
        hosp_extract['npi'] = hosp_extract['ccn'].map(ccn_to_npi)
        hosp_with_npi = hosp_extract[hosp_extract['npi'].notnull()].copy()
        
        print(f"   Mapped {len(hosp_with_npi):,} hospitals to NPIs via crosswalk")
        
        # Ensure NPI is int64
        hosp_with_npi['npi'] = hosp_with_npi['npi'].astype(np.int64)
        
        # Merge on NPI
        merged = df.merge(hosp_with_npi[['npi', 'hosp_revenue', 'hosp_net_income', 'hosp_margin']], 
                         on='npi', how='left', suffixes=('', '_new'))
        
        # Update columns
        for col in ['hosp_revenue', 'hosp_net_income', 'hosp_margin']:
            new_col = f'{col}_new'
            if new_col in merged.columns:
                merged[col] = merged[new_col].fillna(merged[col])
                merged.drop(columns=[new_col], inplace=True)
        
        # Set segment label for matched hospitals
        merged.loc[merged['hosp_revenue'].notnull(), 'segment_label'] = 'Segment F - Hospital'
        
        matches = merged['hosp_revenue'].notnull().sum()
        print(f"   ✅ Matched {matches:,} Hospitals via CCN-to-NPI (Exact)")
        
        df = merged
    else:
        print(f"   ⚠️  CCN-to-NPI crosswalk not available. Cannot match to Seed File.")
    
    # Store hospital data for future use
    hosp_staging_path = os.path.join(DATA_STAGING, "stg_hospital_sas_2024.csv")
    hosp_extract.to_csv(hosp_staging_path, index=False)
    print(f"   Saved hospital data to: {hosp_staging_path}")
    
    return df



# ============================================================================
# 3B. HOME HEALTH AGENCY (HHA) COST REPORTS
# ============================================================================
def integrate_hha_reports(df):
    print_section("3B. INTEGRATING HOME HEALTH AGENCY COST REPORTS")
    
    # Path to HHA cost report
    hha_dir = os.path.join(DATA_RAW, "cost_reports_hha", "HHA20-REPORTS (1)")
    hha_file = os.path.join(hha_dir, "CostReporthha_Final_23.csv")
    
    if not os.path.exists(hha_file):
        print(f"   ⚠️  HHA file not found: {hha_file}")
        return df
    
    print(f"   Loading HHA file: {hha_file}...")
    try:
        hha = pd.read_csv(hha_file)
        print(f"   ✅ Loaded {len(hha):,} HHA records")
    except Exception as e:
        print(f"   ⚠️  Error reading HHA file: {e}")
        return df
    
    # Extract Key Metrics
    # Column names from the file
    rev_col = 'Net Patient Revenues (line 1 minus line 2) Total'
    inc_col = 'Net Income or Loss for the period (line 18 plus line 32)'
    
    # Select relevant columns
    hha_extract = hha[['Provider CCN', 'HHA Name', rev_col, inc_col]].copy()
    hha_extract.rename(columns={
        'Provider CCN': 'ccn',
        'HHA Name': 'hha_name',
        rev_col: 'hha_revenue',
        inc_col: 'hha_net_income'
    }, inplace=True)
    
    # Calculate margin
    hha_extract['hha_margin'] = hha_extract.apply(
        lambda row: (row['hha_net_income'] / row['hha_revenue']) if pd.notnull(row['hha_revenue']) and row['hha_revenue'] > 0 else np.nan,
        axis=1
    )

    # Clean CCN
    hha_extract['ccn'] = hha_extract['ccn'].astype(str).str.strip()
    
    # Remove rows with missing financials
    hha_extract = hha_extract[hha_extract['hha_revenue'].notnull() | hha_extract['hha_net_income'].notnull()]
    
    print(f"   Found {len(hha_extract):,} HHAs with financial data")
    
    # Initialize columns if not present
    for col in ['hha_revenue', 'hha_net_income', 'hha_margin']:
        if col not in df.columns:
            df[col] = np.nan
    
    # Load CCN-to-NPI Crosswalk
    ccn_to_npi = load_ccn_to_npi_crosswalk()
    
    exact_matches = 0
    
    if ccn_to_npi:
        # 1. Try exact CCN-to-NPI match first
        print(f"   Attempting CCN-to-NPI exact match...")
        
        # Map CCN to NPI
        hha_extract['npi'] = hha_extract['ccn'].map(ccn_to_npi)
        hha_with_npi = hha_extract[hha_extract['npi'].notnull()].copy()
        
        print(f"   Mapped {len(hha_with_npi):,} HHAs to NPIs via crosswalk")
        
        if len(hha_with_npi) > 0:
            # Ensure NPI is int64
            hha_with_npi['npi'] = hha_with_npi['npi'].astype(np.int64)
            
            # Merge on NPI
            df = df.merge(hha_with_npi[['npi', 'hha_revenue', 'hha_net_income', 'hha_margin']], 
                         on='npi', how='left', suffixes=('', '_new'))
            
            # Update columns
            for col in ['hha_revenue', 'hha_net_income', 'hha_margin']:
                new_col = f'{col}_new'
                if new_col in df.columns:
                    df[col] = df[new_col].fillna(df[col])
                    df.drop(columns=[new_col], inplace=True)
            
            # Set segment label for matched HHAs
            df.loc[df['hha_revenue'].notnull(), 'segment_label'] = 'Segment - Home Health'
            
            exact_matches = df['hha_revenue'].notnull().sum()
            print(f"   ✅ Matched {exact_matches:,} HHAs via CCN-to-NPI (Exact)")
    
    # 2. Fallback to Fuzzy Name Match for unmatched
    print(f"   Attempting Name Match for unmatched HHAs...")
    
    # Normalize HHA names
    hha_extract['norm_name'] = hha_extract['hha_name'].apply(normalize_name)
    
    # Create map: NormName -> Financials
    # Handle duplicates by taking the one with highest revenue
    hha_map = hha_extract.sort_values('hha_revenue', ascending=False).drop_duplicates('norm_name').set_index('norm_name')
    
    # Only match rows that don't already have HHA data
    mask_candidate = df['hha_revenue'].isnull() & (df['norm_name'] != "")
    
    # Get common names
    common_names = set(df.loc[mask_candidate, 'norm_name']).intersection(set(hha_map.index))
    print(f"   Found {len(common_names):,} name matches")
    
    fuzzy_matches = 0

    if len(common_names) > 0:
        # Create matches dataframe
        matches_df = hha_map.loc[list(common_names)][['hha_revenue', 'hha_net_income', 'hha_margin']]
        
        # Merge and update
        name_matches = df[mask_candidate].merge(matches_df, left_on='norm_name', right_index=True, how='inner', suffixes=('', '_new'))
        
        # Update the main df
        df.loc[name_matches.index, 'hha_revenue'] = name_matches['hha_revenue_new']
        df.loc[name_matches.index, 'hha_net_income'] = name_matches['hha_net_income_new']
        df.loc[name_matches.index, 'hha_margin'] = name_matches['hha_margin_new']
        df.loc[name_matches.index, 'segment_label'] = 'Segment - Home Health'
        
        fuzzy_matches = len(name_matches)
        print(f"   ✅ Matched {fuzzy_matches:,} HHAs by Name (Fuzzy)")
    
    # Summary
    total_matches = exact_matches + fuzzy_matches
    print(f"   📊 Total HHA Matches: {total_matches:,} (Exact: {exact_matches:,}, Fuzzy: {fuzzy_matches:,})")

    
    # Save HHA data to staging for future use
    hha_staging_path = os.path.join(DATA_STAGING, "stg_hha_2023.csv")
    hha_extract.to_csv(hha_staging_path, index=False)
    print(f"   Saved HHA data to: {hha_staging_path}")
    
    return df


def integrate_strategic_data(df):
    print_section("4. INTEGRATING ACO & STRATEGIC DATA")
    
    # 1. OIG Exclusions (Risk)
    # Note: OIG file is in data/staging (root of staging), not data/curated/staging
    oig_path = os.path.join(ROOT, "data", "staging", "oig_leie_raw.csv")
    
    if os.path.exists(oig_path):
        print(f"   Loading OIG Exclusion List: {oig_path}...")
        # OIG file has NPI column, sometimes 0
        oig = pd.read_csv(oig_path, dtype=str)
        
        # Filter for valid NPIs
        excluded_npis = set(oig[oig['NPI'] != '0000000000']['NPI'].astype(int))
        print(f"   Found {len(excluded_npis):,} excluded NPIs.")
        
        # Flag in Seed File
        df['risk_compliance_flag'] = df['npi'].isin(excluded_npis)
        
        flagged_count = df['risk_compliance_flag'].sum()
        print(f"   🚨 Flagged {flagged_count:,} Clinics with Compliance Risks (OIG).")
    else:
        print(f"   ⚠️  OIG file not found at {oig_path}. Skipping Risk Flagging.")
        df['risk_compliance_flag'] = False

    # 2. ACO Data (Value) - Match by Name
    # Use raw CSV for better coverage (477 orgs vs 24 in parquet)
    aco_raw_path = os.path.join(DATA_RAW, "aco", "Accountable Care Organizations", "2025", "py2025_medicare_shared_savings_program_organizations.csv")
    
    if os.path.exists(aco_raw_path):
        print(f"   Loading ACO data from {aco_raw_path}...")
        aco = pd.read_csv(aco_raw_path, encoding='latin1')
        
        # Normalize column names to lowercase
        aco.columns = [c.lower() for c in aco.columns]
        
        # Column is 'aco_name'
        if 'aco_name' in aco.columns:
            aco['norm_name'] = aco['aco_name'].apply(normalize_name)
            aco_participants = set(aco['norm_name'].unique())
            
            # Match
            print(f"   Matching {len(aco_participants):,} ACO orgs by name...")
            df['is_aco_participant'] = df['norm_name'].isin(aco_participants)
            
            print(f"   ✅ Identified {df['is_aco_participant'].sum():,} Clinics participating in ACOs.")
        else:
            print(f"   ⚠️  ACO file missing 'aco_name' column. Columns: {aco.columns.tolist()}")
            df['is_aco_participant'] = False
    else:
        # Fallback to parquet
        stg_aco = os.path.join(DATA_STAGING, "stg_aco_orgs.parquet")
        if os.path.exists(stg_aco):
            print(f"   Loading ACO data from {stg_aco} (Fallback)...")
            aco = pd.read_parquet(stg_aco)
            name_col = 'aco_name' if 'aco_name' in aco.columns else 'org_name'
            
            if name_col in aco.columns:
                aco['norm_name'] = aco[name_col].apply(normalize_name)
                aco_participants = set(aco['norm_name'].unique())
                df['is_aco_participant'] = df['norm_name'].isin(aco_participants)
                print(f"   ✅ Identified {df['is_aco_participant'].sum():,} Clinics participating in ACOs (from Staging).")
            else:
                df['is_aco_participant'] = False
        else:
            print("   ⚠️  ACO data not found.")
            df['is_aco_participant'] = False

    # HRSA Data - Match by Name
    hrsa_path = os.path.join(DATA_STAGING, "stg_hrsa_sites.parquet")
    if os.path.exists(hrsa_path):
        print(f"   Loading HRSA data from {hrsa_path}...")
        hrsa = pd.read_parquet(hrsa_path)
        
        if 'org_name' in hrsa.columns:
            hrsa['norm_name'] = hrsa['org_name'].apply(normalize_name)
            hrsa_orgs = set(hrsa['norm_name'].unique())
            
            # Match
            print(f"   Matching {len(hrsa_orgs):,} HRSA orgs by name...")
            # Create a mask for HRSA match
            hrsa_mask = df['norm_name'].isin(hrsa_orgs)
            
            # If matched, it's likely an FQHC (Segment B)
            df.loc[hrsa_mask, 'segment_label'] = 'Segment B'
            print(f"   ✅ Identified {hrsa_mask.sum():,} HRSA sites (FQHCs).")
            
    return df

# ============================================================================
# 5. HIERARCHY OF TRUTH & SCORING
# ============================================================================
def apply_hierarchy_and_score(df):
    print_section("5. APPLYING HIERARCHY OF TRUTH (VECTORIZED)")
    
    # Initialize columns
    df['final_revenue'] = np.nan
    df['revenue_source'] = "Estimated (Low)"
    df['final_volume'] = np.nan
    df['volume_source'] = "Estimated (Low)"
    df['final_margin'] = np.nan
    df['margin_source'] = "Estimated (Low)"
    
    # 1. Revenue Hierarchy
    # Medicare * 3
    mask_med = df['real_medicare_revenue'].gt(0)
    df.loc[mask_med, 'final_revenue'] = df.loc[mask_med, 'real_medicare_revenue'] * 3.0
    df.loc[mask_med, 'revenue_source'] = "Medicare Claims (Med)"
    
    # FQHC (Overrides Medicare)
    mask_fqhc = df['fqhc_revenue'].gt(0)
    df.loc[mask_fqhc, 'final_revenue'] = df.loc[mask_fqhc, 'fqhc_revenue']
    df.loc[mask_fqhc, 'revenue_source'] = "Cost Report (High)"
    
    # 2. Volume Hierarchy
    mask_vol = df['real_annual_encounters'].gt(0)
    df.loc[mask_vol, 'final_volume'] = df.loc[mask_vol, 'real_annual_encounters']
    df.loc[mask_vol, 'volume_source'] = "Claims/HRSA (High)"
    
    # 3. Margin Hierarchy
    mask_margin = df['fqhc_margin'].notnull()
    df.loc[mask_margin, 'final_margin'] = df.loc[mask_margin, 'fqhc_margin']
    df.loc[mask_margin, 'margin_source'] = "Cost Report (High)"
    
    # Map to columns expected by score_icp
    df['total_revenue'] = df['final_revenue']
    df['net_margin'] = df['final_margin']
    # score_icp uses 'services_count' as the primary volume metric
    df['services_count'] = df['final_volume']
    
    print(f"   ✅ Applied hierarchy to {len(df):,} records.")
    return df

def integrate_hrsa_data(df):
    print_section("5. INTEGRATING HRSA UDS DATA (FQHC Volume)")
    
    hrsa_path = os.path.join(DATA_RAW, "hrsa", "Health_Center_Service_Delivery_and_LookAlike_Sites (1).csv")
    
    if not os.path.exists(hrsa_path):
        print(f"   ⚠️  HRSA file not found: {hrsa_path}")
        return df
        
    print(f"   Loading HRSA data from {hrsa_path}...")
    # Skip first 2 rows (header on row 3)
    hrsa = pd.read_csv(hrsa_path, header=2)
    
    print(f"   Found {len(hrsa):,} HRSA sites.")
    
    # Check for Volume Column
    vol_col = None
    candidates = ['Total Patients', 'Patients', 'Visits']
    for c in candidates:
        if c in hrsa.columns:
            vol_col = c
            break
            
    if vol_col:
        print(f"   ✅ Found Volume Column: {vol_col}")
    else:
        print(f"   ⚠️  Volume column not found. Columns: {hrsa.columns.tolist()}")
        print("   ⚠️  Skipping Volume Overwrite. Performing Identity Match only.")
        
    # Prepare for Matching
    # Match on: State (Exact) + City (Exact) + Org Name (Fuzzy)
    # Note: City might be missing in this file
    
    # Normalize HRSA
    hrsa['norm_name'] = hrsa['Site Name'].apply(normalize_name)
    hrsa['norm_state'] = hrsa['State'].astype(str).str.upper().str.strip()
    
    if 'City' in hrsa.columns:
        hrsa['norm_city'] = hrsa['City'].astype(str).str.upper().str.strip()
        use_city = True
    else:
        print("   ⚠️  City column not found. Matching by State + Name only (Lower Precision).")
        use_city = False
    
    # Normalize Seed (if not already)
    if 'norm_name' not in df.columns:
        if 'org_name' in df.columns:
            df['norm_name'] = df['org_name'].apply(normalize_name)
        else:
            df['norm_name'] = ""
            
    # Handle State Column (Seed uses state_code)
    state_col = 'state' if 'state' in df.columns else 'state_code'
    if 'norm_state' not in df.columns:
        if state_col in df.columns:
            df['norm_state'] = df[state_col].astype(str).str.upper().str.strip()
        else:
            print("   ⚠️  State column not found in Seed. Cannot match.")
            return df
    
    if use_city:
        # Check if Seed has city
        city_col = 'city'
        if city_col not in df.columns:
             print("   ⚠️  City column not found in Seed. Matching by State + Name only.")
             use_city = False
        else:
            if 'norm_city' not in df.columns:
                df['norm_city'] = df[city_col].astype(str).str.upper().str.strip()
            
    if use_city:
        # Create blocking key: State + City
        hrsa['block_key'] = hrsa['norm_state'] + "|" + hrsa['norm_city']
        df['block_key'] = df['norm_state'] + "|" + df['norm_city']
    else:
        # Block by State only
        hrsa['block_key'] = hrsa['norm_state']
        df['block_key'] = df['norm_state']
    
    # Iterate through blocks
    # Filter for blocks present in both
    common_blocks = set(hrsa['block_key']).intersection(set(df['block_key']))
    print(f"   Processing {len(common_blocks):,} common location blocks...")
    
    # Exact Name Match within Block
    merged = df.merge(hrsa[['block_key', 'norm_name', 'Site Name'] + ([vol_col] if vol_col else [])], 
                     on=['block_key', 'norm_name'], 
                     how='inner', suffixes=('', '_hrsa'))
                     
    print(f"   ✅ Matched {len(merged):,} FQHCs by Exact Name + Location.")
    
    # Update Data
    if len(merged) > 0:
        # Set FQHC Flag
        df.loc[merged.index, 'fqhc_flag'] = 1
        df.loc[merged.index, 'segment_label'] = 'Segment B'
        
        if vol_col:
            # Overwrite Volume
            # Create a map: NPI -> Volume
            npi_vol_map = dict(zip(merged['npi'], merged[vol_col]))
            
            # Update
            df['real_annual_encounters'] = df['npi'].map(npi_vol_map).fillna(df['real_annual_encounters'])
            
            # Update source
            df.loc[df['npi'].isin(npi_vol_map.keys()), 'data_source_volume'] = 'HRSA UDS'
            
            print(f"   ✅ Overwrote volume for {len(npi_vol_map):,} clinics.")
            
    return df

def integrate_psych_metrics(df):
    """
    Merge Behavioral Health Signals (Psych Risk Ratio).
    """
    print_section("INTEGRATING BEHAVIORAL HEALTH SIGNALS")
    
    psych_file = os.path.join(DATA_STAGING, "stg_psych_metrics.csv")
    
    if not os.path.exists(psych_file):
        print(f"   ⚠️  Psych metrics file not found: {psych_file}")
        print(f"   💡 Run workers/mine_psych_codes.py first.")
        return df
    
    print(f"   Loading {psych_file}...")
    psych_df = pd.read_csv(psych_file, dtype={'npi': str})
    
    # Ensure NPI is numeric for merge
    psych_df['npi'] = pd.to_numeric(psych_df['npi'], errors='coerce').astype('Int64')
    df['npi'] = pd.to_numeric(df['npi'], errors='coerce').astype('Int64')
    
    print(f"   Loaded {len(psych_df):,} clinics with psych metrics")
    
    # Merge
    before = len(df)
    df = df.merge(psych_df[['npi', 'total_psych_codes', 'psych_risk_ratio']], on='npi', how='left')
    
    # Fill NaN with 0
    df['total_psych_codes'] = df['total_psych_codes'].fillna(0)
    df['psych_risk_ratio'] = df['psych_risk_ratio'].fillna(0)
    
    matched = df['psych_risk_ratio'].gt(0).sum()
    print(f"   ✅ Matched {matched:,} clinics with behavioral health signals ({matched/before:.1%})")
    
    high_risk = df['psych_risk_ratio'].gt(0.80).sum()
    print(f"   🚨 High Audit Risk (>0.80): {high_risk:,} clinics")
    
    return df

# ============================================================================
# MAIN PIPELINE
# ============================================================================
def run_pipeline():
    print("🚀 STARTING TOTAL DATA CAPTURE PIPELINE")
    
    # 1. Load
    df = load_seed()
    print(f"   Initial Seed Count: {len(df):,}")
    
    # 2. Integrate
    df = integrate_physician_util(df)
    df = integrate_undercoding_metrics(df)
    df = integrate_psych_metrics(df)  # NEW: Behavioral Health Signals
    df = integrate_fqhc_reports(df)
    df = integrate_hospital_reports(df)
    df = integrate_hha_reports(df)
    df = integrate_hrsa_data(df)
    df = integrate_strategic_data(df)
    
    # 3. Score
    # final_df = apply_hierarchy_and_score(df)
    # Optimization: Apply hierarchy vectorized, then run scoring engine
    df = apply_hierarchy_and_score(df)
    
    # Save intermediate file for scoring engine
    print_section("SAVING INTERMEDIATE FILE")
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"   Saved enriched data to: {OUTPUT_FILE}")
    
    # Run Scoring Engine
    print_section("RUNNING SCORING ENGINE")
    from workers.score_icp import main as run_scoring
    run_scoring()
    
    # Reload Scored Data for Reporting
    print("   Reloading scored data for reporting...")
    scored_file = os.path.join(DATA_CURATED, "clinics_scored_final.csv")
    if os.path.exists(scored_file):
        final_df = pd.read_csv(scored_file, low_memory=False)
    else:
        print("   ❌ Scoring failed. Using enriched data.")
        final_df = df
    
    # 4. Merge phone numbers from NPI registry
    phone_path = os.path.join(DATA_CURATED, "staging", "stg_npi_orgs.parquet")
    if os.path.exists(phone_path):
        print(f"   Loading phone data from {phone_path}...")
        phone_df = pd.read_parquet(phone_path, columns=["npi", "phone"])
        # Ensure NPI column is numeric to match final_df dtype
        phone_df['npi'] = pd.to_numeric(phone_df['npi'], errors='coerce').astype('Int64')
        final_df = final_df.merge(phone_df, on="npi", how="left")
        phone_filled = final_df['phone'].notnull().sum()
        print(f"   ✅ Merged phone numbers for {phone_filled:,} clinics (fill rate: {phone_filled/len(final_df):.1%})")
    else:
        print(f"   ⚠️  Phone data not found: {phone_path}")
        
    # 5. Save Final
    print_section("SAVING FINAL RESULTS")
    final_df.to_csv(scored_file, index=False) # Save again with phones
    print(f"   Saved to: {scored_file}")
    
    # 5. Report
    print_section("DATA CAPTURE REPORT")
    total = len(final_df)
    print(f"Total Clinics: {total:,}")
    
    print("\n1. REAL FINANCIALS (Cost Reports)")
    fqhc_real = final_df['fqhc_revenue'].notnull().sum()
    print(f"   - FQHC Matches: {fqhc_real:,} (Fill Rate: {fqhc_real/total:.1%})")
    
    print("\n2. REAL VOLUME (Utilization/HRSA)")
    vol_real = final_df['real_annual_encounters'].notnull().sum()
    print(f"   - Verified Volume: {vol_real:,} (Fill Rate: {vol_real/total:.1%})")
    
    print("\n3. STRATEGIC SIGNALS")
    aco_count = final_df['is_aco_participant'].sum()
    print(f"   - ACO Participants: {aco_count:,}")
    
    print("\n4. SCORING IMPACT")
    if 'icp_tier' in final_df.columns:
        tiers = final_df['icp_tier'].value_counts().sort_index()
        for t, c in tiers.items():
            print(f"   - {t}: {c:,}")
    else:
        print("   ⚠️  Scoring columns missing.")

if __name__ == "__main__":
    run_pipeline()
