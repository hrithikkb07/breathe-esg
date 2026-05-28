# TRADEOFFS.md

Three things deliberately not built, and why.

---

## 1. Async Ingestion Queue (Celery)

**What it would do**: File uploads would be received by the Django view, stored, and then
handed to a Celery worker queue for processing. The view returns immediately with a 202
Accepted. The frontend polls a `/uploads/{id}/status` endpoint until processing is complete.

**Why it matters**: For very large files (500MB SAP exports with 500,000 rows) or slow
external dependencies (e.g., calling an airport distance API per row), synchronous processing
blocks the web worker for minutes. Under load, this exhausts the worker pool.

**Why I didn't build it**: The file sizes in scope (monthly CSV exports from facilities teams)
are typically 1,000-50,000 rows. At those sizes, synchronous parsing takes 2-10 seconds —
within acceptable HTTP response time for a professional tool. Adding Celery requires:
a Redis or RabbitMQ broker (1 more service), a Celery worker process (1 more process),
retry/dead-letter queue configuration, worker health monitoring, and status polling
infrastructure on the frontend. That's 3-4 additional infrastructure concerns that add
complexity without improving correctness for the problem as stated.

**What I preserved for the future**: The ingestion entry point is `process_upload(upload_id)`.
Switching to async requires only wrapping this in a Celery task decorator:

```python
@celery_app.task
def process_upload_async(upload_id):
    process_upload(upload_id)
```

The service interface is unchanged. The view would change from:
```python
process_upload(str(upload.id))
```
to:
```python
process_upload_async.delay(str(upload.id))
```

That is the complete change. The architecture was intentionally designed to make this
a 10-minute migration, not a rearchitecture.

---

## 2. Emission Factor Database with Versioning

**What it would do**: A `EmissionFactor` table storing factors with effective dates,
geographic scope, source reference, and version history. When DEFRA publishes updated
factors (annually in June), an analyst uploads the new factor set. A re-normalization
pipeline recomputes `co2e_tonnes` for all records using the old factor set, creates
corrected records via supersession, and generates a diff report for auditor review.

**Why it matters**: Emission factors are not static. DEFRA updates UK grid factors annually.
IPCC AR6 revised GWPs. An enterprise client reporting over multiple years needs their
historical data updated when factors change. Hardcoded constants mean every factor update
requires a code deployment and manual re-computation.

**Why I didn't build it**: This is a 2-week project minimum. Getting the data model right —
handling geographic specificity (UK grid ≠ US grid ≠ Indian grid), fuel-type specificity,
market-based vs location-based for Scope 2, vintage years — is as complex as the rest of
the platform. The constants I've hardcoded are correct (DEFRA 2023) and are source-documented
in comments. For a prototype demonstrating ingestion architecture, this is the correct cut.

**What would change**: The normalization service currently does:
```python
ef = EMISSION_FACTORS["PURCHASED_ELECTRICITY"]["default"]
```

In production it would do:
```python
ef = EmissionFactor.objects.get_active(
    category="PURCHASED_ELECTRICITY",
    geography=upload.tenant.grid_region,
    date=record.period_start,
)
```

The interface is the same; only the data source changes.

---

## 3. User-Facing Export and Reporting

**What it would do**: An export endpoint that takes the set of approved, locked records
for a tenant/year/scope and produces: (a) a CSV in GHG Protocol format for auditor
submission, (b) a summary PDF with methodology notes and data provenance, (c) an API
response formatted for submission to CDP or the client's sustainability reporting platform.

**Why it matters**: The whole point of the ingestion and review workflow is to produce
a clean, auditable set of emission records for reporting. Without the export step, the
platform is a data warehouse with no output.

**Why I didn't build it**: The assignment asks for "ingest, normalize, and surface a review
dashboard where analysts can approve rows before they're locked for audit." The ingestion,
normalization, and review workflow are complete. The export is the next step, but it's also
the most stakeholder-specific step — the format depends entirely on which reporting framework
(GHG Protocol, CDP, TCFD, GRI), which regulator, and which auditor the client is working
with. Building a generic export without knowing the target format would produce either a toy
CSV or a speculative schema. This is the right thing to defer: ship the data pipeline, then
design the output with the actual client requirements in hand.

**What's already in place for this**: The `is_locked` field on `NormalizedEmissionRecord`
and the `RECORD_LOCKED` audit event are specifically designed for the export workflow.
The export endpoint would: query `is_locked=True, review_status=APPROVED`, render the
output format, and write a `RECORD_EXPORTED` audit event. The infrastructure is there;
the output format is not.

---

## What I'd Prioritize in Week 2

1. Emission factor database (highest business impact — this affects accuracy)
2. Async ingestion queue (needed before any enterprise client with real data volumes)
3. Export pipeline (needed before any client can actually use the output)
