"""
ICP (Ideal Customer Profile) Scoring Module

This module implements a 6-category ICP scoring system for healthcare clinics:
1. Fit Score (0-20): Based on specialty type, clinic structure, service type
2. Pain Score (0-20): Based on denial rates, staffing shortages, revenue loss
3. Compliance Risk Score (0-10): Based on audit triggers, flagged status, CMS participation
4. Propensity to Buy Score (0-10): Based on payer mix, billing complexity, RCM staff presence
5. Operational Scale Score (0-20): Based on provider count, patient volume, billing size
6. Strategic Segment Score (0-20): Match to Segment A/B/C definitions

Total ICP Score: 0-100 (sum of all 6 categories)
Tier Assignment: Tier 1 (≥80), Tier 2 (60-79), Tier 3 (<60)
Segment Assignment: A (Behavioral/Home Health), B (FQHC/Rural), C (Multi-Specialty/Growth)
"""

from __future__ import annotations

import math
import os
import re
import hashlib
from typing import Dict, List, Tuple, Any, Optional, Set
from collections import defaultdict
import pandas as pd
import numpy as np

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_CURATED = os.path.join(ROOT, "data", "curated")
CLINICS_SCORED = os.path.join(DATA_CURATED, "clinics_scored.csv")
CLINICS_ICP = os.path.join(DATA_CURATED, "clinics_icp.csv")
ICP_SCORES = os.path.join(DATA_CURATED, "icp_scores.csv")
NETWORKS_ICP = os.path.join(DATA_CURATED, "networks_icp.csv")
CLINICS_ICP_WITH_NETWORKS = os.path.join(DATA_CURATED, "clinics_icp_with_networks.csv")

# Segment definitions
SEGMENT_A_KEYWORDS = {
    "behavioral health",
    "mental health",
    "substance abuse",
    "psychiatry",
    "psychology",
    "home health",
    "home care",
    "hospice",
    "palliative",
}

SEGMENT_B_KEYWORDS = {
    "fqhc",
    "federally qualified",
    "rural health",
    "community health",
    "hrsa",
}

SEGMENT_C_KEYWORDS = {
    "multi-specialty",
    "multi specialty",
    "health system",
    "hospital-affiliated",
    "hospital affiliated",
    "private equity",
    "pe-backed",
}


def safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float, returning default if conversion fails."""
    try:
        if pd.isna(value) or value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int, returning default if conversion fails."""
    return int(round(safe_float(value, default)))


def normalize_text(value: Any) -> str:
    """Normalize text to lowercase and strip whitespace."""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip().lower()


def normalize_score(value: float, min_val: float, max_val: float, target_max: float) -> float:
    """
    Normalize a value to 0-target_max scale using min-max normalization.
    
    Args:
        value: The value to normalize
        min_val: Minimum value in the dataset
        max_val: Maximum value in the dataset
        target_max: Target maximum score (e.g., 20 for Fit Score)
    
    Returns:
        Normalized score between 0 and target_max
    """
    if max_val == min_val:
        return target_max / 2  # If no variance, return midpoint
    
    normalized = (value - min_val) / (max_val - min_val)
    return min(target_max, max(0, normalized * target_max))


# ============================================================================
# CATEGORY 1: FIT SCORE (0-20)
# ============================================================================

def compute_fit_score(row: Dict[str, Any], stats: Dict[str, Any]) -> Tuple[float, List[Dict[str, str]]]:
    """
    Compute Fit Score (0-20) based on specialty type, clinic structure, and service type.
    
    Sources:
    - segment_label (from enrichment pipeline)
    - npi_count (provider count)
    - site_count (location count)
    - services_count (service breadth)
    - taxonomy (from NPI registry)
    
    Logic:
    - Behavioral Health / Home Health: 18-20 points (highest fit)
    - Primary Care / FQHC: 15-17 points (strong fit)
    - Multi-Specialty: 12-15 points (moderate fit)
    - Other specialties: 8-12 points (lower fit)
    - Bonus points for complexity indicators (multi-site, high service count)
    
    Returns:
        Tuple of (score, bibliography)
    """
    bibliography = []
    score = 0.0
    
    # Primary specialty match (0-15 points)
    segment = normalize_text(row.get("segment_label", ""))
    sector = normalize_text(row.get("sector", ""))
    
    if not segment and not sector:
        bibliography.append({
            "score": "fit",
            "sources": ["segment_label", "sector"],
            "status": "MISSING",
            "note": "No specialty information available"
        })
        return 0.0, bibliography
    
    # Segment-based scoring
    if any(kw in segment for kw in SEGMENT_A_KEYWORDS):
        score += 18.0
        bibliography.append({
            "score": "fit",
            "sources": ["segment_label"],
            "value": segment,
            "reason": "Behavioral Health / Home Health (high fit)"
        })
    elif any(kw in segment for kw in SEGMENT_B_KEYWORDS) or "fqhc" in sector:
        score += 16.0
        bibliography.append({
            "score": "fit",
            "sources": ["segment_label", "sector"],
            "value": f"{segment} / {sector}",
            "reason": "FQHC / Community Health (strong fit)"
        })
    elif "primary care" in segment or "family medicine" in segment:
        score += 15.0
        bibliography.append({
            "score": "fit",
            "sources": ["segment_label"],
            "value": segment,
            "reason": "Primary Care (strong fit)"
        })
    elif any(kw in segment for kw in SEGMENT_C_KEYWORDS):
        score += 13.0
        bibliography.append({
            "score": "fit",
            "sources": ["segment_label"],
            "value": segment,
            "reason": "Multi-Specialty (moderate fit)"
        })
    else:
        score += 10.0
        bibliography.append({
            "score": "fit",
            "sources": ["segment_label"],
            "value": segment,
            "reason": "Other specialty (lower fit)"
        })
    
    # Complexity bonuses (0-5 points)
    site_count = safe_float(row.get("site_count", 0))
    services_count = safe_float(row.get("services_count", 0))
    
    if site_count >= 5:
        score += 2.0
        bibliography.append({
            "score": "fit",
            "sources": ["site_count"],
            "value": site_count,
            "reason": "Multi-site complexity bonus"
        })
    
    if services_count >= 10:
        score += 3.0
        bibliography.append({
            "score": "fit",
            "sources": ["services_count"],
            "value": services_count,
            "reason": "High service breadth bonus"
        })
    
    return min(20.0, round(score, 2)), bibliography


# ============================================================================
# CATEGORY 2: PAIN SCORE (0-20)
# ============================================================================

def compute_pain_score(row: Dict[str, Any], stats: Dict[str, Any]) -> Tuple[float, List[Dict[str, str]]]:
    """
    Compute Pain Score (0-20) based on denial rates, staffing shortages, and revenue loss.
    
    Sources:
    - denial_pressure (from existing enrichment)
    - allowed_amt / bene_count (revenue per patient)
    - coding_complexity (proxy for documentation issues)
    - segment indicators (high-risk segments)
    
    Logic:
    - High denial pressure: 8-10 points
    - Low revenue per beneficiary: 5-7 points
    - High coding complexity: 3-5 points
    - Normalize to 0-20 scale
    
    Returns:
        Tuple of (score, bibliography)
    """
    bibliography = []
    score = 0.0
    
    # Denial pressure (0-10 points)
    denial_pressure = safe_float(row.get("denial_pressure", 0))
    
    if denial_pressure > 0:
        # Normalize denial_pressure (typically 0-10 scale) to 0-10 points
        denial_points = min(10.0, denial_pressure)
        score += denial_points
        bibliography.append({
            "score": "pain",
            "sources": ["denial_pressure"],
            "value": denial_pressure,
            "reason": f"Denial pressure indicates reimbursement pain"
        })
    else:
        bibliography.append({
            "score": "pain",
            "sources": ["denial_pressure"],
            "status": "MISSING",
            "note": "No denial pressure data available"
        })
    
    # Revenue strain indicator (0-7 points)
    allowed_amt = safe_float(row.get("allowed_amt", 0))
    bene_count = safe_float(row.get("bene_count", 0))
    
    if allowed_amt > 0 and bene_count > 0:
        revenue_per_bene = allowed_amt / bene_count
        
        # Lower revenue per patient = higher pain
        if revenue_per_bene < 300:
            revenue_points = 7.0
            reason = "Very low revenue per patient (<$300)"
        elif revenue_per_bene < 600:
            revenue_points = 5.0
            reason = "Low revenue per patient (<$600)"
        elif revenue_per_bene < 1000:
            revenue_points = 3.0
            reason = "Moderate revenue per patient (<$1000)"
        else:
            revenue_points = 1.0
            reason = "Adequate revenue per patient"
        
        score += revenue_points
        bibliography.append({
            "score": "pain",
            "sources": ["allowed_amt", "bene_count"],
            "value": f"${revenue_per_bene:.0f}/patient",
            "reason": reason
        })
    else:
        bibliography.append({
            "score": "pain",
            "sources": ["allowed_amt", "bene_count"],
            "status": "MISSING",
            "note": "No Medicare utilization data available"
        })
    
    # Coding complexity as pain indicator (0-3 points)
    coding_complexity = safe_float(row.get("coding_complexity", 0))
    
    if coding_complexity >= 10:
        complexity_points = 3.0
        score += complexity_points
        bibliography.append({
            "score": "pain",
            "sources": ["coding_complexity"],
            "value": coding_complexity,
            "reason": "High coding complexity suggests documentation challenges"
        })
    elif coding_complexity >= 5:
        complexity_points = 1.5
        score += complexity_points
        bibliography.append({
            "score": "pain",
            "sources": ["coding_complexity"],
            "value": coding_complexity,
            "reason": "Moderate coding complexity"
        })
    
    return min(20.0, round(score, 2)), bibliography


# ============================================================================
# CATEGORY 3: COMPLIANCE RISK SCORE (0-10)
# ============================================================================

def compute_compliance_score(row: Dict[str, Any], stats: Dict[str, Any]) -> Tuple[float, List[Dict[str, str]]]:
    """
    Compute Compliance Risk Score (0-10) based on audit triggers, OIG flags, and CMS participation.
    
    Sources:
    - oig_leie_flag (from OIG LEIE enrichment)
    - segment (high-risk segments like Home Health)
    - aco_member (ACO participation = quality focus)
    - fqhc_flag (FQHC = higher compliance scrutiny)
    
    Logic:
    - OIG LEIE match: 10 points (highest risk)
    - Home Health / Post-Acute: 7-8 points (high scrutiny segment)
    - Behavioral Health with high denial: 6-7 points
    - FQHC: 5 points (moderate compliance focus)
    - ACO member: 3-4 points (quality reporting requirements)
    
    Returns:
        Tuple of (score, bibliography)
    """
    bibliography = []
    score = 0.0
    
    # OIG LEIE flag (highest priority signal)
    oig_flag = row.get("oig_leie_flag")
    if oig_flag is True or (isinstance(oig_flag, (int, float)) and oig_flag >= 1):
        score = 10.0
        bibliography.append({
            "score": "compliance_risk",
            "sources": ["oig_leie_flag"],
            "value": "TRUE",
            "reason": "OIG LEIE exclusion match (maximum compliance risk)"
        })
        return 10.0, bibliography
    
    # Segment-based risk
    segment = normalize_text(row.get("segment_label", ""))
    
    if "home health" in segment or "post acute" in segment or "hospice" in segment:
        score += 8.0
        bibliography.append({
            "score": "compliance_risk",
            "sources": ["segment_label"],
            "value": segment,
            "reason": "Home Health / Post-Acute (high CMS scrutiny)"
        })
    elif "behavioral" in segment:
        denial_pressure = safe_float(row.get("denial_pressure", 0))
        if denial_pressure >= 7.0:
            score += 7.0
            bibliography.append({
                "score": "compliance_risk",
                "sources": ["segment_label", "denial_pressure"],
                "value": f"{segment}, denial_pressure={denial_pressure}",
                "reason": "Behavioral Health with high denial pressure"
            })
        else:
            score += 4.0
            bibliography.append({
                "score": "compliance_risk",
                "sources": ["segment_label"],
                "value": segment,
                "reason": "Behavioral Health (moderate compliance focus)"
            })
    
    # FQHC flag
    fqhc_flag = safe_int(row.get("fqhc_flag", 0))
    if fqhc_flag >= 1 and score < 5.0:
        score += 5.0
        bibliography.append({
            "score": "compliance_risk",
            "sources": ["fqhc_flag"],
            "value": "TRUE",
            "reason": "FQHC designation (compliance reporting requirements)"
        })
    
    # ACO participation
    aco_member = safe_int(row.get("aco_member", 0))
    if aco_member >= 1 and score < 4.0:
        score += 4.0
        bibliography.append({
            "score": "compliance_risk",
            "sources": ["aco_member"],
            "value": "TRUE",
            "reason": "ACO participation (quality metric reporting)"
        })
    
    if score == 0.0:
        score = 2.0  # Default baseline risk
        bibliography.append({
            "score": "compliance_risk",
            "sources": ["default"],
            "value": "baseline",
            "reason": "Standard healthcare compliance requirements"
        })
    
    return min(10.0, round(score, 2)), bibliography


# ============================================================================
# CATEGORY 4: PROPENSITY TO BUY SCORE (0-10)
# ============================================================================

def compute_propensity_score(row: Dict[str, Any], stats: Dict[str, Any]) -> Tuple[float, List[Dict[str, str]]]:
    """
    Compute Propensity to Buy Score (0-10) based on payer mix, billing complexity, and RCM indicators.
    
    Sources:
    - roi_readiness (from existing enrichment)
    - pecos_enrolled (PECOS enrollment = structured billing)
    - aco_member (ACO = technology adoption)
    - coding_complexity (complexity = need for automation)
    - scale_velocity (growth = investment appetite)
    
    Logic:
    - High ROI readiness: 4 points
    - PECOS enrollment: 2 points
    - ACO membership: 2 points
    - High coding complexity: 2 points
    
    Returns:
        Tuple of (score, bibliography)
    """
    bibliography = []
    score = 0.0
    
    # ROI readiness (0-4 points)
    roi_readiness = safe_float(row.get("roi_readiness", 0))
    
    if roi_readiness >= 7.0:
        score += 4.0
        bibliography.append({
            "score": "propensity_to_buy",
            "sources": ["roi_readiness"],
            "value": roi_readiness,
            "reason": "High ROI readiness (technology investment signals)"
        })
    elif roi_readiness >= 4.0:
        score += 2.0
        bibliography.append({
            "score": "propensity_to_buy",
            "sources": ["roi_readiness"],
            "value": roi_readiness,
            "reason": "Moderate ROI readiness"
        })
    elif roi_readiness > 0:
        score += 1.0
        bibliography.append({
            "score": "propensity_to_buy",
            "sources": ["roi_readiness"],
            "value": roi_readiness,
            "reason": "Some ROI readiness signals"
        })
    
    # PECOS enrollment (2 points)
    pecos_enrolled = safe_int(row.get("pecos_enrolled", 0))
    if pecos_enrolled >= 1:
        score += 2.0
        bibliography.append({
            "score": "propensity_to_buy",
            "sources": ["pecos_enrolled"],
            "value": "TRUE",
            "reason": "PECOS enrollment (structured billing operations)"
        })
    
    # ACO membership (2 points)
    aco_member = safe_int(row.get("aco_member", 0))
    if aco_member >= 1:
        score += 2.0
        bibliography.append({
            "score": "propensity_to_buy",
            "sources": ["aco_member"],
            "value": "TRUE",
            "reason": "ACO participation (value-based care adoption)"
        })
    
    # Coding complexity as buying indicator (2 points)
    coding_complexity = safe_float(row.get("coding_complexity", 0))
    if coding_complexity >= 8.0:
        score += 2.0
        bibliography.append({
            "score": "propensity_to_buy",
            "sources": ["coding_complexity"],
            "value": coding_complexity,
            "reason": "High billing complexity (need for automation)"
        })
    
    if not bibliography:
        bibliography.append({
            "score": "propensity_to_buy",
            "sources": ["none"],
            "status": "MISSING",
            "note": "No propensity indicators available"
        })
    
    return min(10.0, round(score, 2)), bibliography


# ============================================================================
# CATEGORY 5: OPERATIONAL SCALE SCORE (0-20)
# ============================================================================

def compute_scale_score(row: Dict[str, Any], stats: Dict[str, Any]) -> Tuple[float, List[Dict[str, str]]]:
    """
    Compute Operational Scale Score (0-20) based on provider count, patient volume, and billing size.
    
    Sources:
    - npi_count (number of providers)
    - site_count (number of locations)
    - bene_count (patient volume)
    - allowed_amt (total billing size)
    - services_count (service breadth)
    
    Logic:
    - Use min-max normalization across dataset
    - Provider count: 0-8 points
    - Site count: 0-4 points
    - Patient volume: 0-4 points
    - Billing size: 0-4 points
    
    Returns:
        Tuple of (score, bibliography)
    """
    bibliography = []
    score = 0.0
    
    # Provider count (0-8 points) - log scale
    npi_count = safe_float(row.get("npi_count", 0))
    if npi_count > 0:
        # Log scale: 1-5 providers = 1-3 pts, 5-20 = 3-5 pts, 20-100 = 5-7 pts, 100+ = 7-8 pts
        if npi_count >= 100:
            provider_points = 8.0
            reason = "Large provider network (100+ providers)"
        elif npi_count >= 50:
            provider_points = 7.0
            reason = "Mid-size provider network (50-99 providers)"
        elif npi_count >= 20:
            provider_points = 5.5
            reason = "Growing provider network (20-49 providers)"
        elif npi_count >= 10:
            provider_points = 4.0
            reason = "Small-medium provider group (10-19 providers)"
        elif npi_count >= 5:
            provider_points = 2.5
            reason = "Small provider group (5-9 providers)"
        else:
            provider_points = 1.0
            reason = "Very small practice (1-4 providers)"
        
        score += provider_points
        bibliography.append({
            "score": "scale",
            "sources": ["npi_count"],
            "value": npi_count,
            "reason": reason
        })
    else:
        bibliography.append({
            "score": "scale",
            "sources": ["npi_count"],
            "status": "MISSING",
            "note": "No provider count data"
        })
    
    # Site count (0-4 points)
    site_count = safe_float(row.get("site_count", 0))
    if site_count > 0:
        if site_count >= 10:
            site_points = 4.0
            reason = "Multi-site organization (10+ locations)"
        elif site_count >= 5:
            site_points = 3.0
            reason = "Multi-site organization (5-9 locations)"
        elif site_count >= 3:
            site_points = 2.0
            reason = "Multi-site (3-4 locations)"
        else:
            site_points = 1.0
            reason = "Single or dual-site"
        
        score += site_points
        bibliography.append({
            "score": "scale",
            "sources": ["site_count"],
            "value": site_count,
            "reason": reason
        })
    
    # Patient volume (0-4 points)
    bene_count = safe_float(row.get("bene_count", 0))
    if bene_count > 0:
        if bene_count >= 10000:
            volume_points = 4.0
            reason = "Very high patient volume (10,000+ patients)"
        elif bene_count >= 5000:
            volume_points = 3.5
            reason = "High patient volume (5,000-9,999 patients)"
        elif bene_count >= 1000:
            volume_points = 2.5
            reason = "Moderate patient volume (1,000-4,999 patients)"
        elif bene_count >= 500:
            volume_points = 1.5
            reason = "Small patient volume (500-999 patients)"
        else:
            volume_points = 0.5
            reason = "Low patient volume (<500 patients)"
        
        score += volume_points
        bibliography.append({
            "score": "scale",
            "sources": ["bene_count"],
            "value": bene_count,
            "reason": reason
        })
    
    # Billing size (0-4 points)
    allowed_amt = safe_float(row.get("allowed_amt", 0))
    if allowed_amt > 0:
        if allowed_amt >= 10_000_000:
            billing_points = 4.0
            reason = "Enterprise billing volume ($10M+)"
        elif allowed_amt >= 5_000_000:
            billing_points = 3.5
            reason = "Large billing volume ($5M-$10M)"
        elif allowed_amt >= 1_000_000:
            billing_points = 2.5
            reason = "Mid-size billing volume ($1M-$5M)"
        elif allowed_amt >= 500_000:
            billing_points = 1.5
            reason = "Small billing volume ($500K-$1M)"
        else:
            billing_points = 0.5
            reason = "Low billing volume (<$500K)"
        
        score += billing_points
        bibliography.append({
            "score": "scale",
            "sources": ["allowed_amt"],
            "value": f"${allowed_amt:,.0f}",
            "reason": reason
        })
    
    if score == 0.0:
        bibliography.append({
            "score": "scale",
            "sources": ["none"],
            "status": "MISSING",
            "note": "No scale indicators available"
        })
    
    return min(20.0, round(score, 2)), bibliography


# ============================================================================
# CATEGORY 6: STRATEGIC SEGMENT SCORE (0-20)
# ============================================================================

def compute_strategic_segment_score(row: Dict[str, Any], stats: Dict[str, Any]) -> Tuple[float, List[Dict[str, str]], str]:
    """
    Compute Strategic Segment Score (0-20) and assign Segment (A, B, or C).
    
    Segment Definitions:
    - A: Behavioral Health / Home Health / Hospice
    - B: FQHC / Rural Health Clinic / HRSA grantee
    - C: Multi-specialty / 100+ providers / PE-backed
    
    Scoring:
    - Perfect segment match: 20 points
    - Strong segment indicators: 15-18 points
    - Moderate match: 10-14 points
    - Weak match: 5-9 points
    
    Returns:
        Tuple of (score, bibliography, segment_letter)
    """
    bibliography = []
    score = 0.0
    segment_letter = "C"  # Default to C
    
    segment = normalize_text(row.get("segment_label", ""))
    sector = normalize_text(row.get("sector", ""))
    npi_count = safe_float(row.get("npi_count", 0))
    fqhc_flag = safe_int(row.get("fqhc_flag", 0))
    
    # Check for Segment A (Behavioral / Home Health)
    if any(kw in segment for kw in SEGMENT_A_KEYWORDS):
        score = 20.0
        segment_letter = "A"
        bibliography.append({
            "score": "strategic_segment",
            "sources": ["segment_label"],
            "value": segment,
            "reason": "Perfect match for Segment A (Behavioral/Home Health)"
        })
        return 20.0, bibliography, segment_letter
    
    # Check for Segment B (FQHC / Rural / HRSA)
    if fqhc_flag >= 1 or any(kw in segment for kw in SEGMENT_B_KEYWORDS) or any(kw in sector for kw in SEGMENT_B_KEYWORDS):
        score = 20.0
        segment_letter = "B"
        bibliography.append({
            "score": "strategic_segment",
            "sources": ["segment_label", "sector", "fqhc_flag"],
            "value": f"{segment} / FQHC={fqhc_flag >= 1}",
            "reason": "Perfect match for Segment B (FQHC/Compliance-First)"
        })
        return 20.0, bibliography, segment_letter
    
    # Check for Segment C (Multi-Specialty / Growth)
    if any(kw in segment for kw in SEGMENT_C_KEYWORDS) or npi_count >= 100:
        score = 20.0
        segment_letter = "C"
        if npi_count >= 100:
            bibliography.append({
                "score": "strategic_segment",
                "sources": ["segment_label", "npi_count"],
                "value": f"{segment}, {npi_count} providers",
                "reason": "Perfect match for Segment C (Multi-Specialty/Growth, 100+ providers)"
            })
        else:
            bibliography.append({
                "score": "strategic_segment",
                "sources": ["segment_label"],
                "value": segment,
                "reason": "Perfect match for Segment C (Multi-Specialty/Growth)"
            })
        return 20.0, bibliography, segment_letter
    
    # Moderate matches
    if "primary care" in segment:
        score = 14.0
        segment_letter = "C"
        bibliography.append({
            "score": "strategic_segment",
            "sources": ["segment_label"],
            "value": segment,
            "reason": "Moderate match for Segment C (Primary Care)"
        })
    elif npi_count >= 50:
        score = 15.0
        segment_letter = "C"
        bibliography.append({
            "score": "strategic_segment",
            "sources": ["npi_count"],
            "value": npi_count,
            "reason": "Moderate match for Segment C (50-99 providers)"
        })
    elif npi_count >= 20:
        score = 12.0
        segment_letter = "C"
        bibliography.append({
            "score": "strategic_segment",
            "sources": ["npi_count"],
            "value": npi_count,
            "reason": "Weak match for Segment C (20-49 providers)"
        })
    else:
        score = 8.0
        segment_letter = "C"
        bibliography.append({
            "score": "strategic_segment",
            "sources": ["segment_label", "npi_count"],
            "value": f"{segment}, {npi_count} providers",
            "reason": "Generic segment assignment (default to C)"
        })
    
    return min(20.0, round(score, 2)), bibliography, segment_letter


# ============================================================================
# TIER ASSIGNMENT
# ============================================================================

def assign_tier(icp_score: float) -> Tuple[int, str]:
    """
    Assign tier based on total ICP score.
    
    UPDATED THRESHOLDS (Nov 2025):
    - Tier 1 (HOT): ICP >= 70 (reduced from 80 to reduce score compression)
    - Tier 2 (Qualified): 50 <= ICP < 70 (adjusted accordingly)
    - Tier 3 (Monitor): ICP < 50
    
    Returns:
        Tuple of (tier_number, tier_label)
    """
    if icp_score >= 70:
        return 1, "Tier 1 - HOT"
    elif icp_score >= 50:
        return 2, "Tier 2 - Qualified"
    else:
        return 3, "Tier 3 - Monitor"


# ============================================================================
# MAIN SCORING FUNCTION
# ============================================================================

def compute_icp_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute ICP scores for all clinics in the dataframe.
    
    Args:
        df: DataFrame with clinic data
    
    Returns:
        DataFrame with added ICP scoring columns
    """
    # Compute dataset statistics for normalization (if needed)
    stats = {
        "npi_count_max": df["npi_count"].max() if "npi_count" in df.columns else 1,
        "site_count_max": df["site_count"].max() if "site_count" in df.columns else 1,
        "bene_count_max": df["bene_count"].max() if "bene_count" in df.columns else 1,
        "allowed_amt_max": df["allowed_amt"].max() if "allowed_amt" in df.columns else 1,
    }
    
    records = []
    for _, row in df.iterrows():
        base = row.to_dict()
        
        # Compute all 6 category scores
        fit_score, fit_bib = compute_fit_score(base, stats)
        pain_score, pain_bib = compute_pain_score(base, stats)
        compliance_score, compliance_bib = compute_compliance_score(base, stats)
        propensity_score, propensity_bib = compute_propensity_score(base, stats)
        scale_score, scale_bib = compute_scale_score(base, stats)
        segment_score, segment_bib, segment_letter = compute_strategic_segment_score(base, stats)
        
        # Total ICP score
        total_icp = fit_score + pain_score + compliance_score + propensity_score + scale_score + segment_score
        
        # Tier assignment
        tier_num, tier_label = assign_tier(total_icp)
        
        # Combine bibliography
        all_bibliography = (
            fit_bib + pain_bib + compliance_bib + 
            propensity_bib + scale_bib + segment_bib
        )
        
        # Create updated record
        updated = {
            **base,
            "icp_fit_score": fit_score,
            "icp_pain_score": pain_score,
            "icp_compliance_score": compliance_score,
            "icp_propensity_score": propensity_score,
            "icp_scale_score": scale_score,
            "icp_segment_score": segment_score,
            "icp_total_score": round(total_icp, 2),
            "icp_tier": tier_num,
            "icp_tier_label": tier_label,
            "icp_segment": segment_letter,
            "icp_bibliography": str(all_bibliography),  # Convert to string for CSV storage
        }
        
        records.append(updated)
    
    # Create scored dataframe
    scored_df = pd.DataFrame(records)
    
    return scored_df


def enrich_icp_flags(df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich FQHC and ACO member flags using external datasets.
    
    This function loads raw FQHC and ACO data and enriches the clinic
    dataframe with proper flags at the NPI level, then aggregates to clinic level.
    
    Args:
        df: DataFrame with clinic data (must have clinic_id)
    
    Returns:
        DataFrame with enriched fqhc_flag and aco_member columns
    """
    print("\n[ENRICHMENT] Enriching FQHC and ACO flags...")
    
    # Paths to data sources
    hrsa_fqhc_path = os.path.join(ROOT, "data", "raw", "hrsa", "Health_Center_Service_Delivery_and_LookAlike_Sites (1).csv")
    aco_staging_path = os.path.join(ROOT, "data", "curated", "staging", "stg_aco_orgs.csv")
    npi_staging_path = os.path.join(ROOT, "data", "curated", "staging", "stg_npi_orgs.csv")
    
    # Track original values
    original_fqhc = df['fqhc_flag'].sum() if 'fqhc_flag' in df.columns else 0
    original_aco = df['aco_member'].sum() if 'aco_member' in df.columns else 0
    
    try:
        # Load NPI-to-clinic mapping
        if not os.path.exists(npi_staging_path):
            print(f"  ⚠️  NPI staging file not found: {npi_staging_path}")
            print(f"  → Keeping existing flags (FQHC: {original_fqhc}, ACO: {original_aco})")
            return df
        
        npi_orgs = pd.read_csv(npi_staging_path, low_memory=False)
        
        # Normalize clinic identifiers
        npi_orgs['org_norm'] = npi_orgs['org_name'].str.strip().str.upper()
        npi_orgs['state_norm'] = npi_orgs['state'].str.strip().str.upper()
        npi_orgs['clinic_key'] = npi_orgs['org_norm'] + '-' + npi_orgs['state_norm']
        
        # Create clinic_key in main df for matching
        if 'account_name' in df.columns and 'state_code' in df.columns:
            df['clinic_key_temp'] = df['account_name'].str.strip().str.upper() + '-' + df['state_code'].str.strip().str.upper()
        else:
            print(f"  ⚠️  Missing account_name or state_code columns")
            return df
        
        # Initialize enrichment dictionaries
        clinic_fqhc = {}
        clinic_aco = {}
        
        # =========================================================================
        # ENRICH FQHC FLAGS
        # =========================================================================
        if os.path.exists(hrsa_fqhc_path):
            print(f"  Loading FQHC data from: {os.path.basename(hrsa_fqhc_path)}")
            
            # Load HRSA FQHC data
            hrsa = pd.read_csv(hrsa_fqhc_path, low_memory=False)
            
            # Extract NPIs (handle potential NaN values)
            fqhc_npis = set()
            npi_col = 'npi' if 'npi' in hrsa.columns else 'FQHC Site NPI Number'
            
            if npi_col in hrsa.columns:
                # Filter out empty/invalid NPIs
                valid_npis = hrsa[npi_col].dropna()
                valid_npis = valid_npis[valid_npis != '']
                valid_npis = valid_npis[valid_npis != 'nan']
                
                # Convert to string NPIs
                for npi in valid_npis:
                    try:
                        # Try to convert to int first (removes decimals), then to string
                        npi_str = str(int(float(npi)))
                        if len(npi_str) == 10:  # Valid NPI is 10 digits
                            fqhc_npis.add(npi_str)
                    except (ValueError, TypeError):
                        continue
            
            print(f"    • Found {len(fqhc_npis):,} unique FQHC NPIs")
            
            # Match NPIs to clinics
            if len(fqhc_npis) > 0:
                npi_orgs['npi_str'] = npi_orgs['npi'].astype(str)
                npi_orgs['is_fqhc'] = npi_orgs['npi_str'].isin(fqhc_npis).astype(int)
                
                # Aggregate to clinic level (clinic has FQHC flag if any of its NPIs match)
                fqhc_by_clinic = npi_orgs.groupby('clinic_key')['is_fqhc'].max().to_dict()
                clinic_fqhc = fqhc_by_clinic
                
                fqhc_match_count = sum(1 for v in clinic_fqhc.values() if v >= 1)
                print(f"    ✓ Enriched FQHC flags for {fqhc_match_count:,} clinics")
            else:
                print(f"    ⚠️  No valid FQHC NPIs found in dataset")
        else:
            print(f"  ⚠️  FQHC data file not found: {hrsa_fqhc_path}")
        
        # =========================================================================
        # ENRICH ACO MEMBER FLAGS
        # =========================================================================
        if os.path.exists(aco_staging_path):
            print(f"  Loading ACO data from: {os.path.basename(aco_staging_path)}")
            
            # Load ACO data
            aco_data = pd.read_csv(aco_staging_path, low_memory=False)
            
            # Normalize for matching
            if 'org_name' in aco_data.columns and 'state' in aco_data.columns:
                aco_data['org_norm'] = aco_data['org_name'].str.strip().str.upper()
                aco_data['state_norm'] = aco_data['state'].str.strip().str.upper()
                aco_data['clinic_key'] = aco_data['org_norm'] + '-' + aco_data['state_norm']
                
                # Get unique ACO clinic keys
                aco_clinic_keys = set(aco_data['clinic_key'].unique())
                
                print(f"    • Found {len(aco_clinic_keys):,} unique ACO organizations")
                
                # Match to our clinics
                for key in aco_clinic_keys:
                    if key in df['clinic_key_temp'].values:
                        clinic_aco[key] = 1
                
                aco_match_count = len(clinic_aco)
                print(f"    ✓ Enriched ACO member flags for {aco_match_count:,} clinics")
            else:
                print(f"    ⚠️  Missing required columns in ACO data")
        else:
            print(f"  ⚠️  ACO data file not found: {aco_staging_path}")
        
        # =========================================================================
        # APPLY ENRICHMENT TO DATAFRAME
        # =========================================================================
        
        # Apply FQHC flags
        if clinic_fqhc:
            df['fqhc_flag'] = df['clinic_key_temp'].map(clinic_fqhc).fillna(df.get('fqhc_flag', 0)).astype(int)
        
        # Apply ACO flags
        if clinic_aco:
            df['aco_member'] = df['clinic_key_temp'].map(clinic_aco).fillna(df.get('aco_member', 0)).astype(int)
        
        # Clean up temporary column
        df = df.drop(columns=['clinic_key_temp'], errors='ignore')
        
        # Summary
        final_fqhc = df['fqhc_flag'].sum() if 'fqhc_flag' in df.columns else 0
        final_aco = df['aco_member'].sum() if 'aco_member' in df.columns else 0
        
        print(f"\n  📊 Enrichment Summary:")
        print(f"    • FQHC flags: {original_fqhc:,} → {final_fqhc:,} (+{final_fqhc - original_fqhc:,})")
        print(f"    • ACO flags:  {original_aco:,} → {final_aco:,} (+{final_aco - original_aco:,})")
        
        return df
        
    except Exception as e:
        print(f"  ❌ Enrichment failed: {e}")
        print(f"  → Keeping existing flags")
        return df


def normalize_network_name(name: str) -> str:
    """
    Normalize organization name for network grouping.
    
    Args:
        name: Raw organization name
        
    Returns:
        Normalized name suitable for grouping
    """
    if pd.isna(name) or not isinstance(name, str):
        return ""
    
    # Convert to lowercase
    normalized = name.lower().strip()
    
    # Remove common suffixes and legal structures
    suffixes_to_remove = [
        r'\s+inc\.?$', r'\s+incorporated$', r'\s+llc\.?$', r'\s+l\.l\.c\.?$',
        r'\s+pllc\.?$', r'\s+p\.l\.l\.c\.?$', r'\s+corp\.?$', r'\s+corporation$',
        r'\s+ltd\.?$', r'\s+limited$', r'\s+pa\.?$', r'\s+pc\.?$',
        r'\s+lp\.?$', r'\s+co\.?$', r'\s+company$'
    ]
    
    for suffix in suffixes_to_remove:
        normalized = re.sub(suffix, '', normalized)
    
    # Remove punctuation except spaces
    normalized = re.sub(r'[^\w\s]', '', normalized)
    
    # Collapse multiple spaces
    normalized = re.sub(r'\s+', ' ', normalized)
    
    # Remove leading/trailing whitespace
    normalized = normalized.strip()
    
    return normalized


def create_network_id(name: str) -> str:
    """
    Create a stable network ID from normalized name.
    
    Args:
        name: Normalized network name
        
    Returns:
        Hash-based network ID
    """
    if not name:
        return ""
    
    # Create a short hash of the name
    hash_obj = hashlib.md5(name.encode('utf-8'))
    return f"net_{hash_obj.hexdigest()[:12]}"


def group_clinics_into_networks(df: pd.DataFrame) -> pd.DataFrame:
    """
    Group clinics into networks based on name similarity.
    
    Args:
        df: DataFrame with clinic-level ICP scores
        
    Returns:
        DataFrame with network_id and normalized_network_name columns added
    """
    print("\n" + "=" * 70)
    print("NETWORK GROUPING")
    print("=" * 70)
    
    # Ensure we have account_name
    if 'account_name' not in df.columns:
        print("  ⚠️  No account_name column found, skipping network grouping")
        df['network_id'] = None
        df['network_name'] = None
        df['normalized_network_name'] = None
        return df
    
    # Normalize names
    print(f"\n[1/3] Normalizing {len(df):,} clinic names...")
    df['normalized_network_name'] = df['account_name'].apply(normalize_network_name)
    
    # Filter out empty names
    valid_names = df['normalized_network_name'].notna() & (df['normalized_network_name'] != '')
    df_valid = df[valid_names].copy()
    df_invalid = df[~valid_names].copy()
    
    print(f"  ✓ Valid names: {len(df_valid):,}")
    print(f"  ⚠️  Invalid/missing names: {len(df_invalid):,}")
    
    # Group by normalized name
    print(f"\n[2/3] Grouping clinics by normalized name...")
    name_groups = df_valid.groupby('normalized_network_name')
    
    # Calculate group sizes
    group_sizes = name_groups.size()
    
    # Filter groups (precision over recall - avoid false positives)
    # Only consider networks with 2+ clinics
    network_names = group_sizes[group_sizes >= 2].index.tolist()
    
    print(f"  ✓ Found {len(network_names):,} potential networks")
    print(f"  ✓ Single-clinic organizations: {(group_sizes == 1).sum():,}")
    
    # Additional validation: check state diversity
    # Networks should typically operate in multiple locations
    # But we'll be lenient - allow same-state networks if they have multiple sites
    print(f"  → Validating networks (checking multi-state or 3+ clinics)...")
    
    # Use groupby for efficient validation (much faster than repeated filtering)
    validated_networks = []
    
    if 'state_code' in df_valid.columns:
        # Group by network name and aggregate stats
        network_stats = df_valid.groupby('normalized_network_name').agg({
            'state_code': 'nunique',
            'clinic_id': 'count'
        }).rename(columns={'state_code': 'num_states', 'clinic_id': 'num_clinics'})
        
        # Filter: multi-state OR 3+ clinics
        valid_mask = (network_stats['num_states'] > 1) | (network_stats['num_clinics'] >= 3)
        validated_networks = network_stats[valid_mask].index.tolist()
    else:
        # No state data, accept all multi-clinic groups
        validated_networks = network_names
    
    print(f"  ✓ Validated networks: {len(validated_networks):,}")
    
    # Assign network IDs
    print(f"\n[3/3] Assigning network IDs...")
    
    # Create network ID mapping
    network_id_map = {name: create_network_id(name) for name in validated_networks}
    
    # Assign to dataframe (FAST: vectorized approach, not loop)
    # Create a mapping series for validated networks only
    network_mapping = pd.Series(network_id_map)
    
    # Map network IDs - only for validated networks
    df['network_id'] = df['normalized_network_name'].map(network_id_map)
    df['network_name'] = df['normalized_network_name'].where(df['network_id'].notna())
    
    # Summary
    clinics_in_networks = df['network_id'].notna().sum()
    standalone_clinics = df['network_id'].isna().sum()
    
    print(f"  ✓ Clinics in networks: {clinics_in_networks:,} ({clinics_in_networks/len(df)*100:.1f}%)")
    print(f"  ✓ Standalone clinics: {standalone_clinics:,} ({standalone_clinics/len(df)*100:.1f}%)")
    
    # Show sample networks (use pre-computed stats for efficiency)
    if len(validated_networks) > 0 and 'state_code' in df_valid.columns:
        print(f"\n  Sample networks:")
        sample_stats = df_valid[df_valid['normalized_network_name'].isin(validated_networks[:5])].groupby('normalized_network_name').agg({
            'clinic_id': 'count',
            'state_code': 'nunique'
        }).rename(columns={'clinic_id': 'num_clinics', 'state_code': 'num_states'})
        
        for i, network_name in enumerate(validated_networks[:5]):
            if network_name in sample_stats.index:
                stats = sample_stats.loc[network_name]
                print(f"    {i+1}. {network_name.upper()} - {int(stats['num_clinics'])} clinics in {int(stats['num_states'])} states")
    
    return df


def calculate_network_icp_scores(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate network-level ICP scores from grouped clinics.
    
    Args:
        df: DataFrame with clinic-level ICP scores and network_id
        
    Returns:
        DataFrame with one row per network
    """
    print("\n" + "=" * 70)
    print("NETWORK-LEVEL ICP SCORING")
    print("=" * 70)
    
    # Filter to only clinics in networks
    network_clinics = df[df['network_id'].notna()].copy()
    
    if len(network_clinics) == 0:
        print("  ⚠️  No networks found, skipping network scoring")
        return pd.DataFrame()
    
    print(f"\n[1/2] Aggregating {len(network_clinics):,} clinics into networks...")
    
    # Define scoring columns
    score_cols = ['icp_fit_score', 'icp_pain_score', 'icp_compliance_score',
                  'icp_propensity_score', 'icp_scale_score', 'icp_segment_score']
    
    # Group by network
    networks = []
    
    for network_id, group in network_clinics.groupby('network_id'):
        network_name = group['network_name'].iloc[0]
        num_clinics = len(group)
        
        # States covered
        states_covered = sorted(group['state_code'].dropna().unique().tolist()) if 'state_code' in group.columns else []
        states_str = ','.join(states_covered)
        num_states = len(states_covered)
        
        # Calculate weighted average scores (weight by site_count if available)
        if 'site_count' in group.columns and group['site_count'].notna().sum() > 0:
            weights = group['site_count'].fillna(1)
        else:
            weights = pd.Series([1] * len(group), index=group.index)
        
        # Normalize weights
        weights = weights / weights.sum()
        
        # Aggregate category scores (weighted average)
        category_scores = {}
        for col in score_cols:
            if col in group.columns:
                # Weighted average
                valid_mask = group[col].notna()
                if valid_mask.any():
                    category_scores[col] = (group.loc[valid_mask, col] * weights[valid_mask]).sum() / weights[valid_mask].sum()
                else:
                    category_scores[col] = 0.0
            else:
                category_scores[col] = 0.0
        
        # Calculate network ICP total score
        network_icp_total = sum(category_scores.values())
        
        # Assign tier
        network_tier, network_tier_label = assign_tier(network_icp_total)
        
        # Determine dominant segment
        if 'icp_segment' in group.columns:
            segment_counts = group['icp_segment'].value_counts()
            network_segment = segment_counts.index[0] if len(segment_counts) > 0 else None
        else:
            network_segment = None
        
        # Additional aggregations
        total_npi_count = group['npi_count'].sum() if 'npi_count' in group.columns else 0
        total_site_count = group['site_count'].sum() if 'site_count' in group.columns else 0
        avg_clinic_icp = group['icp_total_score'].mean() if 'icp_total_score' in group.columns else 0
        fqhc_clinics = group['fqhc_flag'].sum() if 'fqhc_flag' in group.columns else 0
        aco_clinics = group['aco_member'].sum() if 'aco_member' in group.columns else 0
        
        # Find anchor clinic (highest ICP score)
        if 'icp_total_score' in group.columns:
            anchor_idx = group['icp_total_score'].idxmax()
            anchor_clinic_id = group.loc[anchor_idx, 'clinic_id']
        else:
            anchor_clinic_id = group['clinic_id'].iloc[0]
        
        networks.append({
            'network_id': network_id,
            'network_name': network_name,
            'num_clinics': num_clinics,
            'num_states': num_states,
            'states_covered': states_str,
            'network_icp_total_score': round(network_icp_total, 2),
            'network_icp_tier': network_tier,
            'network_icp_tier_label': network_tier_label,
            'network_icp_segment': network_segment,
            'network_icp_fit_score': round(category_scores['icp_fit_score'], 2),
            'network_icp_pain_score': round(category_scores['icp_pain_score'], 2),
            'network_icp_compliance_score': round(category_scores['icp_compliance_score'], 2),
            'network_icp_propensity_score': round(category_scores['icp_propensity_score'], 2),
            'network_icp_scale_score': round(category_scores['icp_scale_score'], 2),
            'network_icp_segment_score': round(category_scores['icp_segment_score'], 2),
            'total_npi_count': int(total_npi_count) if pd.notna(total_npi_count) else 0,
            'total_site_count': int(total_site_count) if pd.notna(total_site_count) else 0,
            'avg_clinic_icp_score': round(avg_clinic_icp, 2),
            'fqhc_clinics_count': int(fqhc_clinics) if pd.notna(fqhc_clinics) else 0,
            'aco_clinics_count': int(aco_clinics) if pd.notna(aco_clinics) else 0,
            'anchor_clinic_id': anchor_clinic_id,
        })
    
    networks_df = pd.DataFrame(networks)
    
    print(f"  ✓ Created {len(networks_df):,} network records")
    
    # Summary statistics
    print(f"\n[2/2] Network-level summary:")
    avg_clinics_per_network = networks_df['num_clinics'].mean()
    max_clinics = networks_df['num_clinics'].max()
    avg_network_icp = networks_df['network_icp_total_score'].mean()
    
    network_tier_1 = (networks_df['network_icp_tier'] == 1).sum()
    network_tier_2 = (networks_df['network_icp_tier'] == 2).sum()
    network_tier_3 = (networks_df['network_icp_tier'] == 3).sum()
    
    print(f"  • Avg clinics per network: {avg_clinics_per_network:.1f}")
    print(f"  • Largest network: {max_clinics} clinics")
    print(f"  • Avg network ICP score: {avg_network_icp:.1f}")
    print(f"  • Network Tier 1 (HOT): {network_tier_1:,}")
    print(f"  • Network Tier 2 (Qualified): {network_tier_2:,}")
    print(f"  • Network Tier 3 (Monitor): {network_tier_3:,}")
    
    return networks_df


def enrich_clinics_with_network_data(df: pd.DataFrame, networks_df: pd.DataFrame) -> pd.DataFrame:
    """
    Enrich clinic-level data with network information.
    
    Args:
        df: DataFrame with clinic-level ICP scores
        networks_df: DataFrame with network-level data
        
    Returns:
        DataFrame with network fields added to clinics
    """
    print("\n" + "=" * 70)
    print("ENRICHING CLINICS WITH NETWORK DATA")
    print("=" * 70)
    
    if networks_df.empty:
        print("  ⚠️  No networks to enrich, skipping")
        df['network_icp_score'] = None
        df['network_tier'] = None
        df['network_tier_label'] = None
        df['is_network_anchor'] = False
        return df
    
    # Merge network scores into clinic dataframe
    network_cols = [
        'network_id', 'network_icp_total_score', 'network_icp_tier',
        'network_icp_tier_label', 'anchor_clinic_id', 'num_clinics'
    ]
    
    merge_df = networks_df[network_cols].rename(columns={
        'network_icp_total_score': 'network_icp_score',
        'network_icp_tier': 'network_tier',
        'network_icp_tier_label': 'network_tier_label',
    })
    
    # Merge
    df = df.merge(merge_df, on='network_id', how='left')
    
    # Mark anchor clinics
    df['is_network_anchor'] = df.apply(
        lambda row: row['clinic_id'] == row['anchor_clinic_id'] if pd.notna(row.get('anchor_clinic_id')) else False,
        axis=1
    )
    
    # Clean up
    df = df.drop(columns=['anchor_clinic_id'], errors='ignore')
    
    # Summary
    clinics_with_network_score = df['network_icp_score'].notna().sum()
    anchor_clinics = df['is_network_anchor'].sum()
    
    print(f"  ✓ Enriched {clinics_with_network_score:,} clinics with network scores")
    print(f"  ✓ Identified {anchor_clinics:,} network anchor clinics")
    
    return df


def load_source_dataframe() -> pd.DataFrame:
    """Load the enriched clinic dataset."""
    if os.path.exists(CLINICS_SCORED):
        return pd.read_csv(CLINICS_SCORED, low_memory=False)
    else:
        print(f"Error: Source file not found: {CLINICS_SCORED}")
        return pd.DataFrame()


def main() -> None:
    """Main execution function."""
    print("=" * 70)
    print("ICP SCORING ENGINE (WITH NETWORK SCORING)")
    print("=" * 70)
    
    # Load source data
    print("\n[1/6] Loading clinic data...")
    df = load_source_dataframe()
    
    if df.empty:
        print("❌ No clinics to score. Run enrichment first.")
        return
    
    print(f"✓ Loaded {len(df):,} clinics")
    
    # Enrich FQHC and ACO flags
    print("\n[2/6] Enriching data flags...")
    df = enrich_icp_flags(df)
    
    # Compute ICP scores
    print("\n[3/6] Computing ICP scores...")
    print("  - Fit Score (0-20)")
    print("  - Pain Score (0-20)")
    print("  - Compliance Risk Score (0-10)")
    print("  - Propensity to Buy Score (0-10)")
    print("  - Operational Scale Score (0-20)")
    print("  - Strategic Segment Score (0-20)")
    
    scored = compute_icp_scores(df)
    
    # Summary statistics (clinic-level)
    tier_1_count = (scored["icp_tier"] == 1).sum()
    tier_2_count = (scored["icp_tier"] == 2).sum()
    tier_3_count = (scored["icp_tier"] == 3).sum()
    
    segment_a_count = (scored["icp_segment"] == "A").sum()
    segment_b_count = (scored["icp_segment"] == "B").sum()
    segment_c_count = (scored["icp_segment"] == "C").sum()
    
    avg_icp = scored["icp_total_score"].mean()
    max_icp = scored["icp_total_score"].max()
    min_icp = scored["icp_total_score"].min()
    
    print(f"\n✓ Clinic-level scoring complete!")
    print(f"\n  ICP Score Range: {min_icp:.1f} - {max_icp:.1f} (avg: {avg_icp:.1f})")
    print(f"\n  Tier Distribution:")
    print(f"    - Tier 1 (HOT): {tier_1_count:,} ({tier_1_count/len(scored)*100:.1f}%)")
    print(f"    - Tier 2 (Qualified): {tier_2_count:,} ({tier_2_count/len(scored)*100:.1f}%)")
    print(f"    - Tier 3 (Monitor): {tier_3_count:,} ({tier_3_count/len(scored)*100:.1f}%)")
    print(f"\n  Segment Distribution:")
    print(f"    - Segment A (Behavioral/Home Health): {segment_a_count:,} ({segment_a_count/len(scored)*100:.1f}%)")
    print(f"    - Segment B (FQHC/Compliance): {segment_b_count:,} ({segment_b_count/len(scored)*100:.1f}%)")
    print(f"    - Segment C (Multi-Specialty/Growth): {segment_c_count:,} ({segment_c_count/len(scored)*100:.1f}%)")
    
    # Network scoring
    print("\n[4/6] Grouping clinics into networks...")
    scored_with_networks = group_clinics_into_networks(scored)
    
    print("\n[5/6] Calculating network-level ICP scores...")
    networks_df = calculate_network_icp_scores(scored_with_networks)
    
    print("\n[6/6] Enriching clinic data with network information...")
    final_df = enrich_clinics_with_network_data(scored_with_networks, networks_df)
    
    # Save results
    print("\n" + "=" * 70)
    print("SAVING RESULTS")
    print("=" * 70)
    
    # Save full scored dataset (original format)
    final_df.to_csv(CLINICS_ICP, index=False)
    print(f"\n✓ Full dataset: {CLINICS_ICP} ({len(final_df):,} rows)")
    
    # Save scores-only file (original format)
    icp_columns = [
        "clinic_id",
        "account_name",
        "state_code",
        "segment_label",
        "icp_total_score",
        "icp_tier",
        "icp_tier_label",
        "icp_segment",
        "icp_fit_score",
        "icp_pain_score",
        "icp_compliance_score",
        "icp_propensity_score",
        "icp_scale_score",
        "icp_segment_score",
        "npi_count",
        "site_count",
        "fqhc_flag",
        "aco_member",
        "icp_bibliography",
    ]
    available_icp_columns = [col for col in icp_columns if col in final_df.columns]
    final_df[available_icp_columns].to_csv(ICP_SCORES, index=False)
    print(f"✓ Scores summary: {ICP_SCORES} ({len(final_df):,} rows)")
    
    # Save network-level scores
    if not networks_df.empty:
        networks_df.to_csv(NETWORKS_ICP, index=False)
        print(f"✓ Network scores: {NETWORKS_ICP} ({len(networks_df):,} networks)")
    
    # Save clinics with network enrichment
    clinic_network_columns = [
        "clinic_id",
        "account_name",
        "state_code",
        "segment_label",
        "icp_total_score",
        "icp_tier",
        "icp_tier_label",
        "icp_segment",
        "icp_fit_score",
        "icp_pain_score",
        "icp_compliance_score",
        "icp_propensity_score",
        "icp_scale_score",
        "icp_segment_score",
        "network_id",
        "network_name",
        "network_icp_score",
        "network_tier",
        "network_tier_label",
        "is_network_anchor",
        "num_clinics",
        "npi_count",
        "site_count",
        "fqhc_flag",
        "aco_member",
    ]
    available_network_columns = [col for col in clinic_network_columns if col in final_df.columns]
    final_df[available_network_columns].to_csv(CLINICS_ICP_WITH_NETWORKS, index=False)
    print(f"✓ Clinics with networks: {CLINICS_ICP_WITH_NETWORKS} ({len(final_df):,} rows)")
    
    # Show sample of top scorers (clinic-level)
    print("\n" + "=" * 70)
    print("TOP 10 CLINICS BY ICP SCORE")
    print("=" * 70)
    top_10_clinics = final_df.nlargest(10, "icp_total_score")[
        ["clinic_id", "account_name", "state_code", "icp_total_score", "icp_tier_label", "icp_segment", "network_name"]
    ].copy()
    top_10_clinics['network_name'] = top_10_clinics['network_name'].fillna('(standalone)')
    print(top_10_clinics.to_string(index=False))
    
    # Show sample of top networks
    if not networks_df.empty:
        print("\n" + "=" * 70)
        print("TOP 10 NETWORKS BY ICP SCORE")
        print("=" * 70)
        top_10_networks = networks_df.nlargest(10, "network_icp_total_score")[
            ["network_id", "network_name", "num_clinics", "num_states", "network_icp_total_score", "network_icp_tier_label", "network_icp_segment"]
        ]
        print(top_10_networks.to_string(index=False))
    
    print("\n" + "=" * 70)
    print("✅ ICP SCORING COMPLETE (INCLUDING NETWORKS)")
    print("=" * 70)


if __name__ == "__main__":
    main()

    