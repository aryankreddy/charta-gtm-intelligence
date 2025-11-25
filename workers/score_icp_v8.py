"""
CHARTA HEALTH ICP SCORING ENGINE v8.0
"Strict Sum" Model - Precision & Transparency

Total Score = 100 Points (Strict Additive)
- Economic Pain: 40 pts
- Strategic Fit: 35 pts  
- Strategic Value: 25 pts

Author: Charta Health GTM Intelligence
"""

import pandas as pd
import numpy as np
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

INPUT_FILE = os.path.join(ROOT, "data", "curated", "clinics_enriched_scored.csv")
OUTPUT_FILE = os.path.join(ROOT, "data", "curated", "clinics_scored_final.csv")

# Load CERT Benchmarks
CERT_FILE = os.path.join(ROOT, "data", "raw", "cert_specialty_benchmarks.csv")
CERT_BENCHMARKS = {}
if os.path.exists(CERT_FILE):
    try:
        cert_df = pd.read_csv(CERT_FILE)
        CERT_BENCHMARKS = dict(zip(cert_df['provider_type'].str.lower(), cert_df['improper_payment_rate']))
        print(f"✅ Loaded {len(CERT_BENCHMARKS)} CERT benchmarks.")
    except Exception as e:
        print(f"⚠️ Failed to load CERT benchmarks: {e}")

def calculate_score_v8(row):
    """
    v8.0 Strict Sum Scoring (100 Points Total)
    
    Returns detailed breakdown for UI transparency.
    """
    
    # ===== DATA EXTRACTION =====
    segment = str(row.get('segment_label', '')).upper()
    undercoding = row.get('undercoding_ratio', 0)
    if pd.isna(undercoding): undercoding = 0
    
    vol_metric = float(row.get('final_volume', 0))
    if pd.isna(vol_metric): vol_metric = 0
    
    real_revenue = row.get('metric_est_revenue', 0)
    if pd.isna(real_revenue): real_revenue = 0
    
    # FQHC revenue multiplier
    if 'SEGMENT B' in segment:
        est_rev = real_revenue if real_revenue > 0 else (vol_metric * 300)
    else:
        est_rev = real_revenue if real_revenue > 0 else (vol_metric * 100)
    
    margin = row.get('net_margin', 0)
    if pd.isna(margin): margin = 0
    
    npi_count = int(row.get('npi_count', 1))
    site_count = int(row.get('site_count', 1))
    
    is_aco = row.get('is_aco', False)
    is_oig = row.get('has_oig_flag', False)
    
    # ===== A. ECONOMIC PAIN (40 PTS) =====
    
    # 1. Revenue Leakage (20 pts)
    leakage_pts = 0
    leakage_source = "none"
    
    if undercoding > 0 and undercoding < 0.30:
        leakage_pts = 20
        leakage_source = "verified"
    else:
        # Check CERT benchmarks
        specialty = str(row.get('taxonomy_desc', '')).lower()
        if not specialty or specialty == 'nan':
            specialty = str(row.get('primary_specialty', '')).lower()
        
        projected_rate = 0.0
        for cert_spec, rate in CERT_BENCHMARKS.items():
            if cert_spec in specialty:
                projected_rate = rate
                break
        
        # Fallback to segment proxy
        if projected_rate == 0:
            if 'SEGMENT B' in segment: projected_rate = 0.114
            elif 'SEGMENT D' in segment: projected_rate = 0.104
        
        if projected_rate > 0.10:
            leakage_pts = 15
            leakage_source = "projected"
    
    # 2. Volume Load (15 pts)
    if vol_metric > 25000:
        volume_pts = 15
    elif vol_metric > 10000:
        volume_pts = 10
    else:
        volume_pts = 5
    
    # Check if volume is real or proxy
    volume_source = "real" if row.get('services_count', 0) > 0 else "proxy"
    
    # 3. Margin Pressure (5 pts)
    if margin < 0.03 or 'SEGMENT B' in segment:
        margin_pts = 5
    else:
        margin_pts = 0
    
    pain_total = leakage_pts + volume_pts + margin_pts
    
    # ===== B. STRATEGIC FIT (35 PTS) =====
    
    # 1. Ideal Profile (15 pts)
    if 'SEGMENT B' in segment or 'SEGMENT D' in segment or 'SEGMENT A' in segment:
        profile_pts = 15
    else:
        profile_pts = 5
    
    # 2. Operational Chaos (20 pts)
    if npi_count > 15 or site_count > 3:
        chaos_pts = 20
    elif npi_count > 5:
        chaos_pts = 10
    else:
        chaos_pts = 0
    
    fit_total = profile_pts + chaos_pts
    
    # ===== C. STRATEGIC VALUE (25 PTS) =====
    
    # 1. Deal Value (15 pts)
    if 'SEGMENT B' in segment:
        threshold = 3_000_000
    else:
        threshold = 10_000_000
    
    if est_rev > threshold:
        deal_pts = 15
    else:
        deal_pts = 5
    
    # 2. Market Influence (10 pts)
    if is_aco or is_oig:
        influence_pts = 10
    else:
        influence_pts = 0
    
    value_total = deal_pts + influence_pts
    
    # ===== TOTAL SCORE =====
    total_score = pain_total + fit_total + value_total
    
    # ===== TIER ASSIGNMENT =====
    if total_score >= 70: tier = 'Tier 1'
    elif total_score >= 50: tier = 'Tier 2'
    elif total_score >= 30: tier = 'Tier 3'
    else: tier = 'Tier 4'
    
    # ===== DRIVERS =====
    drivers = []
    if leakage_pts >= 15:
        drivers.append(f"Revenue Leakage ({leakage_source.title()})")
    if volume_pts >= 10:
        drivers.append("High Volume")
    if profile_pts == 15:
        drivers.append("Ideal Profile")
    if chaos_pts >= 15:
        drivers.append("Large Scale")
    if deal_pts == 15:
        drivers.append("High Revenue")
    
    # ===== RETURN DETAILED BREAKDOWN =====
    return {
        'icp_score': total_score,
        'icp_tier': tier,
        'scoring_drivers': " | ".join(drivers) if drivers else "Standard Opportunity",
        
        # Economic Pain (40)
        'score_pain_total': pain_total,
        'score_pain_leakage': leakage_pts,
        'score_pain_volume': volume_pts,
        'score_pain_margin': margin_pts,
        
        # Strategic Fit (35)
        'score_fit_total': fit_total,
        'score_fit_profile': profile_pts,
        'score_fit_chaos': chaos_pts,
        
        # Strategic Value (25)
        'score_strat_total': value_total,
        'score_strat_deal': deal_pts,
        'score_strat_influence': influence_pts,
        
        # Data Source Flags
        'leakage_source': leakage_source,
        'volume_source': volume_source,
        
        # Metrics
        'metric_est_revenue': est_rev,
        'metric_used_volume': vol_metric,
        'data_confidence': 80 if leakage_source == "verified" else 50
    }

def main():
    print("🚀 RUNNING STRICT SUM SCORING ENGINE v8.0...")
    
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file not found: {INPUT_FILE}")
        return
    
    df = pd.read_csv(INPUT_FILE, low_memory=False)
    print(f"Loaded {len(df):,} clinics.")
    
    print("Calculating scores...")
    results = df.apply(calculate_score_v8, axis=1, result_type='expand')
    
    # Merge results back
    for col in results.columns:
        df[col] = results[col]
    
    # Save
    df.to_csv(OUTPUT_FILE, index=False)
    print(f"💾 Saved to {OUTPUT_FILE}")
    
    # Stats
    print("\n📊 TIER DISTRIBUTION:")
    print(df['icp_tier'].value_counts().sort_index())
    
    print(f"\n📈 SCORE STATS:")
    print(f"   Mean: {df['icp_score'].mean():.1f}")
    print(f"   Median: {df['icp_score'].median():.1f}")
    print(f"   Max: {df['icp_score'].max():.0f}")

if __name__ == "__main__":
    main()
