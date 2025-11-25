"""
Mine CPT Codes for Undercoding Signals
Author: Charta Health GTM Data Engineering

Objective: Calculate the "Undercoding Ratio" for every NPI and roll it up to the Clinic level.
Formula: (Count of Level 4+5) / (Total Count of Levels 3+4+5)
Target Codes:
- Level 3 (Low): 99203, 99213
- Level 4/5 (High): 99204, 99205, 99214, 99215

Interpretation: Ratio < 0.30 implies undercoding.
"""

import pandas as pd
import numpy as np
import os
import sys

# Configuration
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_RAW = os.path.join(ROOT, "data", "raw")
DATA_CURATED = os.path.join(ROOT, "data", "curated")
DATA_STAGING = os.path.join(DATA_CURATED, "staging")

# Input Files
UTIL_FILE = os.path.join(DATA_RAW, "physician_utilization", "Medicare Physician & Other Practitioners - by Provider and Service", "2023", "MUP_PHY_R25_P05_V20_D23_Prov_Svc.csv")
PECOS_DIR = os.path.join(DATA_RAW, "pecos", "Medicare Fee-For-Service  Public Provider Enrollment", "2025-Q3")
PECOS_REASSIGN = os.path.join(PECOS_DIR, "PPEF_Reassignment_Extract_2025.10.01.csv")
PECOS_ENROLL = os.path.join(PECOS_DIR, "PPEF_Enrollment_Extract_2025.10.01.csv")

# Output File
OUTPUT_FILE = os.path.join(DATA_STAGING, "stg_undercoding_metrics.csv")

# Target Codes
LEVEL_3_CODES = ['99203', '99213']
LEVEL_4_5_CODES = ['99204', '99205', '99214', '99215']
ALL_TARGET_CODES = set(LEVEL_3_CODES + LEVEL_4_5_CODES)

def load_pecos_bridge():
    print("   Loading PECOS Reassignment Bridge...")
    if not os.path.exists(PECOS_REASSIGN) or not os.path.exists(PECOS_ENROLL):
        print("   ⚠️  PECOS files not found. Skipping Bridge.")
        return None

    # 1. Load Enrollment (Map ID -> NPI)
    print("   Loading Enrollment Map...")
    enrl = pd.read_csv(PECOS_ENROLL, usecols=['NPI', 'ENRLMT_ID'], dtype={'NPI': 'int64', 'ENRLMT_ID': str}, encoding='latin1')
    
    # 2. Load Reassignment (Map Indiv ID -> Org ID)
    print("   Loading Reassignment Map...")
    reas = pd.read_csv(PECOS_REASSIGN, usecols=['REASGN_BNFT_ENRLMT_ID', 'RCV_BNFT_ENRLMT_ID'], dtype=str, encoding='latin1')
    
    # 3. Join to get Indiv NPI -> Org NPI
    merged = reas.merge(enrl, left_on='REASGN_BNFT_ENRLMT_ID', right_on='ENRLMT_ID', how='inner')
    merged.rename(columns={'NPI': 'indiv_npi'}, inplace=True)
    
    merged = merged.merge(enrl, left_on='RCV_BNFT_ENRLMT_ID', right_on='ENRLMT_ID', how='inner')
    merged.rename(columns={'NPI': 'org_npi'}, inplace=True)
    
    bridge = merged[['indiv_npi', 'org_npi']].drop_duplicates()
    print(f"   ✅ Built Bridge: {len(bridge):,} links (Indiv -> Org)")
    return bridge

def process_utilization():
    print(f"🚀 Starting CPT Mining on {UTIL_FILE}")
    
    chunk_size = 100000
    chunks = []
    total_rows = 0
    
    # Process in chunks
    for chunk in pd.read_csv(UTIL_FILE, chunksize=chunk_size, usecols=['Rndrng_NPI', 'HCPCS_Cd', 'Tot_Srvcs'], dtype={'Rndrng_NPI': 'int64', 'HCPCS_Cd': str, 'Tot_Srvcs': float}):
        # Filter for target codes
        filtered = chunk[chunk['HCPCS_Cd'].isin(ALL_TARGET_CODES)]
        
        if not filtered.empty:
            # Aggregate by NPI and Code
            agg = filtered.groupby(['Rndrng_NPI', 'HCPCS_Cd'])['Tot_Srvcs'].sum().reset_index()
            chunks.append(agg)
        
        total_rows += len(chunk)
        sys.stdout.write(f"\r   Processed {total_rows:,} rows...")
        sys.stdout.flush()
        
    print("\n   ✅ Finished processing chunks.")
    
    if not chunks:
        print("   ⚠️  No target codes found.")
        return None
        
    # Combine all chunks
    print("   Aggregating results...")
    full_df = pd.concat(chunks, ignore_index=True)
    final_agg = full_df.groupby(['Rndrng_NPI', 'HCPCS_Cd'])['Tot_Srvcs'].sum().reset_index()
    
    # Pivot to get columns
    print("   Pivoting data...")
    pivot = final_agg.pivot(index='Rndrng_NPI', columns='HCPCS_Cd', values='Tot_Srvcs').fillna(0)
    
    # Calculate sums for levels
    # Note: columns might be missing if no codes found for that specific code
    for code in ALL_TARGET_CODES:
        if code not in pivot.columns:
            pivot[code] = 0
            
    pivot['count_level_3'] = pivot[LEVEL_3_CODES].sum(axis=1)
    pivot['count_level_4_5'] = pivot[LEVEL_4_5_CODES].sum(axis=1)
    pivot['total_eval_codes'] = pivot['count_level_3'] + pivot['count_level_4_5']
    
    # Filter for meaningful volume (e.g., at least 10 codes)
    pivot = pivot[pivot['total_eval_codes'] >= 10].copy()
    
    print(f"   Identified {len(pivot):,} providers with relevant E&M volume.")
    return pivot.reset_index()

def roll_up_to_clinic(provider_metrics):
    print("🌉 Rolling up to Clinic Level...")
    
    bridge = load_pecos_bridge()
    
    if bridge is None:
        print("   ⚠️  No bridge available. Returning provider-level metrics (as clinic proxies).")
        provider_metrics.rename(columns={'Rndrng_NPI': 'npi'}, inplace=True)
        # Calculate ratio
        provider_metrics['undercoding_ratio'] = provider_metrics['count_level_4_5'] / provider_metrics['total_eval_codes']
        return provider_metrics[['npi', 'undercoding_ratio', 'total_eval_codes']]
        
    # Join Provider Metrics to Bridge
    merged = provider_metrics.merge(bridge, left_on='Rndrng_NPI', right_on='indiv_npi', how='inner')
    
    print(f"   Mapped {len(merged):,} providers to clinics.")
    
    # Aggregate by Org NPI
    clinic_agg = merged.groupby('org_npi').agg({
        'count_level_3': 'sum',
        'count_level_4_5': 'sum',
        'total_eval_codes': 'sum'
    }).reset_index()
    
    # Calculate Ratio
    clinic_agg['undercoding_ratio'] = clinic_agg['count_level_4_5'] / clinic_agg['total_eval_codes']
    
    clinic_agg.rename(columns={'org_npi': 'npi'}, inplace=True)
    
    print(f"   Calculated metrics for {len(clinic_agg):,} clinics.")
    return clinic_agg[['npi', 'undercoding_ratio', 'total_eval_codes']]

def main():
    # 1. Process Utilization
    provider_metrics = process_utilization()
    
    if provider_metrics is not None:
        # 2. Roll up
        clinic_metrics = roll_up_to_clinic(provider_metrics)
        
        # 3. Save
        clinic_metrics.to_csv(OUTPUT_FILE, index=False)
        print(f"   ✅ Saved Undercoding Metrics to: {OUTPUT_FILE}")
        
        # 4. Report
        severe_undercoding = clinic_metrics[clinic_metrics['undercoding_ratio'] < 0.30]
        print(f"   🚨 Identified {len(severe_undercoding):,} Clinics with Severe Undercoding (< 0.30)")

if __name__ == "__main__":
    main()
