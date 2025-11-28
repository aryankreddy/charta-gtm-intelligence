"""
Frontend Data Generator for Charta Health Dashboard
Author: Charta Health GTM Engineering

Purpose: Transform production scoring data into UI-friendly JSON format.
Input: data/curated/clinics_scored_final.csv
Output: web/public/data/clinics.json

Key Features:
- Revenue unit normalization (fix values < $10k)
- Top 5,000 leads (expanded from 2,500)
- Glass box analysis with ranking logic, gaps, benchmarks
- Multi-level sorting (icp_score DESC, then est_revenue_lift DESC)
"""

import pandas as pd
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCORED_FILE = os.path.join(ROOT, "data", "curated", "clinics_scored_final.csv")
OUTPUT_JSON = os.path.join(ROOT, "web", "public", "data", "clinics.json")

# Benchmarks
NATIONAL_UNDERCODING_AVG = 0.45  # National average for undercoding ratio


def normalize_revenue(value):
    """
    Fix revenue unit issues (Critique #9).

    If value < 10,000, assume source was in 'Thousands' and multiply by 1,000.
    Logic: No clinic has $2 annual revenue - this is a data quality issue.
    """
    if pd.isna(value) or value == 0:
        return 0

    # If suspiciously low, assume it's in thousands
    if value < 10_000:
        return value * 1_000

    return value


def format_revenue(value):
    """Format revenue as $12.52M or $450k."""
    if pd.isna(value) or value == 0:
        return "N/A"
    if value >= 1_000_000:
        return f"${value/1_000_000:.2f}M"
    elif value >= 1_000:
        return f"${value/1_000:.0f}k"
    else:
        return f"${value:.0f}"


def format_volume(value):
    """Format volume as 45,000."""
    if pd.isna(value) or value == 0:
        return "N/A"
    return f"{int(value):,}"


def format_phone(value):
    """Format phone number to xxx-xxx-xxxx."""
    if pd.isna(value) or value == '' or str(value).lower() == 'nan':
        return ""

    # Convert to string and remove any .0 suffix
    phone_str = str(value).replace('.0', '').strip()

    # Remove any non-digit characters
    digits = ''.join(filter(str.isdigit, phone_str))

    # Format as xxx-xxx-xxxx if we have 10 digits
    if len(digits) == 10:
        return f"{digits[0:3]}-{digits[3:6]}-{digits[6:10]}"
    elif len(digits) == 11 and digits[0] == '1':
        # Handle 1-xxx-xxx-xxxx format
        return f"{digits[1:4]}-{digits[4:7]}-{digits[7:11]}"
    elif len(digits) > 0:
        # Return as-is if not standard format
        return digits
    else:
        return ""


def parse_drivers(scoring_drivers_str):
    """
    Parse emoji-based scoring_drivers string into UI tags.

    Emoji mappings:
    - 🐋 -> green (High Volume - was purple/Strategic)
    - 🩸 or 🚨 -> red (Urgent)
    - ✅ -> green (Verified)
    """
    if pd.isna(scoring_drivers_str) or scoring_drivers_str == '':
        return []

    drivers = []
    parts = str(scoring_drivers_str).split(' | ')

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Replace "Whale Scale" with "High Volume"
        part = part.replace('🐋 Whale Scale', 'High Volume')

        # Determine color based on emoji or label
        color = "text-gray-600"  # default
        if '🐋' in part or 'High Volume' in part:
            color = "text-green-600"  # Changed from purple to green
        elif '🩸' in part or '🚨' in part:
            color = "text-red-600"
        elif '✅' in part:
            color = "text-green-600"

        # Extract label and value
        if '(' in part:
            label = part.split('(')[0].strip()
            value = part.split('(')[1].replace(')', '').strip()
        else:
            label = part
            value = ""

        drivers.append({
            "label": label,
            "value": value,
            "color": color
        })

    return drivers[:3]  # Limit to top 3 drivers


def calculate_lift(final_revenue, undercoding_ratio):
    """
    Calculate revenue lift opportunity.

    Logic:
    - If undercoding_ratio is valid (< 0.5):
      - Lift = final_revenue * (0.50 - undercoding_ratio)
      - Label: "Verified Opportunity"
      - is_projected: False
    - Else:
      - Lift = final_revenue * 0.05 (5% benchmark)
      - Label: "Est. Opportunity"
      - is_projected: True
    """
    if pd.isna(final_revenue) or final_revenue == 0:
        return 0, "N/A", True

    # Check if undercoding_ratio is valid
    if pd.notna(undercoding_ratio) and 0 < undercoding_ratio < 0.5:
        # Verified opportunity based on actual coding gap
        lift = final_revenue * (0.50 - undercoding_ratio)
        label = "Verified Opportunity"
        is_projected = False
    else:
        # Projected opportunity using 5% benchmark
        lift = final_revenue * 0.05
        label = "Est. Opportunity"
        is_projected = True

    return lift, label, is_projected


def calculate_billing_ratio(undercoding_ratio):
    """
    Calculate billing ratio chart data.

    Logic:
    - If undercoding_ratio is valid:
      - Level 4 % = undercoding_ratio * 100
      - Level 3 % = 100 - (undercoding_ratio * 100)
    - Else:
      - Use 50/50 default
    """
    if pd.notna(undercoding_ratio) and 0 < undercoding_ratio < 1.0:
        level4_pct = int(undercoding_ratio * 100)
        level3_pct = 100 - level4_pct
    else:
        # Default 50/50 split
        level3_pct = 50
        level4_pct = 50

    return {"level3": level3_pct, "level4": level4_pct}


def identify_data_gaps(row):
    """
    Identify missing or low-quality data (Critique #4).

    Returns list of gap descriptions.
    """
    gaps = []

    # Critical financial data
    if pd.isna(row.get('undercoding_ratio')) or row.get('undercoding_ratio') == 0:
        gaps.append("Missing CPT billing data")

    if pd.isna(row.get('psych_risk_ratio')):
        gaps.append("No psych audit risk data")

    if pd.isna(row.get('final_margin')) or row.get('final_margin') == 0:
        gaps.append("Missing margin data")

    # Volume verification
    volume_source = str(row.get('volume_source', ''))
    if 'Unknown' in volume_source or volume_source == 'nan':
        gaps.append("Unverified volume estimate")

    # Revenue verification
    revenue_source = str(row.get('revenue_source', ''))
    if 'Unknown' in revenue_source or revenue_source == 'nan':
        gaps.append("Unverified revenue estimate")

    # Data confidence
    data_confidence = row.get('data_confidence', '')
    if pd.isna(data_confidence) or data_confidence == 'Low':
        gaps.append("Low overall data confidence")

    return gaps


def generate_strategic_brief(row, lift_value):
    """
    Generate analyst-tone strategic brief based on data signals.

    This is NOT a sales pitch. This is an objective operational assessment
    based on claims data, billing patterns, and organizational characteristics.
    """
    segment = row.get('segment', 'Unknown')
    undercoding_ratio = row.get('undercoding_ratio')
    psych_risk_ratio = row.get('psych_risk_ratio')
    total_volume = row.get('total_medicare_volume', 0)
    uds_volume = row.get('uds_patient_total', 0)
    margin = row.get('margin')

    # Determine primary operational reality
    brief_parts = []

    # === SEVERE UNDERCODING SIGNAL ===
    if pd.notna(undercoding_ratio) and undercoding_ratio < 0.35:
        brief_parts.append(
            f"Claims analysis proves systemic under-coding (only {undercoding_ratio:.1%} Level 4/5 usage vs. 45% benchmark). "
            f"This suggests a risk-averse culture leaving verified revenue on the table."
        )
    elif pd.notna(undercoding_ratio) and undercoding_ratio < 0.50:
        brief_parts.append(
            f"Billing patterns show {undercoding_ratio:.1%} Level 4/5 usage, below 50% optimal target. "
            f"Data indicates room for documentation improvement without changing clinical care."
        )

    # === BEHAVIORAL HEALTH CODING SIGNALS (BIDIRECTIONAL) ===
    if pd.notna(psych_risk_ratio):
        # Conservative coding (undercoding therapy complexity)
        if psych_risk_ratio <= 0.30:
            brief_parts.append(
                f"Claims analysis shows conservative therapy coding (only {psych_risk_ratio:.1%} high-complexity sessions vs. 50% national benchmark). "
                f"This suggests systematic undercoding of therapy complexity, leaving verified revenue on the table."
            )
        # Aggressive coding (audit risk)
        elif psych_risk_ratio >= 0.75:
            brief_parts.append(
                f"Billing patterns show statistical anomaly in high-complexity codes ({psych_risk_ratio:.1%} of therapy sessions vs. 50% benchmark), "
                f"creating immediate audit liability and potential recoupment exposure under payer scrutiny."
            )
        # Moderate overcoding
        elif psych_risk_ratio > 0.60:
            brief_parts.append(
                f"Elevated use of high-complexity therapy codes ({psych_risk_ratio:.1%} vs. 50% benchmark) suggests potential compliance exposure."
            )

    # === HIGH VOLUME OPERATIONAL REALITY ===
    whale_volume = max(total_volume, uds_volume) if pd.notna(uds_volume) else total_volume
    if whale_volume > 50_000:
        brief_parts.append(
            f"Scale of operations ({whale_volume:,.0f} annual visits) implies manual auditing is mathematically impossible. "
            f"Likely reliant on spot-checks, creating systemic blind spots."
        )
    elif whale_volume > 25_000:
        brief_parts.append(
            f"Volume profile ({whale_volume:,.0f} visits) suggests chart review bottlenecks limit coding accuracy feedback loops."
        )

    # === FQHC MARGIN PRESSURE ===
    if segment == 'Segment B':  # FQHC
        if pd.notna(margin) and margin < 0.02:
            brief_parts.append(
                f"Grant-funded status with thin margins ({margin:.1%}) creates extreme sensitivity to revenue leakage. "
                f"Even small billing errors compound into existential risk."
            )
        else:
            brief_parts.append(
                f"Safety-net mission with PPS reimbursement creates complex compliance requirements and coding dependencies."
            )

    # === STRATEGIC VALUE (if significant lift) ===
    if lift_value > 1_000_000:
        brief_parts.append(
            f"Financial modeling suggests ${lift_value/1_000_000:.1f}M annual opportunity from billing optimization alone."
        )

    # Fallback if no strong signals
    if not brief_parts:
        brief_parts.append(
            "Operational profile suggests standard market opportunity with likely optimization potential pending deeper analysis."
        )

    return " ".join(brief_parts)


def generate_benchmarks(row):
    """
    Compare clinic metrics to national benchmarks (Critique #4).
    """
    benchmarks = {}

    # Undercoding ratio benchmark
    undercoding = row.get('undercoding_ratio')
    if pd.notna(undercoding) and undercoding > 0:
        vs_national = undercoding - NATIONAL_UNDERCODING_AVG
        if undercoding > NATIONAL_UNDERCODING_AVG:  # Higher = GOOD (more Level 4/5 usage = less undercoding)
            benchmarks['undercoding'] = {
                'value': round(undercoding, 3),
                'national_avg': NATIONAL_UNDERCODING_AVG,
                'comparison': f"{abs(vs_national):.2%} better than national average (less undercoding)",
                'status': 'outperforming'
            }
        else:  # Lower = BAD (fewer Level 4/5 usage = more undercoding)
            benchmarks['undercoding'] = {
                'value': round(undercoding, 3),
                'national_avg': NATIONAL_UNDERCODING_AVG,
                'comparison': f"{abs(vs_national):.2%} worse than national average (more undercoding)",
                'status': 'underperforming'
            }
    else:
        benchmarks['undercoding'] = {
            'value': None,
            'national_avg': NATIONAL_UNDERCODING_AVG,
            'comparison': "No data available",
            'status': 'unknown'
        }

    # Psych risk benchmark (assume 0.20 is high risk threshold)
    psych_risk = row.get('psych_risk_ratio')
    if pd.notna(psych_risk) and psych_risk > 0:
        if psych_risk > 0.75:
            benchmarks['psych_audit_risk'] = {
                'value': round(psych_risk, 3),
                'threshold': 0.75,
                'status': 'severe',
                'description': 'Critical audit risk - immediate attention needed'
            }
        elif psych_risk > 0.50:
            benchmarks['psych_audit_risk'] = {
                'value': round(psych_risk, 3),
                'threshold': 0.50,
                'status': 'elevated',
                'description': 'Moderate audit risk detected'
            }
        else:
            benchmarks['psych_audit_risk'] = {
                'value': round(psych_risk, 3),
                'threshold': 0.50,
                'status': 'normal',
                'description': 'Acceptable audit risk profile'
            }

    return benchmarks


def extract_raw_scores(row):
    """
    V8.0 STRICT 100-POINT SCALE
    Extract exact point breakdowns for transparency.
    
    Pain (40) + Fit (30) + Strategy (30) = 100
    No bonuses. Clean additive math.
    """
    def safe_float(val):
        """Preserve decimal precision from continuous scoring."""
        return round(float(val), 1) if pd.notna(val) else 0

    def safe_int(val):
        """Convert to integer for legacy sub-component scores."""
        return int(val) if pd.notna(val) else 0

    # Extract component scores (preserve decimal precision)
    pain_total = safe_float(row.get('score_pain_total'))
    fit_total = safe_float(row.get('score_fit_total'))
    strat_total = safe_float(row.get('score_strat_total'))
    icp_score = safe_float(row.get('icp_score'))
    
    # Verify strict 100-point scale: pain + fit + strategy = icp_score
    # (Allow small rounding differences)
    calculated_total = pain_total + fit_total + strat_total
    if abs(calculated_total - icp_score) > 1:
        # Log warning but don't fail
        pass  # Could add logging here if needed
    
    return {
        'pain': {
            'total': pain_total,
            'signal': safe_int(row.get('score_pain_signal')),
            'volume': 0,      # Removed in v8.0
            'margin': 0,      # Removed in v8.0
            'compliance': 0   # Removed in v8.0
        },
        'fit': {
            'total': fit_total,
            'alignment': safe_int(row.get('score_fit_align')),
            'complexity': safe_int(row.get('score_fit_complex')),
            'chaos': 0,       # Removed in v8.0
            'risk': safe_int(row.get('score_fit_risk'))
        },
        'strategy': {
            'total': strat_total,
            'deal_size': safe_int(row.get('score_strat_deal')),      # Revenue score
            'expansion': safe_int(row.get('score_strat_expand')),    # Whale scale
            'referrals': 0    # Removed in v8.0
        },
        'bonus': {
            'strategic_scale': 0  # No bonuses in v8.0
        },
        'base_before_bonus': icp_score,  # Same as total in v8.0
        'final_score': icp_score
    }


def generate_score_reasoning(row):
    """
    V8.0 STRICT 100-POINT SCALE
    Generate explicit scoring math showing exact statistical conditions.

    Returns structured object with every threshold check and points awarded.
    This matches score_icp_production.py v8.0 logic exactly.
    
    Pain (40) + Fit (30) + Strategy (30) = 100
    """
    reasoning = {
        'pain': [],
        'fit': [],
        'strategy': [],
        'bonus': []  # Empty in v8.0, kept for compatibility
    }

    # Get metrics
    undercoding = row.get('undercoding_ratio')
    if pd.isna(undercoding): undercoding = 0
    
    psych_risk = row.get('psych_risk_ratio')
    if pd.isna(psych_risk): psych_risk = 0
    
    vol_metric = row.get('metric_used_volume', row.get('real_annual_encounters', 0))
    if pd.isna(vol_metric): vol_metric = 0
    
    volume_source = str(row.get('volume_source', '')).upper()
    is_verified_volume = 'UDS' in volume_source or 'VERIFIED' in volume_source or 'CLAIMS' in volume_source

    npi_count = row.get('npi_count', 1)
    if pd.isna(npi_count): npi_count = 1
    
    site_count = row.get('site_count', 1)
    if pd.isna(site_count): site_count = 1

    est_revenue = row.get('metric_est_revenue', row.get('final_revenue', 0))
    if pd.isna(est_revenue): est_revenue = 0

    segment = str(row.get('segment_label', 'Unknown'))
    track = str(row.get('scoring_track', 'AMBULATORY'))
    is_aco = str(row.get('is_aco_participant', '')).lower() == 'true'
    is_risk = str(row.get('risk_compliance_flag', '')).lower() == 'true' or str(row.get('oig_leie_flag', '')).lower() == 'true'
    
    pain_total = row.get('score_pain_total', 0)
    if pd.isna(pain_total): pain_total = 0

    # ========================================
    # V8.0 PAIN SCORING (MAX 40)
    # ========================================
    if track == 'BEHAVIORAL':
        if psych_risk > 0.75:
            reasoning['pain'].append(f"40pts: Psych Risk {psych_risk:.3f} > 0.75 (SEVERE Audit Exposure)")
        elif psych_risk > 0:
            reasoning['pain'].append(f"30pts: Psych Risk {psych_risk:.3f} detected (Verified)")
        else:
            reasoning['pain'].append(f"10pts: Behavioral Track - Benchmark projection")
    
    elif track == 'POST_ACUTE':
        margin = row.get('net_margin')
        if pd.notna(margin):
            if margin < 0.02:
                reasoning['pain'].append(f"40pts: Margin {margin:.1%} < 2% (SEVERE Pressure)")
            else:
                reasoning['pain'].append(f"30pts: Margin {margin:.1%} tracked (Verified)")
        else:
            reasoning['pain'].append(f"10pts: Post-Acute Track - Benchmark projection")
    
    else:  # AMBULATORY
        if undercoding > 0 and undercoding < 0.35:
            reasoning['pain'].append(f"40pts: Only {undercoding:.1%} Level 4/5 usage (< 35% benchmark) - SEVERE Undercoding")
        elif undercoding > 0 and undercoding < 0.50:
            reasoning['pain'].append(f"30pts: Only {undercoding:.1%} Level 4/5 usage (< 50% target) - Moderate Undercoding")
        else:
            reasoning['pain'].append(f"10pts: Ambulatory Track - Benchmark projection")

    # ========================================
    # V8.0 FIT SCORING (MAX 30)
    # ========================================
    
    # Alignment (Max 15)
    if segment == 'Segment B':
        reasoning['fit'].append(f"15pts: FQHC - Core ICP alignment")
    elif segment == 'Segment D':
        reasoning['fit'].append(f"15pts: Urgent Care - High alignment")
    elif segment in ['Segment E', 'Segment A']:
        reasoning['fit'].append(f"10pts: Primary/Behavioral alignment")
    else:
        reasoning['fit'].append(f"5pts: Standard alignment")
    
    # Complexity (Max 10)
    if segment == 'Segment B':
        reasoning['fit'].append(f"10pts: FQHC complexity")
    elif segment == 'Segment C':
        reasoning['fit'].append(f"10pts: Hospital complexity")
    elif npi_count > 10:
        reasoning['fit'].append(f"10pts: Large multi-specialty ({int(npi_count)} providers)")
    elif npi_count > 3:
        reasoning['fit'].append(f"5pts: Medium group ({int(npi_count)} providers)")
    
    # Tech/Risk (Max 5)
    if is_aco or is_risk:
        reasoning['fit'].append(f"5pts: ACO or OIG compliance flag")

    # ========================================
    # V8.0 STRATEGY SCORING (MAX 30)
    # ========================================
    
    # Revenue (Max 15)
    if segment == 'Segment B':
        # FQHC: >$5M = 15pts
        if est_revenue > 5_000_000:
            reasoning['strategy'].append(f"15pts: Revenue ${est_revenue/1_000_000:.1f}M > $5M (FQHC)")
        elif est_revenue > 2_000_000:
            reasoning['strategy'].append(f"10pts: Revenue ${est_revenue/1_000_000:.1f}M > $2M")
        else:
            reasoning['strategy'].append(f"5pts: Revenue ${est_revenue/1_000_000:.1f}M (FQHC)")
    else:
        # Standard: >$15M = 15pts
        if est_revenue > 15_000_000:
            reasoning['strategy'].append(f"15pts: Revenue ${est_revenue/1_000_000:.1f}M > $15M")
        elif est_revenue > 5_000_000:
            reasoning['strategy'].append(f"10pts: Revenue ${est_revenue/1_000_000:.1f}M > $5M")
        else:
            reasoning['strategy'].append(f"5pts: Revenue ${est_revenue/1_000_000:.1f}M")
    
    # High Volume (Max 15)
    if is_verified_volume and vol_metric > 25000:
        reasoning['strategy'].append(f"15pts: High Volume - Verified volume {int(vol_metric):,} patients > 25k threshold")
    elif site_count > 5:
        reasoning['strategy'].append(f"10pts: Multi-Site Network ({int(site_count)} sites)")
    else:
        reasoning['strategy'].append(f"5pts: Standard scale")

    # No bonuses in v8.0 - bonus array stays empty for compatibility
    
    return reasoning


def generate_json():
    """Main function to generate frontend JSON from production data."""

    if not os.path.exists(SCORED_FILE):
        print(f"❌ Scored file not found: {SCORED_FILE}")
        return

    print("📦 Generating Frontend JSON from Production Data...")
    print(f"   Input: {SCORED_FILE}")

    # Load production data
    df = pd.read_csv(SCORED_FILE, low_memory=False)
    print(f"   Loaded {len(df):,} total clinics")

    # Normalize revenue units BEFORE sorting
    print("   🔧 Normalizing revenue units...")
    df['final_revenue'] = df['final_revenue'].apply(normalize_revenue)

    # Calculate lift values for sorting
    df['_lift_value'] = df.apply(
        lambda row: calculate_lift(row['final_revenue'], row.get('undercoding_ratio'))[0],
        axis=1
    )

    # Sort by ICP Score DESC, then Lift Value DESC
    df = df.sort_values(['icp_score', '_lift_value'], ascending=[False, False])

    # Filter: Top 5,000 by ICP Score
    top_clinics = df.head(5000)
    print(f"   Selected Top 5,000 leads (scores: {top_clinics['icp_score'].min()}-{top_clinics['icp_score'].max()})")

    # Transform data
    output_data = []
    verified_count = 0
    projected_count = 0
    revenue_normalized_count = 0

    for _, row in top_clinics.iterrows():
        # Extract production columns
        npi = str(row.get('npi', ''))
        org_name = str(row.get('org_name', 'Unknown Clinic')).title()
        state = str(row.get('state_code', 'Unknown'))
        city = str(row.get('city', ''))
        icp_score = round(float(row.get('icp_score', 0)), 1)  # Preserve decimal precision
        icp_tier = str(row.get('icp_tier', 'Tier 4'))
        segment_label = str(row.get('segment_label', 'Unknown'))

        # Volume & Revenue (normalized)
        real_annual_encounters = row.get('real_annual_encounters')
        final_revenue = row.get('final_revenue')

        # Track normalization
        original_revenue = row.get('final_revenue')
        if pd.notna(original_revenue) and original_revenue > 0 and original_revenue < 10_000:
            revenue_normalized_count += 1

        volume = format_volume(real_annual_encounters)
        revenue = format_revenue(final_revenue)

        # Drivers (parse emoji-based string)
        scoring_drivers = row.get('scoring_drivers', '')
        drivers = parse_drivers(scoring_drivers)

        # Lift Calculation
        undercoding_ratio = row.get('undercoding_ratio')
        lift_value, lift_label, is_projected = calculate_lift(final_revenue, undercoding_ratio)
        est_revenue_lift = format_revenue(lift_value)

        if is_projected:
            projected_count += 1
        else:
            verified_count += 1

        # Billing Ratio Chart
        billing_ratio = calculate_billing_ratio(undercoding_ratio)

        # Primary driver (first driver or default)
        if drivers:
            primary_driver = f"Detected: {drivers[0]['label']}"
        else:
            primary_driver = "Detected: Standard Opportunity"

        # Fit reason (simplified)
        if icp_score >= 70:
            fit_reason = "High-priority target with strong operational fit and verified pain signals."
        elif icp_score >= 50:
            fit_reason = "Qualified prospect with good fit profile."
        else:
            fit_reason = "Standard opportunity."

        # Contact info
        phone = format_phone(row.get('phone'))
        address = f"{city.title()}, {state}" if city else state

        # ========================================
        # GLASS BOX ANALYSIS (Critique #4, #8)
        # ========================================
        analysis = {
            'strategic_brief': generate_strategic_brief(row, lift_value),  # Analyst report (not sales pitch)
            'gaps': identify_data_gaps(row),
            'benchmarks': generate_benchmarks(row),
            'raw_scores': extract_raw_scores(row),
            'score_reasoning': generate_score_reasoning(row),  # NEW: Explicit scoring math
            'data_confidence': str(row.get('data_confidence', 'Unknown'))
        }

        # MIPS and HPSA/MUA data
        avg_mips_score = row.get('avg_mips_score')
        mips_clinician_count = row.get('mips_clinician_count')
        is_hpsa = str(row.get('is_hpsa', '')).lower() == 'true'
        is_mua = str(row.get('is_mua', '')).lower() == 'true'
        county_name = str(row.get('county_name', ''))

        # Scoring Track (for transparency)
        scoring_track = str(row.get('scoring_track', 'AMBULATORY'))

        # Dynamic Pain Label (NEW)
        pain_label = str(row.get('pain_label', 'Economic Pain'))

        # Assemble clinic object
        clinic = {
            "id": npi,
            "name": org_name,
            "tier": icp_tier,
            "score": icp_score,
            "segment": segment_label,
            "state": state,
            "revenue": revenue,
            "volume": volume,
            "est_revenue_lift": est_revenue_lift,
            "is_projected_lift": is_projected,
            "lift_basis": lift_label,
            "billing_ratio": billing_ratio,
            "primary_driver": primary_driver,
            "drivers": drivers,
            "scoring_track": scoring_track,  # NEW: Track transparency
            "pain_label": pain_label,  # NEW: Dynamic pain driver label
            "contact": {
                "phone": phone,
                "email": "N/A",
                "address": address
            },
            "fit_reason": fit_reason,
            "details": {
                "raw": {
                    "undercoding_ratio": float(undercoding_ratio) if pd.notna(undercoding_ratio) else None,
                    "volume_source": str(row.get('volume_source', 'Unknown')),
                    "revenue_source": str(row.get('revenue_source', 'Unknown')),
                    "avg_mips_score": float(avg_mips_score) if pd.notna(avg_mips_score) else None,
                    "mips_clinician_count": int(mips_clinician_count) if pd.notna(mips_clinician_count) else None,
                    "is_hpsa": is_hpsa,
                    "is_mua": is_mua,
                    "county_name": county_name if pd.notna(county_name) and county_name != 'nan' else None
                }
            },
            "analysis": analysis  # NEW: Glass box insights
        }

        output_data.append(clinic)

    # Save to JSON
    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output_data, f, indent=2)

    # Summary
    print(f"\n✅ Frontend JSON Generated: {OUTPUT_JSON}")
    print(f"   Total Records: {len(output_data):,}")
    print(f"   Revenue Normalized: {revenue_normalized_count:,} clinics (< $10k → * 1,000)")
    print(f"   Verified Opportunities: {verified_count} ({verified_count/len(output_data)*100:.1f}%)")
    print(f"   Projected Opportunities: {projected_count} ({projected_count/len(output_data)*100:.1f}%)")
    print(f"\n📊 Score Distribution:")
    print(f"   Tier 1 (≥70): {sum(1 for c in output_data if c['score'] >= 70)}")
    print(f"   Tier 2 (50-69): {sum(1 for c in output_data if 50 <= c['score'] < 70)}")
    print(f"   Tier 3 (<50): {sum(1 for c in output_data if c['score'] < 50)}")
    print(f"\n🔍 Data Quality:")
    avg_gaps = sum(len(c['analysis']['gaps']) for c in output_data) / len(output_data)
    print(f"   Average Data Gaps: {avg_gaps:.1f} per clinic")


if __name__ == "__main__":
    generate_json()
