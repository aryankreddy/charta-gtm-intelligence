"""
BEHAVIORAL HEALTH SIGNAL MINER
Author: Charta Health GTM Strategy

Purpose: Extract psychotherapy billing patterns to identify audit risk.

Target Codes:
- 90837: Psychotherapy, 60 min (High Scrutiny)
- 90834: Psychotherapy, 45 min (Standard)

Formula: Psych_Risk_Ratio = Count(90837) / (Count(90837) + Count(90834))
Interpretation: Ratio > 0.80 = High Audit Risk
"""

import pandas as pd
import numpy as np
import os
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PHYSICIAN_UTIL = os.path.join(ROOT, "data", "raw", "physician_utilization", 
                               "Medicare Physician & Other Practitioners - by Provider and Service", 
                               "2023", "MUP_PHY_R25_P05_V20_D23_Prov_Svc.csv")
PECOS_BRIDGE = os.path.join(ROOT, "data", "curated", "staging", "stg_pecos_bridge.csv")
OUTPUT_FILE = os.path.join(ROOT, "data", "curated", "staging", "stg_psych_metrics.csv")

# Target HCPCS codes
TARGET_CODES = ['90837', '90834']

def mine_psych_codes():
    print("🧠 MINING BEHAVIORAL HEALTH SIGNALS...")
    
    if not os.path.exists(PHYSICIAN_UTIL):
        print(f"❌ Physician Utilization file not found: {PHYSICIAN_UTIL}")
        return
    
    # STEP 1: Extract Psych Codes (Chunked Processing)
    print("📊 Step 1: Extracting psychotherapy codes from Medicare claims...")
    
    psych_data = []
    chunk_size = 500000
    chunks_processed = 0
    
    for chunk in pd.read_csv(PHYSICIAN_UTIL, chunksize=chunk_size, low_memory=False, dtype=str):
        chunks_processed += 1
        
        # Filter for target codes (note: column is HCPCS_Cd not Hcpcs_Cd)
        psych_chunk = chunk[chunk['HCPCS_Cd'].isin(TARGET_CODES)].copy()
        
        if not psych_chunk.empty:
            # Keep only needed columns
            psych_chunk = psych_chunk[['Rndrng_NPI', 'HCPCS_Cd', 'Tot_Srvcs']].copy()
            psych_chunk['Tot_Srvcs'] = pd.to_numeric(psych_chunk['Tot_Srvcs'], errors='coerce').fillna(0)
            psych_data.append(psych_chunk)
        
        if chunks_processed % 5 == 0:
            print(f"  Processed {chunks_processed} chunks...")
    
    if not psych_data:
        print("❌ No psychotherapy codes found in claims data.")
        return
    
    # Combine all chunks
    psych_df = pd.concat(psych_data, ignore_index=True)
    print(f"✅ Found {len(psych_df):,} psychotherapy claim records")
    
    # STEP 2: Aggregate by Provider NPI
    print("📈 Step 2: Aggregating by provider NPI...")
    
    # Pivot to get counts per code
    provider_psych = psych_df.pivot_table(
        index='Rndrng_NPI',
        columns='HCPCS_Cd',
        values='Tot_Srvcs',
        aggfunc='sum',
        fill_value=0
    ).reset_index()
    
    # Ensure both columns exist
    if '90837' not in provider_psych.columns:
        provider_psych['90837'] = 0
    if '90834' not in provider_psych.columns:
        provider_psych['90834'] = 0
    
    # Calculate metrics
    provider_psych['total_psych_codes'] = provider_psych['90837'] + provider_psych['90834']
    provider_psych['psych_risk_ratio'] = np.where(
        provider_psych['total_psych_codes'] > 0,
        provider_psych['90837'] / provider_psych['total_psych_codes'],
        0
    )
    
    # Filter for meaningful volume (>10 codes)
    provider_psych = provider_psych[provider_psych['total_psych_codes'] > 10].copy()
    
    print(f"✅ {len(provider_psych):,} providers with meaningful psych volume (>10 codes)")
    print(f"   Mean Risk Ratio: {provider_psych['psych_risk_ratio'].mean():.3f}")
    print(f"   High Risk (>0.80): {len(provider_psych[provider_psych['psych_risk_ratio'] > 0.80]):,} providers")
    
    # STEP 3: Roll Up to Clinic Level (via PECOS Bridge)
    print("🏥 Step 3: Rolling up to clinic level...")
    
    if not os.path.exists(PECOS_BRIDGE):
        print(f"⚠️  PECOS Bridge not found. Saving provider-level data only.")
        clinic_psych = provider_psych.rename(columns={'Rndrng_NPI': 'npi'})
    else:
        # Load PECOS bridge
        bridge = pd.read_csv(PECOS_BRIDGE, dtype=str)
        bridge = bridge[['provider_npi', 'clinic_npi']].drop_duplicates()
        
        # Merge provider data with bridge
        provider_psych['provider_npi'] = provider_psych['Rndrng_NPI']
        merged = provider_psych.merge(bridge, on='provider_npi', how='left')
        
        # Use clinic_npi if available, else use provider_npi
        merged['npi'] = merged['clinic_npi'].fillna(merged['provider_npi'])
        
        # Aggregate to clinic level
        clinic_psych = merged.groupby('npi').agg({
            '90837': 'sum',
            '90834': 'sum',
            'total_psych_codes': 'sum'
        }).reset_index()
        
        # Recalculate ratio at clinic level
        clinic_psych['psych_risk_ratio'] = np.where(
            clinic_psych['total_psych_codes'] > 0,
            clinic_psych['90837'] / clinic_psych['total_psych_codes'],
            0
        )
        
        # Filter for meaningful volume (>100 codes at clinic level)
        clinic_psych = clinic_psych[clinic_psych['total_psych_codes'] > 100].copy()
        
        print(f"✅ {len(clinic_psych):,} clinics with meaningful psych volume (>100 codes)")
        print(f"   Mean Risk Ratio: {clinic_psych['psych_risk_ratio'].mean():.3f}")
        print(f"   High Risk (>0.80): {len(clinic_psych[clinic_psych['psych_risk_ratio'] > 0.80]):,} clinics")
    
    # STEP 4: Save Output
    print("💾 Step 4: Saving output...")
    
    # Keep only needed columns
    output_cols = ['npi', 'total_psych_codes', 'psych_risk_ratio']
    clinic_psych[output_cols].to_csv(OUTPUT_FILE, index=False)
    
    print(f"✅ Saved to {OUTPUT_FILE}")
    
    # Summary Stats
    print("\n📊 SUMMARY STATISTICS:")
    print(f"   Total Clinics: {len(clinic_psych):,}")
    print(f"   Avg Psych Codes: {clinic_psych['total_psych_codes'].mean():.0f}")
    print(f"   Avg Risk Ratio: {clinic_psych['psych_risk_ratio'].mean():.3f}")
    print(f"   High Risk (>0.80): {len(clinic_psych[clinic_psych['psych_risk_ratio'] > 0.80]):,}")
    print(f"   Medium Risk (0.60-0.80): {len(clinic_psych[(clinic_psych['psych_risk_ratio'] >= 0.60) & (clinic_psych['psych_risk_ratio'] <= 0.80)]):,}")
    print(f"   Low Risk (<0.60): {len(clinic_psych[clinic_psych['psych_risk_ratio'] < 0.60]):,}")

if __name__ == "__main__":
    mine_psych_codes()
