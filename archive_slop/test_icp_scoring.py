#!/usr/bin/env python3
"""
Test script for ICP Scoring System

This script validates the ICP scoring logic by:
1. Loading ICP scores
2. Checking data completeness
3. Validating score ranges
4. Analyzing tier/segment distribution
5. Inspecting bibliography entries
6. Testing edge cases
"""

import os
import sys
import ast
from typing import Dict, Any

import pandas as pd

# Add parent directory to path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)

ICP_FILE = os.path.join(ROOT, "data", "curated", "clinics_icp.csv")
ICP_SCORES_FILE = os.path.join(ROOT, "data", "curated", "icp_scores.csv")


def print_header(title: str):
    """Print a formatted header."""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def print_section(title: str):
    """Print a formatted section header."""
    print(f"\n{'─' * 80}")
    print(f"  {title}")
    print(f"{'─' * 80}")


def test_data_availability():
    """Test 1: Check if ICP data files exist."""
    print_header("TEST 1: DATA AVAILABILITY")
    
    tests = {
        "ICP Full Dataset": ICP_FILE,
        "ICP Scores Summary": ICP_SCORES_FILE
    }
    
    all_passed = True
    for name, path in tests.items():
        if os.path.exists(path):
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f"✓ {name}: FOUND ({size_mb:.1f} MB)")
        else:
            print(f"❌ {name}: NOT FOUND")
            print(f"   Expected: {path}")
            all_passed = False
    
    return all_passed


def test_score_ranges():
    """Test 2: Validate score ranges."""
    print_header("TEST 2: SCORE RANGE VALIDATION")
    
    df = pd.read_csv(ICP_FILE)
    
    score_columns = {
        "icp_fit_score": (0, 20),
        "icp_pain_score": (0, 20),
        "icp_compliance_score": (0, 10),
        "icp_propensity_score": (0, 10),
        "icp_scale_score": (0, 20),
        "icp_segment_score": (0, 20),
        "icp_total_score": (0, 100),
    }
    
    all_passed = True
    for col, (min_val, max_val) in score_columns.items():
        if col not in df.columns:
            print(f"❌ {col}: COLUMN NOT FOUND")
            all_passed = False
            continue
        
        actual_min = df[col].min()
        actual_max = df[col].max()
        actual_mean = df[col].mean()
        
        if actual_min < min_val or actual_max > max_val:
            print(f"❌ {col}: OUT OF RANGE")
            print(f"   Expected: {min_val}-{max_val}")
            print(f"   Actual: {actual_min:.1f}-{actual_max:.1f} (mean: {actual_mean:.1f})")
            all_passed = False
        else:
            print(f"✓ {col}: {actual_min:.1f}-{actual_max:.1f} (mean: {actual_mean:.1f}) ✓")
    
    return all_passed


def test_tier_distribution():
    """Test 3: Analyze tier distribution."""
    print_header("TEST 3: TIER DISTRIBUTION")
    
    df = pd.read_csv(ICP_FILE)
    
    if "icp_tier" not in df.columns:
        print("❌ icp_tier column not found")
        return False
    
    total = len(df)
    tier_counts = df["icp_tier"].value_counts().sort_index()
    
    print(f"\nTotal Clinics: {total:,}\n")
    
    tier_labels = {
        1: "Tier 1 (HOT)",
        2: "Tier 2 (Qualified)",
        3: "Tier 3 (Monitor)"
    }
    
    for tier_num in [1, 2, 3]:
        count = tier_counts.get(tier_num, 0)
        percentage = (count / total) * 100
        label = tier_labels[tier_num]
        print(f"  {label:25} {count:>8,} ({percentage:>5.2f}%)")
    
    # Check tier logic (UPDATED THRESHOLDS: Nov 2025)
    print("\n  Tier Logic Validation (Updated Thresholds: 70/50):")
    tier_1 = df[df["icp_tier"] == 1]
    tier_2 = df[df["icp_tier"] == 2]
    tier_3 = df[df["icp_tier"] == 3]
    
    tier_1_min = tier_1["icp_total_score"].min() if len(tier_1) > 0 else None
    tier_2_min = tier_2["icp_total_score"].min() if len(tier_2) > 0 else None
    tier_2_max = tier_2["icp_total_score"].max() if len(tier_2) > 0 else None
    tier_3_max = tier_3["icp_total_score"].max() if len(tier_3) > 0 else None
    
    all_passed = True
    
    if tier_1_min is not None and tier_1_min < 70:
        print(f"    ❌ Tier 1 min score: {tier_1_min:.1f} (expected ≥ 70)")
        all_passed = False
    elif tier_1_min is not None:
        print(f"    ✓ Tier 1 min score: {tier_1_min:.1f} ≥ 70")
    else:
        print(f"    ℹ️  Tier 1: No clinics (max score below 70 threshold)")
    
    if tier_2_min is not None and (tier_2_min < 50 or tier_2_max >= 70):
        print(f"    ❌ Tier 2 range: {tier_2_min:.1f}-{tier_2_max:.1f} (expected 50-69)")
        all_passed = False
    elif tier_2_min is not None:
        print(f"    ✓ Tier 2 range: {tier_2_min:.1f}-{tier_2_max:.1f} (50-69)")
    
    if tier_3_max is not None and tier_3_max >= 50:
        print(f"    ❌ Tier 3 max score: {tier_3_max:.1f} (expected < 50)")
        all_passed = False
    elif tier_3_max is not None:
        print(f"    ✓ Tier 3 max score: {tier_3_max:.1f} < 50")
    
    return all_passed


def test_segment_distribution():
    """Test 4: Analyze segment distribution."""
    print_header("TEST 4: SEGMENT DISTRIBUTION")
    
    df = pd.read_csv(ICP_FILE)
    
    if "icp_segment" not in df.columns:
        print("❌ icp_segment column not found")
        return False
    
    total = len(df)
    segment_counts = df["icp_segment"].value_counts().sort_index()
    
    print(f"\nTotal Clinics: {total:,}\n")
    
    segment_labels = {
        "A": "Segment A (Behavioral/Home Health)",
        "B": "Segment B (FQHC/Compliance)",
        "C": "Segment C (Multi-Specialty/Growth)"
    }
    
    for segment_letter in ["A", "B", "C"]:
        count = segment_counts.get(segment_letter, 0)
        percentage = (count / total) * 100
        label = segment_labels[segment_letter]
        print(f"  {label:40} {count:>8,} ({percentage:>5.2f}%)")
    
    # Sample segment A and B clinics
    print("\n  Sample Segment A Clinics:")
    segment_a = df[df["icp_segment"] == "A"].head(3)
    for _, row in segment_a.iterrows():
        print(f"    • {row['account_name'][:50]:50} | {row['segment_label']}")
    
    if segment_counts.get("B", 0) > 0:
        print("\n  Sample Segment B Clinics:")
        segment_b = df[df["icp_segment"] == "B"].head(3)
        for _, row in segment_b.iterrows():
            print(f"    • {row['account_name'][:50]:50} | {row['segment_label']}")
    else:
        print("\n  ⚠️  No Segment B clinics found (FQHC flag likely missing in data)")
    
    return True


def test_bibliography_completeness():
    """Test 5: Check bibliography entries."""
    print_header("TEST 5: BIBLIOGRAPHY COMPLETENESS")
    
    df = pd.read_csv(ICP_FILE)
    
    if "icp_bibliography" not in df.columns:
        print("❌ icp_bibliography column not found")
        return False
    
    # Sample 100 random clinics
    sample = df.sample(min(100, len(df)))
    
    bibliography_stats = {
        "total_entries": 0,
        "missing_data_entries": 0,
        "available_data_entries": 0,
        "sources_used": set()
    }
    
    for _, row in sample.iterrows():
        try:
            bib = ast.literal_eval(row["icp_bibliography"])
            bibliography_stats["total_entries"] += len(bib)
            
            for entry in bib:
                if entry.get("status") == "MISSING":
                    bibliography_stats["missing_data_entries"] += 1
                else:
                    bibliography_stats["available_data_entries"] += 1
                
                sources = entry.get("sources", [])
                bibliography_stats["sources_used"].update(sources)
        except:
            pass
    
    print(f"\nSample Size: {len(sample):,} clinics\n")
    print(f"  Total Bibliography Entries: {bibliography_stats['total_entries']:,}")
    print(f"  Available Data Entries: {bibliography_stats['available_data_entries']:,}")
    print(f"  Missing Data Entries: {bibliography_stats['missing_data_entries']:,}")
    
    if bibliography_stats['total_entries'] > 0:
        missing_pct = (bibliography_stats['missing_data_entries'] / bibliography_stats['total_entries']) * 100
        print(f"  Missing Data Rate: {missing_pct:.1f}%")
    
    print(f"\n  Data Sources Used ({len(bibliography_stats['sources_used'])} total):")
    for source in sorted(bibliography_stats['sources_used']):
        if source != "none" and source != "default":
            print(f"    • {source}")
    
    return True


def test_top_scorers():
    """Test 6: Inspect top scoring clinics."""
    print_header("TEST 6: TOP SCORING CLINICS")
    
    df = pd.read_csv(ICP_FILE)
    
    top_10 = df.nlargest(10, "icp_total_score")
    
    print(f"\nTop 10 Clinics by ICP Score:\n")
    
    for i, row in top_10.iterrows():
        print(f"{row['account_name'][:60]:60}")
        print(f"  Location: {row['state_code']}")
        print(f"  Segment: {row.get('segment_label', 'N/A')}")
        print(f"  ICP Score: {row['icp_total_score']:.1f}/100 | Tier: {row['icp_tier_label']} | Segment: {row['icp_segment']}")
        print(f"  Breakdown: Fit={row['icp_fit_score']:.1f} | Pain={row['icp_pain_score']:.1f} | "
              f"Compliance={row['icp_compliance_score']:.1f} | Propensity={row['icp_propensity_score']:.1f} | "
              f"Scale={row['icp_scale_score']:.1f} | Segment={row['icp_segment_score']:.1f}")
        print(f"  Operational: {row.get('npi_count', 0):.0f} providers | {row.get('site_count', 0):.0f} sites")
        print()
    
    return True


def test_data_gaps():
    """Test 7: Identify data gaps."""
    print_header("TEST 7: DATA GAP ANALYSIS")
    
    df = pd.read_csv(ICP_FILE)
    
    key_fields = {
        "segment_label": "Specialty/Segment",
        "npi_count": "Provider Count",
        "site_count": "Site Count",
        "fqhc_flag": "FQHC Flag",
        "oig_leie_flag": "OIG LEIE Flag",
        "bene_count": "Medicare Patient Count",
        "allowed_amt": "Medicare Reimbursement",
        "denial_pressure": "Denial Pressure",
        "coding_complexity": "Coding Complexity",
        "roi_readiness": "ROI Readiness",
        "aco_member": "ACO Participation",
        "pecos_enrolled": "PECOS Enrollment",
    }
    
    print(f"\nTotal Clinics: {len(df):,}\n")
    print(f"{'Field':<30} {'Available':<15} {'Missing':<15} {'Coverage':<10}")
    print(f"{'-' * 80}")
    
    for field, label in key_fields.items():
        if field in df.columns:
            available = df[field].notna().sum()
            missing = df[field].isna().sum()
            coverage = (available / len(df)) * 100
            
            # Special handling for boolean/integer flags
            if field in ["fqhc_flag", "aco_member", "pecos_enrolled", "oig_leie_flag"]:
                positive = (df[field] >= 1).sum() if field in df.columns else 0
                print(f"{label:<30} {positive:>10,} (≥1) {len(df) - positive:>10,} (=0)   {positive/len(df)*100:>6.1f}%")
            else:
                status = "✓" if coverage >= 80 else "⚠️" if coverage >= 50 else "❌"
                print(f"{label:<30} {available:>10,}     {missing:>10,}     {coverage:>5.1f}% {status}")
        else:
            print(f"{label:<30} {'COLUMN NOT FOUND':>40} ❌")
    
    # Key findings
    print("\n  Key Findings:")
    
    if "fqhc_flag" in df.columns:
        fqhc_count = (df["fqhc_flag"] >= 1).sum()
        if fqhc_count == 0:
            print("    ❌ No FQHC clinics detected → Segment B will be empty")
        else:
            print(f"    ✓ {fqhc_count:,} FQHC clinics detected")
    
    if "oig_leie_flag" not in df.columns:
        print("    ❌ OIG LEIE flag not in dataset → Compliance scores may be lower")
    
    if "bene_count" in df.columns:
        bene_available = df["bene_count"].notna().sum()
        bene_pct = (bene_available / len(df)) * 100
        if bene_pct < 50:
            print(f"    ⚠️  Medicare patient data only {bene_pct:.1f}% complete → Pain/Scale scores affected")
    
    return True


def main():
    """Run all tests."""
    print_header("ICP SCORING SYSTEM VALIDATION")
    print("Version: 1.0")
    print("Date: November 16, 2025")
    
    tests = [
        ("Data Availability", test_data_availability),
        ("Score Ranges", test_score_ranges),
        ("Tier Distribution", test_tier_distribution),
        ("Segment Distribution", test_segment_distribution),
        ("Bibliography", test_bibliography_completeness),
        ("Top Scorers", test_top_scorers),
        ("Data Gaps", test_data_gaps),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ Test failed with error: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    # Summary
    print_header("TEST SUMMARY")
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    print(f"\nTests Passed: {passed}/{total}\n")
    
    for name, result in results:
        status = "✓ PASS" if result else "❌ FAIL"
        print(f"  {name:<30} {status}")
    
    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

