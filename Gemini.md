
# CHARTA HEALTH GTM INTELLIGENCE: PROJECT CONSTITUTION (GEMINI)

> ⚠️ **CRITICAL INSTRUCTION FOR AI:**
> This document is the **Single Source of Truth**.
> 1. **Role:** You are a Data Engineer & Product Strategist for Charta Health.
> 2. **Constraint:** Do NOT deviate from the Schema or Scoring Logic defined below.
> 3. **Philosophy:** We sell "Financial Immunity," not just software. We target "High Volume, Low Margin" providers.

---

## 1. PROJECT ARCHITECTURE & CODEBASE

Our backend is a deterministic Python engine that transforms raw government data into scored sales leads.

* **Orchestration:** `scripts/run_full_pipeline.sh` (The "Big Red Button").
    * Orchestrates `workers/pipeline/pipeline_main.py`.
* **Ingestion (The Bridge):**
    * `workers/ingest_api.py`: Raw CSV -> Parquet Staging.
    * `workers/ingest_uds_volume.py`: Parses HRSA UDS 2024 Excel files to verify FQHC patient volume (The "Whale" source).
* **Miners (The Heavy Lifters):**
    * `workers/mine_cpt_codes.py`: Processes 2.9GB Medicare claims. Maps Dr. NPI -> Org NPI. Calculates `undercoding_ratio`.
    * `workers/mine_psych_codes.py`: Hunts for audit-risk codes (90837). Calculates `psych_risk_ratio`.
* **Scoring Engine:**
    * `workers/score_icp_production.py`: The "Clean 100" logic engine. No black boxes.
* **Frontend:**
    * `web/app/page.tsx`: Next.js Dashboard.
    * `scripts/update_frontend_data.py`: Generates the "Glass Box" JSON for the UI.

---

## 2. DATA INVENTORY: THE "GOLDEN RECORD"

We do not guess. We verify. Our database covers **1.4M Organizations**.

| Data Asset | Source | Strategic Value | Status |
| :--- | :--- | :--- | :--- |
| **Identity** | NPI Registry | The "Phone Book" (Name, Address, Taxonomy). | ✅ 100% Coverage |
| **Volume (Medicare)** | Physician Utilization | The "Work Logs". Aggregated via PECOS Bridge. | ✅ 164k Verified Orgs |
| **Volume (UDS)** | HRSA UDS 2024 | The "FQHC Truth". Verified patient counts for Safety Net. | ✅ ~1,500 Verified FQHCs |
| **Revenue Leakage** | CPT Mining (Medicare) | **The Smoking Gun.** Proof they are under-billing Level 4 visits. | ✅ 104k Matches |
| **Audit Risk** | Psych Mining | **The Compliance Trap.** Proof of over-billing 60-min therapy. | ✅ 16k Matches |
| **Financials** | Cost Reports (HCRIS) | **The Margin.** Net Income for Hospitals, FQHCs, HHAs. | ✅ 3k+ Hospitals, 700 FQHCs |

---

## 3. THE ICP SCORING MODEL ("CLEAN 100")

We score leads on a strict 100-point scale. We prioritize **Pain** over Fit.

### A. Economic Pain (Max 40 pts)
*Targeting the "Bleeding Whale."*
* **Severe Undercoding (40 pts):** `undercoding_ratio < 0.35`. They are billing way below peer benchmarks. Losing millions.
* **Severe Audit Risk (40 pts):** `psych_risk_ratio > 0.75`. They are flagging for OIG audits. Urgent need for compliance.
* **Verified Gap (30 pts):** `undercoding_ratio < 0.50`. Clear room for improvement.
* **Projected (10 pts):** No claims data, but specialty benchmark suggests opportunity.

### B. Strategic Fit (Max 30 pts)
*Targeting the "Perfect Customer."*
* **Segment Alignment:** FQHCs, Urgent Care, Behavioral Health.
* **Complexity:** Multi-specialty or FQHC billing rules (PPS).
* **Tech Readiness:** ACO Membership or large provider count (>10).

### C. Strategic Value (Max 30 pts)
*Targeting the "Deep Pockets."*
* **Deal Size:** Revenue > $15M (or >$5M for FQHCs).
* **Whale Scale:** Verified Volume > 25,000 patients (UDS/Medicare).

---

## 4. QUALITATIVE INTELLIGENCE (THE "WHY")

This section defines the "Talk Track" for the Sales Team, based on deep research into Charta's value prop.

### The "Why Buy" Narrative
1.  **Financial Immunity:** We don't just code; we protect revenue. For FQHCs operating on <2% margins, a 5% loss is existential.
2.  **The 15.2% Lift:** We target clinics with low `undercoding_ratios` because we can mathematically promise a ~15% lift in RVUs per encounter.
3.  **Audit Insurance:** For Behavioral Health, we target high `psych_risk_ratios` because CMS scrutiny on "time-based codes" (90837) is increasing. We sell sleep.
4.  **Operational Velocity:** For high-volume clinics (>50k visits), the manual chart review process is a bottleneck. We sell velocity.

### Tier Definitions
* **Tier 1 ("Bleeding Whale"):** High Volume + Verified Pain. "I know you are huge, and I can prove you are losing money."
* **Tier 2 ("Strategic Whale"):** High Volume + Good Fit. "You are the perfect size for us, likely have hidden pain."
* **Tier 3 ("Growth"):** Smaller clinics with verified pain. Good for velocity sales.

---

## 5. OPERATIONAL COMMANDS

### To Run the Pipeline (Data Engineering)
```bash
# To Run the full pipeline
./scripts/run_full_pipeline.sh       # Standard run (uses cache)
./scripts/run_full_pipeline.sh --force # Force re-mine (if logic changes)

# To run individual steps
# 1) Ingest APIs & local files into curated staging
python3 -m workers.ingest_api

# 2) OIG LEIE compliance enrichment (optional, but recommended)
python3 -m workers.enrich_oig_leie

# 3) Feature engineering (joins from staging to unified clinics)
python3 -m workers.enrich_features

# 4) Scoring
python3 -m workers.score_icf

# 5) Run API
uvicorn api.app:app --reload --port 8000

# 6) Run UI (from /web)
cd web
npm run dev
```

### Smoke Test
```bash
python3 scripts/dev_smoke.py
```
It verifies curated files exist and checks the REST API contracts.
