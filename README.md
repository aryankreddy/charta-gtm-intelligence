# FinalChartaTool

Data pipeline and APIs that power the Charta Clinic Intelligence UI.

## Project Structure

- `workers/` — ingestion, enrichment, and scoring jobs
- `data/` — raw, staging, and curated outputs
- `api/` — FastAPI service serving /clinics endpoints
- `web/` — Next.js frontend (see `web/README.md` for UI instructions)

## Data Pipeline

```bash
# 1) Ingest APIs & local files into curated staging
python -m workers.ingest_api

# 2) Feature engineering (joins from staging to unified clinics)
python -m workers.enrich_features

# 3) Scoring
python -m workers.score_icf

# 4) Run API
uvicorn api.app:app --reload --port 8000

# 5) Run UI (from /web)
cd web
npm run dev
```

## Smoke Test

After running the three pipeline commands, execute:

```bash
python scripts/dev_smoke.py
```

It verifies curated files exist and checks the REST API contracts.
