"""
ICP SCORING ENGINE v6.0 (MULTI-TRACK & CHAOS LOGIC)
Author: Charta Health GTM Strategy

CHANGELOG v6.0:
- Multi-Track Scoring: Detects clinic type and applies appropriate formula
  * Track A: Ambulatory/Primary (Undercoding Signal)
  * Track B: Behavioral Health (Audit Risk Signal)
  * Track C: Post-Acute/Home Health (Margin + Compliance)
- Operational Chaos Score: Rewards complexity/chaos instead of tech readiness
- Health System Penalty: Decreases score for rigid IT environments
"""

import pandas as pd
import numpy as np
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
INPUT_FILE = os.path.join(ROOT, "data", "curated", "clinics_enriched_scored.csv")
OUTPUT_FILE = os.path.join(ROOT, "data", "curated", "clinics_scored_final.csv")

# --- CONFIGURATION ---
SEGMENT_ALIGNMENT_SCORES = {
    'Segment B': 20,  # FQHC (MAX FIT - Core ICP)
    'Segment D': 15,  # Urgent Care
    'Segment E': 12,  # Primary Care
    'Segment A': 12,  # Behavioral/Specialty
    'Segment F': 6,   # Other
    'Segment C': 8,   # Hospitals (lower due to complexity)
    'default': 5
}

# Load CERT Benchmarks
CERT_FILE = os.path.join(ROOT, "data", "raw", "cert_specialty_benchmarks.csv")
CERT_BENCHMARKS = {}
if os.path.exists(CERT_FILE):
    try:
        cert_df = pd.read_csv(CERT_FILE)
        # Create dictionary: {Specialty: Rate}
        # Normalize keys to lowercase for easier matching
        CERT_BENCHMARKS = dict(zip(cert_df['provider_type'].str.lower(), cert_df['improper_payment_rate']))
        print(f"✅ Loaded {len(CERT_BENCHMARKS)} CERT benchmarks.")
    except Exception as e:
        print(f"⚠️ Failed to load CERT benchmarks: {e}")
else:
    print(f"⚠️ CERT benchmarks file not found: {CERT_FILE}")

def detect_track(row):
    """
    Determine which scoring track to use based on segment and data signals.
    
    Returns: 'BEHAVIORAL', 'POST_ACUTE', or 'AMBULATORY'
    """
    segment = str(row.get('segment_label', '')).upper()
    psych_codes = row.get('total_psych_codes', 0)
    psych_ratio = row.get('psych_risk_ratio', 0)
    
    # Track B: Behavioral Health
    if 'BEHAVIORAL' in segment or 'PSYCH' in segment:
        return 'BEHAVIORAL'
    if pd.notnull(psych_codes) and psych_codes > 100:
        return 'BEHAVIORAL'
    
    # Track C: Post-Acute / Home Health
    if 'HOME HEALTH' in segment or 'HHA' in segment or 'SEGMENT F' in segment:
        return 'POST_ACUTE'
    
    # Track A: Ambulatory/Primary (Default)
    return 'AMBULATORY'

def calculate_operational_chaos(row):
    """
    Operational Chaos Score (replaces Tech Readiness).
    Rewards complexity/chaos that indicates need for automation.
    
    Max: 20 points (v7.0 Aggressive Scale)
    """
    npi_count = float(row.get('npi_count', 1))
    segment = str(row.get('segment_label', '')).upper()
    
    # FIX: Ghost Data Bug - Use ONLY real services_count (not final_volume)
    real_vol = row.get('services_count')
    if pd.isna(real_vol): real_vol = 0
    real_vol = float(real_vol)
    
    # v7.0 SCALE = CHAOS
    # If large group or high volume -> Max Chaos immediately
    if npi_count > 15 or real_vol > 20000:
        return 20
        
    margin = row.get('net_margin')
    if pd.isna(margin): margin = row.get('hospital_margin')
    if pd.isna(margin): margin = row.get('hha_margin')
    if pd.isna(margin): margin = row.get('fqhc_margin')
    
    chaos_score = 0
    
    # Small Groups (2-10 providers): Likely lack sophisticated RCM
    if 2 <= npi_count <= 10:
        chaos_score += 8
    elif 11 <= npi_count <= 50:
        chaos_score += 4  # Medium groups
    # REMOVED: Solo practitioners bonus (too simple)
    
    # FIXED: Burnout Signal (High volume per doctor) - ONLY if volume is REAL
    if npi_count > 0 and real_vol > 0:
        volume_per_doctor = real_vol / npi_count
        if volume_per_doctor > 4000:
            chaos_score += 5  # High burnout indicator
    
    # Home Health / Post-Acute: High transfer volume = chaos
    if 'HOME HEALTH' in segment or 'HHA' in segment:
        chaos_score += 2
    
    # NEW: Desperation Override for Hospitals
    if 'HOSPITAL' in segment or 'HEALTH SYSTEM' in segment or 'SEGMENT C' in segment:
        if pd.notnull(margin):
            if margin > 0.05:
                chaos_score -= 5  # Comfortable hospitals: rigid IT penalty
            elif margin < 0.0:
                chaos_score += 5  # Losing money: financial pain overrides IT rigidity
        else:
            chaos_score -= 5  # Default penalty if no margin data
    
    return max(0, min(20, chaos_score))

def calculate_row_score(row):
    # 1. UNPACK DATA
    real_margin = row.get('net_margin')
    if pd.isna(real_margin): real_margin = row.get('hospital_margin')
    if pd.isna(real_margin): real_margin = row.get('hha_margin')
    if pd.isna(real_margin): real_margin = row.get('fqhc_margin')
    
    real_revenue = row.get('total_revenue')
    if pd.isna(real_revenue): real_revenue = row.get('hospital_total_revenue')
    if pd.isna(real_revenue): real_revenue = row.get('fqhc_revenue')
    if pd.isna(real_revenue): real_revenue = row.get('hha_revenue')
    if pd.isna(real_revenue): real_revenue = row.get('real_medicare_revenue')
    
    # Volume Priority: Real > Estimated > 0
    real_enc = row.get('services_count')
    est_enc = row.get('final_volume')
    vol_metric = real_enc if (pd.notnull(real_enc) and real_enc > 0) else (est_enc if pd.notnull(est_enc) else 0)
    
    # Signals
    undercoding = row.get('undercoding_ratio', 0)
    psych_risk = row.get('psych_risk_ratio', 0)
    is_aco = str(row.get('is_aco_participant', '')).lower() == 'true'
    is_risk = str(row.get('risk_compliance_flag', '')).lower() == 'true' or str(row.get('oig_leie_flag', '')).lower() == 'true'
    npi_count = float(row.get('npi_count', 1))
    
    raw_seg = str(row.get('segment_label', 'default'))
    segment = raw_seg.split(' - ')[0] if ' - ' in raw_seg else raw_seg
    
    confidence = 0
    
    # DETECT TRACK
    track = detect_track(row)
    
    # --- PHASE 1: ECONOMIC PAIN (45 pts, increased from 40) ---
    s1_pain_signal = 0
    
    if track == 'BEHAVIORAL':
        # Track B: Psych Audit Risk
        if pd.notnull(psych_risk) and psych_risk > 0:
            confidence += 50
            if psych_risk > 0.80: s1_pain_signal = 25  # High Audit Risk (increased from 20)
            elif psych_risk > 0.70: s1_pain_signal = 18
            elif psych_risk > 0.60: s1_pain_signal = 12
            else: s1_pain_signal = 6
    
    elif track == 'POST_ACUTE':
        # Track C: Margin Pressure + Compliance Risk
        if pd.notnull(real_margin):
            confidence += 30
            if real_margin < 0.02: s1_pain_signal = 15
            elif real_margin < 0.05: s1_pain_signal = 10
            else: s1_pain_signal = 5
        
        # Bonus for compliance risk
        if is_risk:
            s1_pain_signal += 5
    
    else:  # AMBULATORY (Default)
        # Track A: Undercoding (INCREASED max from 20 to 25 pts)
        if pd.notnull(undercoding) and undercoding > 0:
            confidence += 50
            if undercoding < 0.30: s1_pain_signal = 25  # Severe (increased from 20)
            elif undercoding < 0.45: s1_pain_signal = 15  # Moderate (increased from 12)
            else: s1_pain_signal = 8  # Mild (increased from 5)
        
        # NEW: Implied Pain for High-Volume FQHCs
        # If no verified undercoding, but high volume FQHC -> Implied Leakage
        elif segment == 'Segment B' and vol_metric > 10000 and s1_pain_signal == 0:
            s1_pain_signal = 15
            # Note: We append driver later
            
        # NEW: CERT Benchmark Projection (if no verified data & no implied FQHC pain)
        elif s1_pain_signal == 0:
            # Try to match specialty to CERT benchmarks
            specialty = str(row.get('taxonomy_desc', '')).lower()
            if not specialty or specialty == 'nan':
                specialty = str(row.get('primary_specialty', '')).lower()
            
            projected_rate = 0.0
            matched_spec = None
            
            # Simple substring match
            for cert_spec, rate in CERT_BENCHMARKS.items():
                if cert_spec in specialty:
                    projected_rate = rate
                    matched_spec = cert_spec
                    break
            
            # If no match, try segment mapping
            if projected_rate == 0:
                if segment == 'Segment B': projected_rate = 0.114 # Family Practice proxy
                elif segment == 'Segment D': projected_rate = 0.104 # Emergency/Urgent proxy
            
            # AGGRESSIVE INFERENCE (v7.0): High Risk = Verified Pain
            if projected_rate > 0.10:
                s1_pain_signal = 20 # "High Projected Risk" (Treat as Verified)
            elif projected_rate > 0.05:
                s1_pain_signal = 10 # "Moderate Projected Risk"
                
    # NEW: Overcoding / Compliance Risk (up to 15 pts)
    overcoding = row.get('overcoding_ratio', 0)
    if pd.isna(overcoding): overcoding = 0
    
    s1_compliance_risk = 0
    if overcoding > 0.10:
        confidence += 30
        s1_compliance_risk = 15  # High compliance risk
        # Note: This can stack with undercoding for clinics with both issues
    
    # Alternative: Denial Rate (if overcoding not available)
    denial_rate = row.get('denial_rate', 0)
    if s1_compliance_risk == 0 and pd.notnull(denial_rate) and denial_rate > 0.10:
        confidence += 20
        if denial_rate > 0.20: s1_compliance_risk = 12
        else: s1_compliance_risk = 6
    
    # Volume (Universal across all tracks)
    s1_volume = 0
    if vol_metric > 50000: s1_volume = 12
    elif vol_metric > 25000: s1_volume = 10
    elif vol_metric > 10000: s1_volume = 8
    elif vol_metric > 5000: s1_volume = 5
    if vol_metric > 0: confidence += 20

    # Margin (if not already scored in Track C)
    s1_margin = 0
    if track != 'POST_ACUTE':
        if pd.notnull(real_margin):
            confidence += 30
            if real_margin < 0.02: s1_margin = 8
            elif real_margin < 0.05: s1_margin = 5

    pain = s1_pain_signal + s1_volume + s1_margin + s1_compliance_risk

    # --- PHASE 2: STRATEGIC FIT (40 pts, increased from 35) ---
    s2_align = SEGMENT_ALIGNMENT_SCORES.get(segment, 5)
    
    # Complexity (based on provider count)
    s2_complex = 0
    if segment == 'Segment B': s2_complex = 10
    elif segment == 'Segment C': s2_complex = 8
    elif npi_count > 15: s2_complex = 10 # Scale Override: Large groups imply complexity
    elif npi_count > 5: s2_complex = 5
    
    # Operational Chaos (ENHANCED: now max 15 pts, was 10)
    s2_chaos = calculate_operational_chaos(row)
    
    # Risk Bonus
    s2_risk = 2 if is_risk else 0
    
    fit = s2_align + s2_complex + s2_chaos + s2_risk

    # --- PHASE 3: STRATEGIC VALUE (25 pts) ---
    # Deal Size (Segment-Specific)
    s3_deal = 0
    
    # --- PHASE 3: STRATEGIC VALUE (15 pts) ---
    s3_deal = 0
    
    # VERTICAL VALUATION: FQHCs get higher revenue multiplier ($300/visit)
    if segment == 'Segment B':
        est_rev = real_revenue if pd.notnull(real_revenue) else (vol_metric * 300)
    else:
        est_rev = real_revenue if pd.notnull(real_revenue) else (vol_metric * 100)
    
    # Revenue Thresholds (Recalibrated for FQHC/Urgent Care)
    if segment == 'Segment B':
        # FQHC Specific Thresholds ($2M Max)
        if est_rev > 2_000_000: s3_deal = 12
        elif est_rev > 1_000_000: s3_deal = 8
        elif est_rev > 500_000: s3_deal = 4
    elif segment == 'Segment D':
        # Urgent Care Thresholds
        if est_rev > 3_000_000: s3_deal = 12
        elif est_rev > 1_000_000: s3_deal = 8
        elif est_rev > 500_000: s3_deal = 4
    else:
        # Standard thresholds
        if est_rev > 5_000_000: s3_deal = 12
        elif est_rev > 1_000_000: s3_deal = 8
        elif est_rev > 500_000: s3_deal = 4
    
    # Expansion Potential
    s3_expand = 0
    if npi_count > 20: s3_expand = 3
    elif npi_count > 10: s3_expand = 2
    
    s3_ref = 5 if is_aco else 0 # This line was not in the snippet, but was in the original code. Keeping it.
    
    strat = s3_deal + s3_expand + s3_ref

    # --- TOTALS ---
    total = min(100, pain + fit + strat)
    
    # Tier Assignment
    # --- TIER ASSIGNMENT (v7.0 Aggressive) ---
    tier = 'Tier 4'
    if total >= 70: tier = 'Tier 1'
    elif total >= 50: tier = 'Tier 2'
    elif total >= 30: tier = 'Tier 3'
    
    # Drivers Text (Track-Specific)
    drivers = []
    
    if track == 'BEHAVIORAL':
        drivers.append(f"Psych Track: Audit Risk ({psych_risk:.2f})")
        if s1_pain_signal >= 18:
            drivers.append("High Audit Risk")
    elif track == 'POST_ACUTE':
        drivers.append("Post-Acute Track")
        if s1_pain_signal >= 10:
            drivers.append("Margin Pressure")
        if is_risk:
            drivers.append("Compliance Risk")
    else:  # AMBULATORY
        drivers.append(f"Primary Track: Undercoding ({undercoding:.2f})")
        if s1_pain_signal >= 15:
            if pd.notnull(undercoding) and undercoding > 0:
                drivers.append("Severe Undercoding")
            elif segment == 'Segment B' and vol_metric > 10000:
                drivers.append("Implied Revenue Leakage")
        
        # CERT Driver
        if s1_pain_signal >= 10 and (pd.isnull(undercoding) or undercoding == 0):
             if s1_pain_signal >= 20: drivers.append("Critical Benchmark Risk")
             else: drivers.append("Benchmark Risk")
    
    # NEW: Compliance Risk Driver
    if s1_compliance_risk >= 10:
        drivers.append("Compliance Risk")
    
    # NEW: Burnout Signal
    if npi_count > 0 and pd.notnull(vol_metric) and vol_metric > 0:
        if (vol_metric / npi_count) > 4000:
            drivers.append("High Burnout")
    
    # NEW: Financial Desperation
    if pd.notnull(real_margin) and real_margin < 0.0:
        drivers.append("Financial Desperation")
    
    if s1_volume >= 10:
        drivers.append("High Volume")
    if s3_deal >= 8:
        drivers.append(f"Strong Rev (${est_rev/1000000:.1f}M)")
    if s2_chaos >= 8:
        drivers.append("Operational Chaos")
    
    return {
        'icp_score': total,
        'icp_tier': tier,
        'scoring_track': track,
        'data_confidence': min(100, confidence),
        'scoring_drivers': " | ".join(drivers) if drivers else "Standard",
        'score_pain_total': pain,
        'score_pain_signal': s1_pain_signal,
        'score_pain_volume': s1_volume,
        'score_pain_margin': s1_margin,
        'score_pain_compliance': s1_compliance_risk,
        
        'score_fit_total': fit,
        'score_fit_align': s2_align,
        'score_fit_complex': s2_complex,
        'score_fit_chaos': s2_chaos,
        'score_fit_risk': s2_risk,
        
        'score_strat_total': strat,
        'score_strat_deal': s3_deal,
        'score_strat_expand': s3_expand,
        'score_strat_ref': s3_ref,
        
        'metric_est_revenue': est_rev,
        'metric_used_volume': vol_metric
    }

# Compatibility wrapper for pipeline_main.py
def calculate_score(row_dict):
    """
    Wrapper function for backward compatibility with pipeline_main.py
    Converts dict input to Series and calls calculate_row_score
    Transforms new return format to old pipeline format
    """
    import pandas as pd
    row = pd.Series(row_dict)
    result = calculate_row_score(row)
    
    # Transform to old format expected by pipeline
    return {
        'total': result['icp_score'],
        'tier': result['icp_tier'],
        'confidence': result['data_confidence'],
        'rationale': result['scoring_drivers'],
        'estimates': {
            'revenue': result['metric_est_revenue'],
            'encounters': result['metric_used_volume']
        },
        'breakdown': {
            'pain_total': result['score_pain_total'],
            'pain_signal': result['score_pain_signal'],
            'pain_volume': result['score_pain_volume'],
            'pain_margin': result['score_pain_margin'],
            'fit_total': result['score_fit_total'],
            'fit_align': result['score_fit_align'],
            'fit_complex': result['score_fit_complex'],
            'fit_chaos': result['score_fit_chaos'],
            'strat_total': result['score_strat_total'],
            'strat_deal': result['score_strat_deal'],
            'strat_expand': result['score_strat_expand']
        }
    }

def main():
    print("🚀 RUNNING MULTI-TRACK SCORING ENGINE v6.0...")
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file missing: {INPUT_FILE}")
        return

    df = pd.read_csv(INPUT_FILE, low_memory=False)
    print(f"Loaded {len(df):,} clinics.")
    
    # Ensure numeric
    cols = ['services_count', 'final_volume', 'total_revenue', 'npi_count', 'undercoding_ratio', 'net_margin',
            'hospital_margin', 'hha_margin', 'fqhc_margin', 'hospital_total_revenue', 'fqhc_revenue', 'hha_revenue', 
            'real_medicare_revenue', 'psych_risk_ratio', 'total_psych_codes']
    for c in cols:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')

    print("Calculating scores...")
    scores = df.apply(calculate_row_score, axis=1, result_type='expand')
    
    # Clean merge
    cols_to_drop = [c for c in scores.columns if c in df.columns]
    if cols_to_drop: df.drop(columns=cols_to_drop, inplace=True)
    
    final_df = pd.concat([df, scores], axis=1)
    final_df.sort_values('icp_score', ascending=False, inplace=True)
    
    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"💾 Saved to {OUTPUT_FILE}")
    
    # Report by Track
    print("\n📊 SCORING RESULTS BY TRACK:")
    for track in ['AMBULATORY', 'BEHAVIORAL', 'POST_ACUTE']:
        track_df = final_df[final_df['scoring_track'] == track]
        if len(track_df) > 0:
            print(f"\n{track} Track ({len(track_df):,} clinics):")
            print(f"  Avg Score: {track_df['icp_score'].mean():.1f}")
            tier_counts = track_df['icp_tier'].value_counts()
            for tier in ['Tier 1', 'Tier 2', 'Tier 3', 'Tier 4']:
                count = tier_counts.get(tier, 0)
                print(f"  {tier}: {count:,}")
    
    print("\n📊 OVERALL TIER DISTRIBUTION:")
    print(final_df['icp_tier'].value_counts())

if __name__ == "__main__":
    main()