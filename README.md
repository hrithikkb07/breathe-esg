# Breathe ESG — Data Ingestion Platform

A Django + React prototype for ingesting, normalizing, and reviewing ESG emissions
data from enterprise sources.

**Live demo:** `https://breathe-esg.onrender.com`  
**Credentials:** `analyst / demo1234`

---

## Architecture

```
frontend/           React + Tailwind analyst dashboard
backend/
  esg/
    models/         Data model (Tenant, Upload, RawRecord, NormalizedRecord, AuditLog)
    services/       Ingestion pipeline, parsers, normalization, suspicious detection
    serializers/    DRF serializers (read/write separated)
    views/          Thin API views, delegate to services
    management/     seed_demo_data command
  config/           Django settings, URLs, WSGI
sample_data/        Realistic CSV samples for all 3 sources
docs/               MODEL.md, DECISIONS.md, TRADEOFFS.md, SOURCES.md
render.yaml         One-click Render deployment
```

## Data Model Summary

```
Tenant → SourceUpload → RawRecord → NormalizedEmissionRecord
                                              ↓
                                          AuditLog (append-only)
```

Every normalized record traces to a specific raw row in a specific file.
Records are never deleted. Approved records are locked (immutable).
See `docs/MODEL.md` for full rationale.

## Three Sources

| Source | Format | Scope |
|--------|--------|-------|
| SAP fuel/procurement | CSV (German or English headers, semicolon or comma) | Scope 1 |
| Utility electricity | CSV portal export | Scope 2 |
| Corporate travel (Concur/Navan) | CSV trip export | Scope 3 |

Sample files are in `sample_data/`. Each was designed to trigger specific
detection logic (negative values, duplicate invoices, implausible distances).

## Local Development

**Backend**
```bash
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL, then:
createdb breathe_esg
python manage.py migrate
python manage.py seed_demo_data
python manage.py runserver
```

**Frontend**
```bash
cd frontend
npm install
# Set VITE_API_URL in .env.local:
echo "VITE_API_URL=http://localhost:8000/api" > .env.local
npm run dev
```

## Deployment (Render)

1. Push to GitHub
2. Render → New → Blueprint → select this repo
3. Render reads `render.yaml` and creates: API + static site + PostgreSQL
4. After first deploy, shell into the API service and run:
   ```
   python manage.py seed_demo_data
   ```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/token/` | JWT login |
| GET | `/api/dashboard/summary/` | Aggregate counts for dashboard |
| POST | `/api/uploads/` | Upload and ingest a CSV |
| GET | `/api/uploads/` | Ingestion history |
| GET | `/api/records/` | All normalized records (filterable) |
| GET | `/api/records/{id}/` | Record detail with raw data |
| POST | `/api/records/{id}/review/` | Approve or reject |
| POST | `/api/records/bulk-review/` | Bulk approve/reject |
| GET | `/api/audit-log/` | Audit trail |

## Key Documents

- `docs/MODEL.md` — Data model rationale
- `docs/DECISIONS.md` — Every ambiguity resolved
- `docs/TRADEOFFS.md` — Three deliberate non-builds
- `docs/SOURCES.md` — Research basis for each data source format
