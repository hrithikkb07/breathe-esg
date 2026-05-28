# DECISIONS.md

Every ambiguity I resolved, what I chose, why, and what I'd ask the PM.

---

## 1. SAP Format: Flat File (CSV), Not IDoc

**Ambiguity**: SAP can export via IDoc (structured XML/EDI), OData service, BAPI call, or
flat file CSV. The PM said "fuel and procurement data sitting in SAP" — they didn't specify
the interface.

**Decision**: CSV flat file export (SAP transaction MB60 / custom Z-report format).

**Why**: Flat file CSV is the most common real-world mechanism for client data handoffs that
I found through research. SAP IDoc requires an active EDI integration (B2B middleware like
SAP PI/PO or CIG) that most clients don't have configured for third-party handoffs. OData
is modern but requires the client to have activated the appropriate Fiori services and expose
them externally. Flat file exports are universally available in any SAP installation via SE16,
MB60, or custom ABAP reports — the facilities/sustainability lead can pull them independently.

**What I ignored from SAP reality**:
- IDoc parsing (requires EDI handling, out of scope)
- Material master lookups (would need SAP master data API access)
- Multi-leg procurement chains (handling Goods Receipt → Invoice linkage)
- SAP S/4HANA ODATA APIs (too complex for one person in 4 days)

**What I'd ask the PM**:
- "Does the client have an SAP liaison who can configure a scheduled export to SFTP, or will
  the sustainability lead manually export and upload each month?"
- "What SAP module are they running for fuel procurement — MM or PM?"

---

## 2. Utility Data: CSV Portal Export

**Ambiguity**: Utility data can come as PDF bills, portal CSV exports, utility APIs
(Green Button, ISO 15118), or manual meter readings.

**Decision**: CSV portal export (what major utilities like E.ON, MSEDCL, UK Power Networks
provide via their self-service portals).

**Why**: PDF bills require OCR extraction, which is a computer vision problem. Utility APIs
(Green Button) are only available from a small subset of utilities, and uptake is low outside
the US and California specifically. Portal CSV exports are universally available and are the
format that facilities teams actually pull monthly. Real research: E.ON's portal exports
`Service Start Date`, `Service End Date`, `Usage (kWh)`, `Tariff`, `Invoice #` — our schema
maps to this directly.

**What I ignored**:
- Half-hourly or interval data (smart meters) — we use billing-period aggregates
- Reactive power charges, demand charges — relevant for Scope 2 market-based but not for
  location-based as implemented
- PDF bill ingestion

**What I'd ask the PM**:
- "Are all their utility accounts on e-billing with portal access, or will some be paper bills?"
- "Are they calculating Scope 2 market-based (do they have renewable energy certificates)?"

---

## 3. Corporate Travel: Concur-style CSV (not API)

**Ambiguity**: Platforms like Concur, Navan, TravelPerk, and Egencia all expose APIs. They
also let admins bulk-export expense/trip reports as CSV.

**Decision**: CSV export mimicking Concur Travel's expense report export format.

**Why**: Concur's API requires OAuth2 setup and an approved SAP Concur App Center listing
(or a production API key granted by Concur's partner team). Neither is achievable in 4 days.
The CSV export from Concur (Reports > Travel > Download) contains the same fields and is what
sustainability teams actually use today. I researched Concur's export format: columns include
`Employee ID`, `Trip ID`, `Expense Type`, `Travel Date`, `Origin`, `Destination`, `Cabin Class`.
Navan's export is similar with slightly different naming conventions.

**What I ignored**:
- Hotel carbon intensity by property (Concur's Sustainable Travel program data)
- Per-segment flight data (multi-leg itineraries with connection flights)
- Car rental mileage (not in our sample; would be `GROUND` category)
- Train carbon intensity by country (UK rail is much cleaner than ground in China)

**What I'd ask the PM**:
- "Does the client use Concur Travel or a different platform? The column names vary."
- "Do they want per-employee breakdowns, or aggregate company travel?"
- "Are business class flights a meaningful portion of their travel? Cabin class has a 2-3x
  impact on the emission factor."

---

## 4. Ingestion: Synchronous, Not Async

**Decision**: Process uploads synchronously in the request/response cycle.

**Why**: Files we expect to handle (<100MB, <50,000 rows) parse in under 10 seconds on
any reasonable server. Celery adds: a Redis/RabbitMQ broker, a worker process, health
monitoring for the queue, and retry logic. That's 3-4 additional infrastructure components.
For a prototype, the synchronous pattern is correct. The interface is designed so Celery
can be added later without changing the service signature — see TRADEOFFS.md.

---

## 5. Record Correction via Supersession, Not In-Place Update

**Decision**: When an analyst corrects a record, we create a new `NormalizedEmissionRecord`
and link it via `superseded_by`. We never update the original.

**Why**: If we update in-place, we lose the ability to know what the value was before the
correction. Audit logs capture "who changed it and when" but not "what the old value was"
(unless we snapshot it in the payload). Supersession is a cleaner pattern: the original record
is immutable, the new record has full provenance, and the chain is queryable.

**Tradeoff**: Queries for "current" records need to exclude superseded records
(`superseded_by__isnull=True`). This is a filter added to the default queryset — easy to
maintain, easy to explain.

---

## 6. Emission Factors: Hardcoded Constants (for now)

**Decision**: Emission factors are Python constants in the service layer, not a database table.

**Why**: A database-backed emission factor table with versioning, effective dates, and
geographic variance is a 2-week project in itself. For this prototype, constants are
accurate and auditable — they're committed to version control with their source documented.
The database table is the right production approach (see TRADEOFFS.md), and the code is
structured so factors can be replaced with a DB lookup without changing the normalization logic.

---

## 7. Database: PostgreSQL

**Decision**: PostgreSQL.

**Why**: The assignment specifies it. Beyond that: JSONB indexing for raw record queries,
row-level security for multi-tenancy enforcement, and strong transactional guarantees for
audit log writes. SQLite would work for a prototype but PostgreSQL is what this would run
in production.

---

## 8. No Soft Delete

**Decision**: Records are never deleted. They are rejected (analytic status) or locked
(approved). `RawRecord` and `AuditLog` entries have no delete path at all.

**Why**: Deletion would break the provenance chain. If a source upload is deleted, what
happens to all its raw records and normalized records? Auditors need to be able to trace
any approved emission back to its source for 7+ years (typical retention requirement).
The correct model: records are rejected (visible to analysts, excluded from reporting)
rather than deleted.
