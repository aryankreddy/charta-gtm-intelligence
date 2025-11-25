import pandas as pd
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCORED_FILE = os.path.join(ROOT, "data", "curated", "clinics_scored_final.csv")
OUTPUT_JSON = os.path.join(ROOT, "web", "public", "data", "clinics.json")
CERT_FILE = os.path.join(ROOT, "data", "raw", "cert_specialty_benchmarks.csv")

# Load CERT Benchmarks
CERT_BENCHMARKS = {}
if os.path.exists(CERT_FILE):
    try:
        cert_df = pd.read_csv(CERT_FILE)
        CERT_BENCHMARKS = dict(zip(cert_df['provider_type'].str.lower(), cert_df['improper_payment_rate']))
    except:
        pass

def clean_float(val):
    if pd.isna(val) or val == float('inf') or val == float('-inf'):
        return 0.0
    return float(val)

def generate_json():
    if not os.path.exists(SCORED_FILE):
        print("❌ Scored file not found.")
        return

    print("📦 Generating Frontend JSON...")
    df = pd.read_csv(SCORED_FILE, low_memory=False)
    
    # Filter: Top 500 Tier 1 & Tier 2
    # If not enough Tier 1/2, take top 500 by score
    top_clinics = df.sort_values('icp_score', ascending=False).head(500)
    
    # Select UI Columns
    # Map CSV columns to UI expected format
    # UI expects: id, name, tier, score, segment, state, revenue, volume, drivers, contact, fit_reason
    
    output_data = []
    
    for _, row in top_clinics.iterrows():
        # Format Revenue
        rev_val = row.get('metric_est_revenue', 0)
        if pd.isna(rev_val) or rev_val == 0: revenue = "N/A"
        elif rev_val >= 1_000_000: revenue = f"${rev_val/1_000_000:.1f}M"
        elif rev_val >= 1_000: revenue = f"${rev_val/1_000:.0f}k"
        else: revenue = f"${rev_val:.0f}"
        
        # Format Volume
        vol_val = row.get('metric_used_volume', 0)
        if pd.isna(vol_val) or vol_val == 0: volume = "N/A"
        else: volume = f"{vol_val:,.0f}"

        # Parse Drivers
        drivers = []
        raw_drivers = str(row.get('scoring_drivers', ''))
        if raw_drivers and raw_drivers != 'nan' and raw_drivers != 'Standard':
            parts = raw_drivers.split(' | ')
            for p in parts:
                color = "text-gray-600"
                if "Undercoding" in p: color = "text-red-600"
                elif "Margin" in p: color = "text-orange-600"
                elif "Volume" in p: color = "text-blue-600"
                elif "Rev" in p: color = "text-green-600"
                elif "FQHC" in p: color = "text-purple-600"
                
                label = p.split('(')[0].strip()
                value = p.split('(')[1].replace(')', '') if '(' in p else "High"
                
                drivers.append({"label": label, "value": value, "color": color})
        
        # Fit Reason
        score = row.get('icp_score', 0)
        fit_reason = "Strong operational fit."
        if score > 70:
            fit_reason = "High-priority target. "
            if row.get('score_pain_signal', 0) > 10:
                fit_reason += "Severe undercoding indicates immediate revenue opportunity. "
            if row.get('score_pain_margin', 0) > 5:
                fit_reason += "Margin pressure creates urgency. "
        
        # Segment
        seg = str(row.get('segment_label', 'Unknown'))
        if ' - ' in seg: seg = seg.split(' - ')[0]

        # Sub-scores and Metrics
        margin_val = row.get('net_margin')
        if pd.isna(margin_val): margin_val = row.get('hospital_margin')
        if pd.isna(margin_val): margin_val = row.get('fqhc_margin') # Added FQHC margin check
        
        # Calculate Revenue Lift & Billing Ratio
        undercoding = clean_float(row.get('undercoding_ratio'))
        est_rev = row.get('metric_est_revenue', 0)
        
        # NEW LOGIC: Projected Lift with Verification Flag
        if undercoding > 0:
            # Verified undercoding data exists
            lift_basis = "Based on coding gap"
            lift_pct = 0.12  # Assume 12% lift for verified undercoders
            is_projected_lift = False
            # Lift = Revenue * 12%
            lift_val = est_rev * lift_pct
        else:
            # Missing undercoding data - use CERT Benchmark or 3% fallback
            lift_basis = "Projected (Benchmark)"
            is_projected_lift = True
            
            # Lookup CERT Rate
            specialty = str(row.get('taxonomy_desc', '')).lower()
            if not specialty or specialty == 'nan':
                specialty = str(row.get('primary_specialty', '')).lower()
            
            projected_rate = 0.03 # Default fallback
            
            for cert_spec, rate in CERT_BENCHMARKS.items():
                if cert_spec in specialty:
                    projected_rate = rate
                    break
            
            # If no match, try segment mapping
            if projected_rate == 0.03:
                if seg == 'Segment B': projected_rate = 0.114 # Family Practice proxy
                elif seg == 'Segment D': projected_rate = 0.104 # Emergency/Urgent proxy
            
            lift_basis = f"Projected ({projected_rate*100:.1f}% Benchmark)"
            lift_val = est_rev * projected_rate
        
        if lift_val > 1_000_000: est_revenue_lift = f"${lift_val/1_000_000:.1f}M"
        elif lift_val > 1_000: est_revenue_lift = f"${lift_val/1_000:.0f}k"
        else: est_revenue_lift = f"${lift_val:.0f}"
        
        # Billing Ratio Simulation
        # If undercoding is present, skew based on it. If not, assume 50/50 benchmark.
        if undercoding > 0:
            level3_pct = min(95, 50 + (undercoding * 100))
        else:
            level3_pct = 60 # Slight skew for benchmark
            
        level4_pct = 100 - level3_pct
        
        # v8.0 Score Breakdown (Strict Sum Model)
        details = {
            "pain": {
                "total": int(row.get('score_pain_total', 0)),
                "leakage": int(row.get('score_pain_signal', 0)),
                "volume": int(row.get('score_pain_volume', 0)),
                "margin": int(row.get('score_pain_margin', 0))
            },
            "fit": {
                "total": int(row.get('score_fit_total', 0)),
                "profile": int(row.get('score_fit_align', 0)),
                "chaos": int(row.get('score_fit_chaos', 0))
            },
            "strat": {
                "total": int(row.get('score_strat_total', 0)),
                "deal": int(row.get('score_strat_deal', 0)),
                "influence": int(row.get('score_strat_ref', 0))
            },
            "sources": {
                "leakage": str(row.get('leakage_source', 'none')),
                "volume": str(row.get('volume_source', 'proxy'))
            },
            "raw": {
                "undercoding_ratio": undercoding,
                "margin": clean_float(margin_val),
                "npi_count": int(row.get('npi_count', 0))
            }
        }

        clinic = {
            "id": str(row.get('npi', '')),
            "name": str(row.get('org_name', 'Unknown Clinic')).title(),
            "tier": str(row.get('icp_tier', 'Tier 4')),
            "score": int(score),
            "segment": seg,
            "state": str(row.get('state_code', 'Unknown')),
            "revenue": revenue,
            "volume": volume,
            "est_revenue_lift": est_revenue_lift,
            "is_projected_lift": is_projected_lift,
            "lift_basis": lift_basis,
            "billing_ratio": {"level3": int(level3_pct), "level4": int(level4_pct)},
            "primary_driver": f"Detected: {drivers[0]['label']}" if drivers else "Detected: Standard Opportunity",
            "drivers": drivers[:3],
            "details": details,
            "contact": {
                "phone": str(row.get('phone', 'N/A')),
                "email": "N/A", 
                "address": f"{str(row.get('city', '')).title()}, {str(row.get('state_code', ''))}"
            },
            "fit_reason": fit_reason
        }
        output_data.append(clinic)
    
    # Export
    os.makedirs(os.path.dirname(OUTPUT_JSON), exist_ok=True)
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output_data, f, indent=2)
        
    # Summary Stats
    verified_count = sum(1 for c in output_data if not c['is_projected_lift'])
    projected_count = sum(1 for c in output_data if c['is_projected_lift'])
    
    print(f"✅ UI Data Ready: {OUTPUT_JSON} ({len(output_data)} records)")
    print(f"   Verified Opportunities: {verified_count}")
    print(f"   Projected Opportunities: {projected_count}")

if __name__ == "__main__":
    generate_json()