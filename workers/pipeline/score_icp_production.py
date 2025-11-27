"""
ICP SCORING ENGINE v11.0 (SEGMENTED SCORING TRACKS)
Author: Charta Health GTM Strategy

CHANGELOG v11.0 (BEHAVIORAL HEALTH VBC TRACK):
- **SEGMENTED TRACKS:** Separate scoring logic for different care models
  * Track A (Ambulatory): E&M undercoding-focused
  * Track B (Behavioral): VBC readiness + psych complexity
  * Track C (Post-Acute): Margin-based scoring

**TRACK B (BEHAVIORAL HEALTH) LOGIC:**
- **Economic Pain (Max 40):**
  * PRIMARY: Psych Audit Risk (0.75+ → 40pts, 0.50+ → 30pts, else 10-25pts)
  * SECONDARY: Add-on code density (high 90785 usage → complexity bonus)
  * IGNORES: E&M undercoding ratio (not relevant for behavioral)
  
- **Strategic Fit (Max 30):**
  * VBC Readiness: MIPS > 80 = tech-ready for collaborative care (5pts)
  * Segment Alignment: Behavioral Health = core ICP (15pts, up from 10pts)
  * Complexity: Provider count (logarithmic, max 10pts)
  
- **Strategic Value (Max 30):**
  * Volume: Lower thresholds (10k+ patients = max points vs 25k+ for ambulatory)
  * Revenue: Adjusted for behavioral economics ($2M+ = strong deal)

GOAL: Clean, compliant behavioral health orgs score 75-85 based on VBC potential.

CHANGELOG v10.0 (MIPS + HPSA/MUA INTEGRATION):
- **MIPS Score Bonus (Strategic Fit):** +5pts if avg_mips_score > 80 OR < 50
- **HPSA/MUA Bonus (Strategic Fit):** +5pts if clinic in HPSA or MUA county
"""

import pandas as pd
import numpy as np
import os
import math

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
INPUT_FILE = os.path.join(ROOT, "data", "curated", "clinics_enriched_scored.csv")
OUTPUT_FILE = os.path.join(ROOT, "data", "curated", "clinics_scored_final.csv")

# Staging files for MIPS and HPSA/MUA
MIPS_STAGING = os.path.join(ROOT, "data", "staging", "stg_mips_org_scores.csv")
HPSA_MUA_STAGING = os.path.join(ROOT, "data", "staging", "stg_hpsa_mua_flags.csv")

# --- CONTINUOUS SCORING PARAMETERS ---
# Pain scoring breakpoints
UNDERCODING_SEVERE = 0.15  # Worst case → 40 points
UNDERCODING_NATIONAL_AVG = 0.45  # National avg → 15 points
UNDERCODING_FLOOR_SCORE = 10  # Ratios above avg → floor

# Psych risk breakpoints
PSYCH_RISK_SEVERE = 0.75  # Severe → 40 points
PSYCH_RISK_MILD = 0.0  # No risk → 10 points

def detect_track(row):
    """
    Determine which scoring track to use based on segment and data signals.

    Returns: 'BEHAVIORAL', 'POST_ACUTE', or 'AMBULATORY'
    """
    segment = str(row.get('segment_label', '')).upper()
    org_name = str(row.get('org_name', '')).upper()
    psych_codes = row.get('total_psych_codes', 0)
    psych_ratio = row.get('psych_risk_ratio', 0)

    # Track B: Behavioral Health (VERY CONSERVATIVE - only dedicated behavioral practices)
    # NOTE: Segment A is "Behavioral/Specialty" - includes many non-behavioral specialties!
    # Only use name-based detection for true behavioral health organizations

    # 1. Organization name contains behavioral health keywords
    behavioral_keywords = ['BEHAVIORAL', 'PSYCH', 'MENTAL HEALTH', 'COUNSELING', 'THERAPY']
    if any(keyword in org_name for keyword in behavioral_keywords):
        return 'BEHAVIORAL'

    # 2. For Segment A ONLY: Additional check for high psych focus
    # This catches behavioral practices that don't have keywords in name
    if 'SEGMENT A' in segment:
        if pd.notnull(psych_codes) and pd.notnull(psych_ratio):
            # Very high threshold: >2000 psych codes AND >0.70 ratio
            if psych_codes > 2000 and psych_ratio > 0.70:
                return 'BEHAVIORAL'

    # Default: All other Segment A goes to AMBULATORY (they're specialty practices)

    # Track C: Post-Acute / Home Health
    if 'HOME HEALTH' in segment or 'HHA' in segment or 'SEGMENT F' in segment:
        return 'POST_ACUTE'

    # Track A: Ambulatory/Primary (Default)
    return 'AMBULATORY'

def score_undercoding_continuous(ratio):
    """
    Continuous scoring for undercoding ratio (AMBULATORY track).

    Maps:
    - 0.15 (severe) → 40 points
    - 0.45 (national avg) → 15 points
    - >0.45 → 10 points (floor)
    - 0 or missing → 10 points (floor)

    Returns: (score, reasoning_text)
    """
    if ratio <= 0 or pd.isna(ratio):
        return 10, "No undercoding data available"

    if ratio >= UNDERCODING_NATIONAL_AVG:
        return UNDERCODING_FLOOR_SCORE, f"At/above national average ({ratio:.3f})"

    if ratio <= UNDERCODING_SEVERE:
        return 40, f"Severe undercoding ({ratio:.3f})"

    # Linear interpolation between severe (0.15→40) and avg (0.45→15)
    # Formula: score = 40 - ((ratio - 0.15) / (0.45 - 0.15)) * (40 - 15)
    score = 40 - ((ratio - UNDERCODING_SEVERE) / (UNDERCODING_NATIONAL_AVG - UNDERCODING_SEVERE)) * 25
    return round(score, 1), f"Undercoding ratio {ratio:.3f}"

def score_psych_risk_continuous(ratio):
    """
    Continuous scoring for psych audit risk (BEHAVIORAL track).

    Maps:
    - 0.75+ (severe) → 40 points
    - 0.50-0.75 (elevated) → 30-40 points
    - 0.25-0.50 (moderate) → 20-30 points
    - 0.0-0.25 (low/clean) → 10-20 points

    Returns: (score, reasoning_text)
    """
    if ratio <= 0 or pd.isna(ratio):
        return 10, "No psych risk data available"

    if ratio >= PSYCH_RISK_SEVERE:
        return 40, f"Severe psych audit risk ({ratio:.3f})"
    
    if ratio >= 0.50:
        # Elevated risk: 30-40 points
        score = 30 + ((ratio - 0.50) / (PSYCH_RISK_SEVERE - 0.50)) * 10
        return round(score, 1), f"Elevated psych audit risk ({ratio:.3f})"
    
    if ratio >= 0.25:
        # Moderate risk: 20-30 points
        score = 20 + ((ratio - 0.25) / 0.25) * 10
        return round(score, 1), f"Moderate psych complexity ({ratio:.3f})"

    # Low/clean: 10-20 points (still reward some complexity)
    score = 10 + (ratio / 0.25) * 10
    return round(score, 1), f"Low psych risk, clean billing ({ratio:.3f})"


def score_behavioral_vbc_readiness(row):
    """
    Score behavioral health organizations on Value-Based Care readiness.
    
    Factors:
    - MIPS > 80: Tech-ready for CoCM/BHI codes (collaborative care)
    - ACO participation: Already in VBC model
    - Provider count: Capacity for integration
    - HPSA/MUA: Complex patient population (VBC opportunity)
    
    Returns: (score, reasoning_list)
    """
    score = 0
    reasoning = []
    
    # MIPS Quality Score (indicator of EHR sophistication)
    avg_mips = row.get('avg_mips_score', None)
    if pd.notna(avg_mips) and avg_mips > 80:
        score += 5
        reasoning.append(f"MIPS {avg_mips:.1f} = VBC-ready tech infrastructure")
    elif pd.notna(avg_mips) and avg_mips >= 60:
        score += 3
        reasoning.append(f"MIPS {avg_mips:.1f} = moderate tech readiness")
    
    # ACO Participation
    is_aco = str(row.get('is_aco_participant', '')).lower() == 'true'
    if is_aco:
        score += 5
        reasoning.append("ACO participant = VBC experience")
    
    # HPSA/MUA (complex populations benefit most from BHI)
    is_hpsa = str(row.get('is_hpsa', 'False')).lower() == 'true'
    is_mua = str(row.get('is_mua', 'False')).lower() == 'true'
    if is_hpsa or is_mua:
        score += 5
        designation = []
        if is_hpsa: designation.append("HPSA")
        if is_mua: designation.append("MUA")
        reasoning.append(f"{'/'.join(designation)} = complex population, BHI opportunity")
    
    return min(score, 15), reasoning  # Cap at 15 for VBC readiness

def score_provider_count_continuous(npi_count):
    """
    Logarithmic scoring for provider complexity.

    Maps:
    - 1 provider → 0 points
    - 5 providers → 2 points
    - 10 providers → 3 points
    - 20 providers → 4 points
    - 50 providers → 6 points
    - 100+ providers → 10 points (cap)

    Returns: score (float)
    """
    if npi_count <= 1:
        return 0

    if npi_count >= 100:
        return 10

    # Logarithmic scale: score = log(npi_count) / log(100) * 10
    # This maps 1→0, 10→5, 100→10 smoothly
    score = (math.log(npi_count) / math.log(100)) * 10
    return round(score, 1)

def score_revenue_continuous(revenue, segment):
    """
    Logarithmic scoring for deal size based on revenue.

    FQHCs:
    - $100k → 2 points
    - $2M → 7 points
    - $5M+ → 15 points

    Others:
    - $500k → 2 points
    - $5M → 7 points
    - $15M+ → 15 points

    Returns: score (float)
    """
    if pd.isna(revenue) or revenue <= 0:
        return 2  # Minimum score for unknown

    is_fqhc = segment == 'Segment B'

    if is_fqhc:
        min_rev = 100_000
        mid_rev = 2_000_000
        max_rev = 5_000_000
    else:
        min_rev = 500_000
        mid_rev = 5_000_000
        max_rev = 15_000_000

    if revenue >= max_rev:
        return 15

    if revenue <= min_rev:
        return 2

    # Logarithmic scale between min and max
    # Maps min→2, mid→7, max→15
    log_revenue = math.log(revenue)
    log_min = math.log(min_rev)
    log_max = math.log(max_rev)

    score = 2 + ((log_revenue - log_min) / (log_max - log_min)) * 13
    return round(min(15, max(2, score)), 1)

def score_volume_continuous(volume, is_verified):
    """
    Continuous scoring for volume/scale (AMBULATORY track).

    Verified volume:
    - 1k → 3 points
    - 10k → 8 points
    - 25k → 12 points
    - 50k+ → 15 points

    Unverified:
    - Cap at 10 points (penalty for uncertainty)

    Returns: score (float)
    """
    if pd.isna(volume) or volume <= 0:
        return 3  # Minimum

    max_score = 15 if is_verified else 10

    if volume >= 50_000:
        return max_score

    if volume <= 1_000:
        return 3

    # Logarithmic scale: 1k→3, 10k→8, 25k→12, 50k→15
    log_volume = math.log(volume)
    log_min = math.log(1_000)
    log_max = math.log(50_000)

    score = 3 + ((log_volume - log_min) / (log_max - log_min)) * (max_score - 3)
    return round(min(max_score, max(3, score)), 1)


def score_behavioral_volume_continuous(volume, is_verified):
    """
    Behavioral health volume scoring with LOWER thresholds.
    
    Behavioral health practices have lower visit volumes than primary care
    because therapy sessions are longer and capacity is lower.
    
    Verified volume:
    - 500 → 3 points
    - 5k → 8 points
    - 10k → 12 points
    - 20k+ → 15 points
    
    Unverified:
    - Cap at 10 points
    
    Returns: score (float)
    """
    if pd.isna(volume) or volume <= 0:
        return 3  # Minimum
    
    max_score = 15 if is_verified else 10
    
    if volume >= 20_000:
        return max_score
    
    if volume <= 500:
        return 3
    
    # Logarithmic scale adjusted for behavioral health thresholds
    log_volume = math.log(volume)
    log_min = math.log(500)
    log_max = math.log(20_000)
    
    score = 3 + ((log_volume - log_min) / (log_max - log_min)) * (max_score - 3)
    return round(min(max_score, max(3, score)), 1)

def calculate_row_score(row):
    """
    V9.0 CONTINUOUS SCORING

    Pain (40) + Fit (30) + Value (30) = 100 max
    All thresholds replaced with smooth functions.
    """

    # 1. UNPACK DATA
    real_revenue = row.get('total_revenue')
    if pd.isna(real_revenue): real_revenue = row.get('hospital_total_revenue')
    if pd.isna(real_revenue): real_revenue = row.get('fqhc_revenue')
    if pd.isna(real_revenue): real_revenue = row.get('hha_revenue')
    if pd.isna(real_revenue): real_revenue = row.get('real_medicare_revenue')

    # Volume Priority: Real > Estimated > 0
    real_enc = row.get('services_count')
    est_enc = row.get('final_volume')
    vol_metric = real_enc if (pd.notnull(real_enc) and real_enc > 0) else (est_enc if pd.notnull(est_enc) else 0)

    # Check if volume is verified (UDS/Claims)
    volume_source = str(row.get('volume_source', '')).upper()
    is_verified_volume = 'UDS' in volume_source or 'VERIFIED' in volume_source or 'CLAIMS' in volume_source or 'HRSA' in volume_source

    # Signals
    undercoding = row.get('undercoding_ratio', 0)
    if pd.isna(undercoding): undercoding = 0

    psych_risk = row.get('psych_risk_ratio', 0)
    if pd.isna(psych_risk): psych_risk = 0

    is_aco = str(row.get('is_aco_participant', '')).lower() == 'true'
    is_risk = str(row.get('risk_compliance_flag', '')).lower() == 'true' or str(row.get('oig_leie_flag', '')).lower() == 'true'
    npi_count = float(row.get('npi_count', 1))
    site_count = float(row.get('site_count', 1))

    raw_seg = str(row.get('segment_label', 'default'))
    segment = raw_seg.split(' - ')[0] if ' - ' in raw_seg else raw_seg

    confidence = 0
    pain_reasoning = []
    fit_reasoning = []
    strategy_reasoning = []

    # DETECT TRACK
    track = detect_track(row)

    # ========================================
    # PHASE 1: ECONOMIC PAIN (MAX 40 POINTS) - CONTINUOUS
    # ========================================
    if track == 'BEHAVIORAL':
        # Track B: Behavioral Health Pain = VBC Opportunity + Complexity
        # PRIMARY: Psych audit risk (measures complexity/billing intensity)
        pain, reason = score_psych_risk_continuous(psych_risk)
        pain_reasoning.append(f"+{pain:.1f}pts: {reason}")
        
        # SECONDARY: Add-on code density bonus (if we detect high 90785 usage)
        # This rewards practices doing complex therapy (high documentation opportunity)
        total_psych = row.get('total_psych_codes', 0)
        if pd.notna(total_psych) and total_psych > 500:
            # High volume psych practice = documentation/billing sophistication opportunity
            addon_bonus = min(5, (total_psych / 1000) * 5)
            pain += addon_bonus
            pain = min(40, pain)  # Cap at 40
            pain_reasoning.append(f"+{addon_bonus:.1f}pts: High psych volume ({int(total_psych)} codes) = documentation lift")
        
        # Confidence boost if we have strong psych data
        if pain >= 20:
            confidence += 40

    elif track == 'POST_ACUTE':
        # Post-Acute: Margin-based (simplified for now, could be continuous too)
        real_margin = row.get('net_margin')
        if pd.notna(real_margin):
            if real_margin < 0.0:
                pain = 40
                pain_reasoning.append(f"+40pts: Negative margin ({real_margin:.1%})")
            elif real_margin < 0.05:
                # Linear scale: 0-5% margin → 25-40 points
                pain = 25 + (0.05 - real_margin) / 0.05 * 15
                pain = round(pain, 1)
                pain_reasoning.append(f"+{pain:.1f}pts: Low margin ({real_margin:.1%})")
            else:
                pain = 15
                pain_reasoning.append(f"+15pts: Stable margin ({real_margin:.1%})")
            confidence += 30
        else:
            pain = 10
            pain_reasoning.append("+10pts: No margin data")

    else:  # AMBULATORY (Default) - CONTINUOUS
        pain, reason = score_undercoding_continuous(undercoding)
        pain_reasoning.append(f"+{pain:.1f}pts: {reason}")
        if pain >= 30 and undercoding > 0:
            confidence += 50

    # ========================================
    # PHASE 2: STRATEGIC FIT (MAX 30 POINTS) - SEGMENTED
    # ========================================
    
    # Initialize variables for all tracks
    s2_align = 0
    s2_complex = 0
    s2_tech_risk = 0
    s2_mips = 0
    s2_hpsa_mua = 0
    
    if track == 'BEHAVIORAL':
        # Track B: Behavioral Health Fit = VBC Readiness + Segment Alignment
        
        # Segment Alignment (15 pts): Behavioral is CORE ICP
        s2_align = 15
        fit_reasoning.append(f"+15pts: Behavioral Health - Core ICP segment")
        
        # VBC Readiness (Max 15 pts): MIPS + ACO + HPSA/MUA
        vbc_score, vbc_reasons = score_behavioral_vbc_readiness(row)
        for reason in vbc_reasons:
            fit_reasoning.append(reason)
        
        # Complexity (bonus, not core): Provider count adds operational capacity
        s2_complex = score_provider_count_continuous(npi_count)
        if s2_complex > 0:
            fit_reasoning.append(f"+{s2_complex:.1f}pts: {int(npi_count)} providers (operational capacity)")
        
        fit = round(s2_align + vbc_score + min(s2_complex, 5), 1)  # Cap complexity at 5 for behavioral
        
    else:
        # Track A (Ambulatory) / Track C (Post-Acute): Original Logic
        
        # Alignment (Max 15): Based on segment priority
        segment_alignment_scores = {
            'Segment B': 15,  # FQHC (Core ICP)
            'Segment D': 15,  # Urgent Care
            'Segment E': 10,  # Primary Care
            'Segment A': 10,  # Behavioral/Specialty (fallback if not detected as behavioral)
            'Segment C': 8,   # Hospitals
            'Segment F': 5,   # Other
        }
        s2_align = segment_alignment_scores.get(segment, 5)
        fit_reasoning.append(f"+{s2_align}pts: {segment} alignment")

        # Complexity (Max 10): Continuous provider count scoring
        s2_complex = score_provider_count_continuous(npi_count)
        if s2_complex > 0:
            fit_reasoning.append(f"+{s2_complex:.1f}pts: {int(npi_count)} providers")

        # Tech/Risk (Max 5): ACO or OIG risk flag
        s2_tech_risk = 0
        if is_aco:
            s2_tech_risk += 3
            fit_reasoning.append("+3pts: ACO participant")
        if is_risk:
            s2_tech_risk += 2
            fit_reasoning.append("+2pts: Compliance flag")

        # MIPS Score Bonus (Max 5): Reward exceptional quality OR distressed performers
        s2_mips = 0
        avg_mips_score = row.get('avg_mips_score', None)
        if pd.notna(avg_mips_score):
            if avg_mips_score > 80:
                s2_mips = 5
                fit_reasoning.append(f"+5pts: High MIPS quality ({avg_mips_score:.1f})")
            elif avg_mips_score < 50:
                s2_mips = 5
                fit_reasoning.append(f"+5pts: Distressed MIPS performer ({avg_mips_score:.1f})")

        # HPSA/MUA Bonus (Max 5): Payer mix proxy for complexity/fragility
        s2_hpsa_mua = 0
        is_hpsa = str(row.get('is_hpsa', 'False')).lower() == 'true'
        is_mua = str(row.get('is_mua', 'False')).lower() == 'true'
        if is_hpsa or is_mua:
            s2_hpsa_mua = 5
            designation = []
            if is_hpsa: designation.append("HPSA")
            if is_mua: designation.append("MUA")
            fit_reasoning.append(f"+5pts: {'/'.join(designation)} designated area")

        fit = round(s2_align + s2_complex + s2_tech_risk + s2_mips + s2_hpsa_mua, 1)

    # ========================================
    # PHASE 3: STRATEGIC VALUE (MAX 30 POINTS) - SEGMENTED
    # ========================================
    
    if track == 'BEHAVIORAL':
        # Track B: Behavioral Health Value = Revenue + Volume (lower thresholds)
        
        # Revenue Score (Max 15) - Use behavioral economics
        # Estimate: ~$150-200 per visit for therapy
        est_rev = real_revenue if pd.notnull(real_revenue) else (vol_metric * 150)
        
        # Behavioral revenue thresholds (lower than ambulatory)
        if pd.isna(est_rev) or est_rev <= 0:
            s3_revenue = 2
        elif est_rev >= 5_000_000:
            s3_revenue = 15
        elif est_rev <= 250_000:
            s3_revenue = 2
        else:
            # Logarithmic scale: $250k→2pts, $2M→10pts, $5M→15pts
            log_revenue = math.log(est_rev)
            log_min = math.log(250_000)
            log_max = math.log(5_000_000)
            s3_revenue = 2 + ((log_revenue - log_min) / (log_max - log_min)) * 13
            s3_revenue = round(min(15, max(2, s3_revenue)), 1)
        
        strategy_reasoning.append(f"+{s3_revenue:.1f}pts: ${est_rev/1_000_000:.2f}M revenue (behavioral health economics)")
        
        # Volume Score (Max 15) - BEHAVIORAL-SPECIFIC thresholds
        s3_volume = score_behavioral_volume_continuous(vol_metric, is_verified_volume)
        if vol_metric > 0:
            verified_label = "verified" if is_verified_volume else "estimated"
            strategy_reasoning.append(f"+{s3_volume:.1f}pts: {int(vol_metric):,} {verified_label} volume (behavioral thresholds)")
        else:
            strategy_reasoning.append(f"+{s3_volume:.1f}pts: No volume data")
        
        strat = round(s3_revenue + s3_volume, 1)
        
    else:
        # Track A (Ambulatory) / Track C (Post-Acute): Original Logic
        
        # Revenue Score (Max 15) - CONTINUOUS
        # Estimate revenue if missing
        if segment == 'Segment B':
            est_rev = real_revenue if pd.notnull(real_revenue) else (vol_metric * 300)
        else:
            est_rev = real_revenue if pd.notnull(real_revenue) else (vol_metric * 100)

        s3_revenue = score_revenue_continuous(est_rev, segment)
        strategy_reasoning.append(f"+{s3_revenue:.1f}pts: ${est_rev/1_000_000:.2f}M revenue")

        # Volume/Scale Score (Max 15) - CONTINUOUS
        s3_volume = score_volume_continuous(vol_metric, is_verified_volume)
        if vol_metric > 0:
            verified_label = "verified" if is_verified_volume else "estimated"
            strategy_reasoning.append(f"+{s3_volume:.1f}pts: {int(vol_metric):,} {verified_label} volume")
        else:
            strategy_reasoning.append(f"+{s3_volume:.1f}pts: No volume data")

        strat = round(s3_revenue + s3_volume, 1)

    # ========================================
    # TOTALS (STRICT 100-POINT MAX)
    # ========================================
    total = round(pain + fit + strat, 1)

    # Tier Assignment
    tier = 'Tier 4'
    if total >= 70: tier = 'Tier 1'
    elif total >= 50: tier = 'Tier 2'
    elif total >= 30: tier = 'Tier 3'

    # ========================================
    # DRIVERS TEXT (High-level summary)
    # ========================================
    drivers = []

    # Pain Driver
    if pain >= 35:
        if track == 'BEHAVIORAL':
            drivers.append(f"🚨 SEVERE Psych Risk ({psych_risk:.2f})")
        else:
            drivers.append(f"🩸 SEVERE Undercoding ({undercoding:.2f})")
    elif pain >= 25:
        if track == 'BEHAVIORAL':
            drivers.append(f"Psych Track: Audit Risk ({psych_risk:.2f})")
        else:
            drivers.append(f"Primary Track: Undercoding ({undercoding:.2f})")
    else:
        drivers.append(f"{track} Track: Benchmark")

    # Fit Driver
    if s2_align >= 15:
        if segment == 'Segment B':
            drivers.append("FQHC - Core ICP")
        elif segment == 'Segment D':
            drivers.append("Urgent Care - High Fit")
    elif track == 'BEHAVIORAL':
        drivers.append("Behavioral Health - Core ICP")

    # Value Drivers
    if s3_volume >= 12:
        drivers.append(f"High Volume ({int(vol_metric/1000)}k patients)")
    elif site_count > 5:
        drivers.append(f"Multi-Site Network ({int(site_count)} sites)")

    if est_rev > 5_000_000:
        drivers.append(f"Strong Rev (${est_rev/1000000:.1f}M)")

    # Compliance/Risk
    if is_risk:
        drivers.append("Compliance Flag")
    if is_aco:
        drivers.append("ACO Participant")

    # ========================================
    # RETURN STRUCTURE
    # ========================================
    return {
        'icp_score': min(100, total),  # Cap at 100
        'icp_tier': tier,
        'scoring_track': track,
        'data_confidence': min(100, confidence),
        'scoring_drivers': " | ".join(drivers) if drivers else "Standard",

        # Pain Breakdown (Max 40)
        'score_pain_total': round(pain, 1),
        'score_pain_signal': round(pain, 1),
        'score_pain_volume': 0,
        'score_pain_margin': 0,
        'score_pain_compliance': 0,

        # Fit Breakdown (Max 30+10 bonuses)
        'score_fit_total': round(fit, 1),
        'score_fit_align': s2_align,
        'score_fit_complex': round(s2_complex, 1),
        'score_fit_chaos': 0,
        'score_fit_risk': s2_tech_risk,
        'score_fit_mips': s2_mips,
        'score_fit_hpsa_mua': s2_hpsa_mua,

        # Strategy Breakdown (Max 30)
        'score_strat_total': round(strat, 1),
        'score_strat_deal': round(s3_revenue, 1),
        'score_strat_expand': round(s3_volume, 1),
        'score_strat_ref': 0,

        # No bonuses in v9.0
        'score_bonus_strategic_scale': 0,
        'score_base_before_bonus': min(100, total),

        # Metrics
        'metric_est_revenue': est_rev,
        'metric_used_volume': vol_metric,

        # Reasoning (for transparency)
        'score_reasoning_pain': " | ".join(pain_reasoning),
        'score_reasoning_fit': " | ".join(fit_reasoning),
        'score_reasoning_strategy': " | ".join(strategy_reasoning)
    }

# Compatibility wrapper for pipeline_main.py
def calculate_score(row_dict):
    """
    Wrapper function for backward compatibility with pipeline_main.py
    """
    import pandas as pd
    row = pd.Series(row_dict)
    result = calculate_row_score(row)

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
    print("🚀 RUNNING CONTINUOUS SCORING ENGINE v10.0...")
    if not os.path.exists(INPUT_FILE):
        print(f"❌ Input file missing: {INPUT_FILE}")
        return

    df = pd.read_csv(INPUT_FILE, low_memory=False)
    print(f"Loaded {len(df):,} clinics.")

    # Load MIPS staging data
    if os.path.exists(MIPS_STAGING):
        print(f"📥 Loading MIPS data from {MIPS_STAGING}...")
        mips_df = pd.read_csv(MIPS_STAGING)
        mips_df['npi'] = mips_df['org_npi'].astype(str)
        df['npi'] = df['npi'].astype(str)
        df = df.merge(mips_df[['npi', 'avg_mips_score', 'mips_clinician_count']], on='npi', how='left')
        matched_mips = df['avg_mips_score'].notna().sum()
        print(f"   ✅ Matched {matched_mips:,} clinics with MIPS data")
    else:
        print(f"   ⚠️  MIPS staging file not found. Skipping MIPS scoring.")
        df['avg_mips_score'] = None
        df['mips_clinician_count'] = None

    # Load HPSA/MUA staging data with county-level matching
    if os.path.exists(HPSA_MUA_STAGING):
        print(f"📥 Loading HPSA/MUA data from {HPSA_MUA_STAGING}...")
        hpsa_mua_df = pd.read_csv(HPSA_MUA_STAGING)

        # Check if county_name column exists in clinics data
        has_county_data = 'county_name' in df.columns and df['county_name'].notna().sum() > 0

        if has_county_data:
            print(f"   ✅ County data available - using county-level matching")

            # Normalize for matching
            df['state_norm'] = df['state_code'].str.upper().str.strip()
            df['county_norm'] = df['county_name'].str.strip().str.title()
            hpsa_mua_df['state_norm'] = hpsa_mua_df['state'].str.upper().str.strip()
            hpsa_mua_df['county_norm'] = hpsa_mua_df['county_name'].str.strip().str.title()

            # Merge on state + county
            df = df.merge(
                hpsa_mua_df[['state_norm', 'county_norm', 'is_hpsa', 'is_mua']],
                on=['state_norm', 'county_norm'],
                how='left'
            )

            # Drop temporary columns
            df.drop(columns=['state_norm', 'county_norm'], inplace=True)

            # Fill missing values with False
            df['is_hpsa'] = df['is_hpsa'].fillna(False).astype(bool)
            df['is_mua'] = df['is_mua'].fillna(False).astype(bool)

            matched_hpsa = df['is_hpsa'].sum()
            matched_mua = df['is_mua'].sum()
            print(f"   ✅ Matched {matched_hpsa:,} clinics in HPSA counties")
            print(f"   ✅ Matched {matched_mua:,} clinics in MUA counties")
        else:
            print(f"   ⚠️  No county data available - using state-level fallback")

            # Fallback to state-level matching
            hpsa_states = set(hpsa_mua_df[hpsa_mua_df['is_hpsa']]['state'].unique())
            mua_states = set(hpsa_mua_df[hpsa_mua_df['is_mua']]['state'].unique())

            df['is_hpsa'] = df['state_code'].isin(hpsa_states)
            df['is_mua'] = df['state_code'].isin(mua_states)

            matched_hpsa = df['is_hpsa'].sum()
            matched_mua = df['is_mua'].sum()
            print(f"   ✅ Marked {matched_hpsa:,} clinics in HPSA states")
            print(f"   ✅ Marked {matched_mua:,} clinics in MUA states")
    else:
        print(f"   ⚠️  HPSA/MUA staging file not found. Skipping HPSA/MUA scoring.")
        df['is_hpsa'] = False
        df['is_mua'] = False

    # Ensure numeric
    cols = ['services_count', 'final_volume', 'total_revenue', 'npi_count', 'undercoding_ratio', 'net_margin',
            'hospital_margin', 'hha_margin', 'fqhc_margin', 'hospital_total_revenue', 'fqhc_revenue', 'hha_revenue',
            'real_medicare_revenue', 'psych_risk_ratio', 'total_psych_codes', 'site_count']
    for c in cols:
        if c in df.columns: df[c] = pd.to_numeric(df[c], errors='coerce')

    print("Calculating continuous scores...")
    scores = df.apply(calculate_row_score, axis=1, result_type='expand')

    # Clean merge
    cols_to_drop = [c for c in scores.columns if c in df.columns]
    if cols_to_drop: df.drop(columns=cols_to_drop, inplace=True)

    final_df = pd.concat([df, scores], axis=1)
    final_df.sort_values('icp_score', ascending=False, inplace=True)

    final_df.to_csv(OUTPUT_FILE, index=False)
    print(f"💾 Saved to {OUTPUT_FILE}")

    # Report by Track
    print("\n📊 CONTINUOUS SCORING RESULTS BY TRACK:")
    for track in ['AMBULATORY', 'BEHAVIORAL', 'POST_ACUTE']:
        track_df = final_df[final_df['scoring_track'] == track]
        if len(track_df) > 0:
            print(f"\n{track} Track ({len(track_df):,} clinics):")
            print(f"  Avg Score: {track_df['icp_score'].mean():.1f}")
            print(f"  Score Range: {track_df['icp_score'].min():.1f} - {track_df['icp_score'].max():.1f}")
            tier_counts = track_df['icp_tier'].value_counts()
            for tier in ['Tier 1', 'Tier 2', 'Tier 3', 'Tier 4']:
                count = tier_counts.get(tier, 0)
                print(f"  {tier}: {count:,}")

    print("\n📊 OVERALL TIER DISTRIBUTION:")
    print(final_df['icp_tier'].value_counts())

    # Show unique score distribution
    unique_scores = final_df['icp_score'].nunique()
    print(f"\n✨ UNIQUE SCORES: {unique_scores:,} (vs ~10 in v8.0)")

    # Sample of score breakdowns
    print("\n📋 SAMPLE CONTINUOUS SCORES:")
    sample = final_df.head(5)[['org_name', 'icp_score', 'score_pain_total', 'score_fit_total', 'score_strat_total']]
    print(sample.to_string(index=False))

if __name__ == "__main__":
    main()
