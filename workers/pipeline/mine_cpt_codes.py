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

# Configuration - Go up 2 levels from workers/pipeline/ to project root
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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

def process_utilization_with_bridge(bridge):
    """
    Process Medicare utilization data in chunks, merging with PECOS bridge
    to aggregate directly by Organization NPI.
    
    Args:
        bridge: DataFrame with columns ['indiv_npi', 'org_npi'] or None
        
    Returns:
        DataFrame with columns ['npi', 'undercoding_ratio', 'total_eval_codes']
    """
    print(f"🚀 Starting CPT Mining on {UTIL_FILE}")
    
    chunk_size = 100000
    org_chunks = []
    total_rows = 0
    matched_rows = 0
    
    # Process in chunks
    for chunk in pd.read_csv(UTIL_FILE, chunksize=chunk_size, 
                            usecols=['Rndrng_NPI', 'HCPCS_Cd', 'Tot_Srvcs'], 
                            dtype={'Rndrng_NPI': 'int64', 'HCPCS_Cd': str, 'Tot_Srvcs': float}):
        
        # Filter for target codes
        filtered = chunk[chunk['HCPCS_Cd'].isin(ALL_TARGET_CODES)].copy()
        
        if not filtered.empty:
            if bridge is not None:
                # Merge with bridge to get Org NPI
                filtered = filtered.merge(bridge, left_on='Rndrng_NPI', right_on='indiv_npi', how='inner')
                matched_rows += len(filtered)
                
                # Aggregate by Org NPI and Code
                agg = filtered.groupby(['org_npi', 'HCPCS_Cd'])['Tot_Srvcs'].sum().reset_index()
                agg.rename(columns={'org_npi': 'npi'}, inplace=True)
            else:
                # Fallback: use individual NPI as proxy for org
                agg = filtered.groupby(['Rndrng_NPI', 'HCPCS_Cd'])['Tot_Srvcs'].sum().reset_index()
                agg.rename(columns={'Rndrng_NPI': 'npi'}, inplace=True)
            
            org_chunks.append(agg)
        
        total_rows += len(chunk)
        sys.stdout.write(f"\r   Processed {total_rows:,} rows...")
        sys.stdout.flush()
        
    print("\n   ✅ Finished processing chunks.")
    
    if bridge is not None:
        print(f"   Mapped {matched_rows:,} utilization records to organizations via bridge.")
    
    if not org_chunks:
        print("   ⚠️  No target codes found.")
        return None
        
    # Combine all chunks and aggregate by Org NPI
    print("   Aggregating results by Organization NPI...")
    full_df = pd.concat(org_chunks, ignore_index=True)
    final_agg = full_df.groupby(['npi', 'HCPCS_Cd'])['Tot_Srvcs'].sum().reset_index()
    
    # Pivot to get columns
    print("   Pivoting data...")
    pivot = final_agg.pivot(index='npi', columns='HCPCS_Cd', values='Tot_Srvcs').fillna(0)
    
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

    # Calculate undercoding ratio
    # NOTE: Higher ratio = BETTER (more Level 4/5 usage = less undercoding)
    #       Lower ratio = WORSE (fewer Level 4/5 usage = more undercoding)
    #       National average: ~45% (0.45)
    #       Ratios < 0.35 indicate severe undercoding
    pivot['undercoding_ratio'] = pivot['count_level_4_5'] / pivot['total_eval_codes']
    
    print(f"   Identified {len(pivot):,} organizations with relevant E&M volume.")
    
    # Return only needed columns
    result = pivot.reset_index()[['npi', 'undercoding_ratio', 'total_eval_codes']]
    return result

def main():
    print("="*80)
    print(" MINE CPT CODES - UNDERCODING METRICS (ORG-LEVEL)")
    print("="*80)
    
    # 1. Load PECOS Bridge
    bridge = load_pecos_bridge()
    
    if bridge is None:
        print("\n   ⚠️  WARNING: No bridge available. Using individual NPIs as proxy.")
        print("   💡 For production use, ensure PECOS files are available.")
    
    # 2. Process Utilization with Bridge
    org_metrics = process_utilization_with_bridge(bridge)
    
    if org_metrics is not None:
        # 3. Save
        org_metrics.to_csv(OUTPUT_FILE, index=False)
        print(f"\n   ✅ Saved Undercoding Metrics to: {OUTPUT_FILE}")
        print(f"   📊 Total Organizations: {len(org_metrics):,}")
        
        # 4. Report
        severe_undercoding = org_metrics[org_metrics['undercoding_ratio'] < 0.30]
        print(f"   🚨 Severe Undercoding (< 0.30): {len(severe_undercoding):,} organizations ({len(severe_undercoding)/len(org_metrics)*100:.1f}%)")
        
        moderate_undercoding = org_metrics[(org_metrics['undercoding_ratio'] >= 0.30) & (org_metrics['undercoding_ratio'] < 0.50)]
        print(f"   ⚠️  Moderate Undercoding (0.30-0.50): {len(moderate_undercoding):,} organizations ({len(moderate_undercoding)/len(org_metrics)*100:.1f}%)")
        
        # Distribution stats
        print(f"\n   📈 Undercoding Ratio Distribution:")
        print(f"      Mean:   {org_metrics['undercoding_ratio'].mean():.3f}")
        print(f"      Median: {org_metrics['undercoding_ratio'].median():.3f}")
        print(f"      Min:    {org_metrics['undercoding_ratio'].min():.3f}")
        print(f"      Max:    {org_metrics['undercoding_ratio'].max():.3f}")
    else:
        print("\n   ❌ No metrics generated. Check input data.")

if __name__ == "__main__":
    main()
