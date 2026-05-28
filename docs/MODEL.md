# MODEL.md

## Data Model Overview

This document explains the data model for the Breathe ESG ingestion platform. Every
design decision here has a reason. If you're reading this in a code review or interview,
I can defend any of it.

---

## The Provenance Chain

```
SourceUpload  →  RawRecord  →  NormalizedEmissionRecord
    │                                      │
    └── who uploaded, when, which file     └── scope, category, quantity, review status
```

Every normalized emission record traces back to:
1. A specific **row number** in a specific **file**
2. Which was uploaded by a specific **user** at a specific **time**
3. With the **exact raw data** preserved unchanged

This chain is non-negotiable for audit purposes. When an auditor asks "where did this
8,920 liter diesel figure come from?", we can answer with: file, row, timestamp, uploader.

---

## Multi-tenancy

**Approach**: Row-level multi-tenancy via a `tenant` foreign key on every data table.

**Why not schema-per-tenant**: Schema-per-tenant (one PostgreSQL schema per client) provides
stronger isolation and simpler queries (no tenant filter required). We chose row-level
because this is a prototype with one backend process, and schema-per-tenant requires either
dynamic schema switching middleware or separate DB connections per tenant — significantly
more complexity for the same correctness if the app layer is correct.

**What changes for production**: Add `SECURITY DEFINER` row-level security policies in
PostgreSQL and a database-level constraint that the application user cannot query rows
where `tenant_id != current_tenant_id`. This replaces app-layer filter discipline with
database enforcement.

**Multi-tenancy enforcement**: Every ViewSet inherits `TenantScopedMixin`, which applies
`filter(tenant=request.user.tenant)` to every queryset. This is the single enforcement
point — no tenant FK filter is written in individual views.

---

## Key Model Design Decisions

### `RawRecord`: Immutable Source of Truth

`RawRecord` stores the exact JSON of each CSV row as received. It is never updated after
creation. The `save()` override enforces this at the application layer.

**Why JSONField instead of typed columns**: Each source type (SAP, Utility, Travel) has
a completely different schema. A unified typed table would either be massively sparse or
require multiple tables. JSONField with PostgreSQL's JSONB backend gives us schema
flexibility without sacrificing query capability. We can index specific JSON paths when
needed.

**Why preserve raw data**: Normalization logic will change. Emission factors get updated.
Bugs get discovered. Without the raw data, re-normalization is impossible. The raw record
is our data liability protection: if we ever made a systematic error, we can re-run
normalization across all affected records.

### `NormalizedEmissionRecord`: Unified Emissions Schema

All three source types normalize into a single schema. Key fields:

| Field | Design Decision |
|---|---|
| `scope` | Integer (1/2/3). GHG Protocol scope. Determined by source type. |
| `emission_category` | String enum. More granular than scope (e.g., `STATIONARY_COMBUSTION` within Scope 1). |
| `activity_quantity` + `activity_unit` | Normalized to canonical units (liters, kWh, km, nights). |
| `original_quantity` + `original_unit` | Preserved pre-normalization values for traceability. |
| `emission_factor` + `emission_factor_source` | Stored per-record so recalculation is auditable when factors update. |
| `period_start` + `period_end` | Both dates. Utility billing periods don't align with calendar months. |
| `source_entity_id` | Plant code (SAP), meter ID (Utility), employee ID (Travel). |
| `is_suspicious` + `suspicious_reasons` | Flag array separate from `review_status`. A record can be suspicious AND approved (analyst verified it). |
| `superseded_by` | Self-referential FK for record correction lineage without a separate history table. |
| `is_locked` | Once locked, `save()` raises an error. Used after export to auditors. |

### Why One Table Instead of Three

Alternative: separate `SAPRecord`, `UtilityRecord`, `TravelRecord` tables.

Problem with three tables: analysts work across sources in a unified dashboard. Auditors
need one output schema. Queries like "show me all Scope 3 records pending review" require
UNION across three tables or a view. The tradeoff — some nullable columns — is worth
the query simplicity.

### `AuditLog`: Append-Only Event Log

Uses `BigAutoField` (sequential integer) rather than UUID as primary key. This gives us
guaranteed ordering by insertion sequence without a secondary sort column. The `id` IS
the ordering.

The log is written by services using the `log_event()` helper, not directly via
`AuditLog.objects.create()`. This enforces consistent structure.

In production: the application DB user should not have UPDATE or DELETE privileges
on the `audit_log` table. We've noted this but can't enforce it in the prototype.

### `SourceMapping`: Configurable Column Mapping

SAP exports vary dramatically by client SAP version and locale. Instead of hardcoding
every variant, we store mappings per tenant. The default mappings live in code; client
overrides live in the database.

This lets a new client onboard without a code deploy: configure their column mappings
in the admin, and the parser will use them.

---

## Scope Categorization

| Source Type | Scope | Category |
|---|---|---|
| SAP fuel combustion | 1 | `STATIONARY_COMBUSTION` |
| SAP mobile fuel (fleet, if applicable) | 1 | `MOBILE_COMBUSTION` |
| Utility electricity | 2 | `PURCHASED_ELECTRICITY` |
| Travel - flights | 3 | `BUSINESS_TRAVEL_AIR` |
| Travel - hotels | 3 | `BUSINESS_TRAVEL_HOTEL` |
| Travel - rail | 3 | `BUSINESS_TRAVEL_RAIL` |
| Travel - ground | 3 | `BUSINESS_TRAVEL_GROUND` |

Scope 2 can be calculated location-based or market-based. We implement location-based
(using a grid emission factor per geography) because market-based requires contractual
instrument tracking (RECs, PPAs) which is out of scope for this prototype.

---

## Unit Normalization

All quantities normalize to:
- **Fuel**: liters (volume) + kWh equivalent (energy)
- **Electricity**: kWh
- **Travel distance**: km
- **Hotel**: nights (dimensionless)

Original unit and quantity are preserved in `original_unit` / `original_quantity`.

Fuel-to-kWh conversion uses lower heating values (LHV) from DEFRA. We store the
converted values because emission factors are typically expressed per unit of energy,
not per unit of volume. This makes factor application consistent across fuel types.

---

## Suspicious Record Detection

Flags are stored in `suspicious_reasons` as a JSON array of `{code, detail}` objects.
This allows filtering by specific flag code in queries.

| Flag Code | Trigger |
|---|---|
| `NEGATIVE_QUANTITY` | Any negative value |
| `ZERO_QUANTITY` | Exactly zero |
| `FUTURE_DATE` | Period in the future |
| `DATE_TOO_OLD` | Before 2015 |
| `DUPLICATE_INVOICE` | Same invoice ref already ingested |
| `STATISTICAL_SPIKE` | >3σ from entity's historical mean (requires ≥6 history points) |
| `BILLING_OVERLAP` | Meter already has a record overlapping this period |
| `IMPLAUSIBLE_FLIGHT_DISTANCE` | <50km or >20,000km |

`is_suspicious` is a denormalized boolean for indexed querying. It is set to `True` if
any flags are raised, regardless of how many.

---

## Audit Trail Strategy

Every state transition is written to `AuditLog`:
- Upload lifecycle: CREATED → PROCESSING → COMPLETE/FAILED/PARTIAL
- Record lifecycle: CREATED → FLAGGED → APPROVED/REJECTED → LOCKED

Each log entry records: actor, action, resource type + ID, payload (contextual detail).

Audit log entries are immutable: `save()` raises `ValueError` if `pk` is already set.

The audit log is queryable by resource (all events for a specific record), by actor
(all actions by a specific user), or by action type across the tenant.

---

## What Would Change for Production

1. **Row-level security**: PostgreSQL RLS policies to enforce tenant isolation at the DB layer
2. **Emission factor table**: Currently hardcoded constants. Should be a `EmissionFactor` model with versioning and effective dates
3. **Full airport database**: Currently ~15 sample airports. Should be the full IATA database (~9,000 airports)
4. **Async ingestion**: Large files should process via Celery. See TRADEOFFS.md.
5. **Schema-per-tenant**: For true data isolation at enterprise scale
6. **Re-normalization pipeline**: A management command to re-derive normalized records when factors update

---

## What I'd Do Differently at Production Scale

### 1. Emission Factor as a first-class model

The current implementation stores emission factors as hardcoded Python constants.
This is sufficient for a prototype but breaks for production in two ways:

- **Annual updates**: DEFRA publishes updated factors every June. A code deployment
  per factor update is unacceptable at enterprise scale.
- **Re-derivation**: When factors change, every approved record whose calculation
  used the old factor needs to be re-derived and re-reviewed. Without a DB table
  with `effective_date`, there's no reliable way to query "which records used
  the pre-June-2024 DEFRA factors."

The production model would be:

```python
class EmissionFactor(models.Model):
    category   = CharField(choices=EmissionCategory.choices)
    sub_type   = CharField()          # fuel type, grid region, cabin class
    value      = DecimalField(...)    # kg CO₂e per unit
    unit       = CharField()          # per liter, per kWh, per km, per night
    source     = CharField()          # "DEFRA 2023", "IPCC AR6"
    effective_from = DateField()
    effective_to   = DateField(null=True)  # null = currently active

    class Meta:
        constraints = [UniqueConstraint(fields=["category","sub_type","effective_from"])]
```

The normalization service would call:
`EmissionFactor.objects.get_active(category, sub_type, record_date)`
instead of the current dict lookup.

### 2. PostgreSQL Row-Level Security

The current multi-tenancy is enforced by `TenantScopedMixin` in every ViewSet.
This is correct application-layer enforcement, but it's one missed queryset
override away from a data leak.

Production would add:

```sql
ALTER TABLE normalized_emission_record ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON normalized_emission_record
  USING (tenant_id = current_setting('app.tenant_id')::uuid);
```

The Django middleware would call `SET app.tenant_id = '...'` at the start of
every request. This makes tenant isolation a database guarantee, not an
application convention.

### 3. Separate `IngestionJob` model for async visibility

Currently, upload processing is synchronous and status is tracked on `SourceUpload`.
For async (Celery) processing, analysts need richer visibility: which step is the
job on, what's the ETA, can they cancel it?

A separate `IngestionJob` model with `step`, `progress_pct`, `started_at`, `eta`
would decouple job execution state from the upload's data provenance. The upload
record remains the permanent data record; the job record is ephemeral and can be
archived after completion.
