import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


class RawRecord(models.Model):
    """
    Immutable mirror of a single CSV row, exactly as received.

    WHY STORE THE RAW DATA: Normalization logic will change. Emission factors get
    updated. Bugs get fixed. If we only store normalized records, we lose the ability
    to re-derive when any of those change. The raw record is our source-of-truth.

    WHY JSONFIELD: Each source type has a completely different schema. Forcing them
    into typed columns would require either a massive sparse table or multiple tables
    with complex joins. JSONField gives us schema flexibility with Postgres's JSONB
    indexing capability when we need it.

    This record is NEVER updated after creation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    upload = models.ForeignKey(
        "SourceUpload", on_delete=models.PROTECT, related_name="raw_records"
    )
    # Row number in the source file, 1-indexed. Needed to trace back to the exact
    # line in the original export for dispute resolution.
    row_number = models.IntegerField()
    # The raw parsed row data, exactly as read from CSV (before any normalization)
    raw_data = models.JSONField()
    # If parsing this row failed, we still store the record with the error.
    # This gives analysts visibility into what broke without blocking the whole upload.
    parse_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "raw_record"
        unique_together = [("upload", "row_number")]
        indexes = [
            models.Index(fields=["upload", "row_number"]),
        ]

    def save(self, *args, **kwargs):
        # Enforce immutability: raw records are never updated
        if self.pk and self.__class__.objects.filter(pk=self.pk).exists():
            raise ValidationError("RawRecord is immutable and cannot be updated.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Row {self.row_number} of {self.upload.original_filename}"


class NormalizedEmissionRecord(models.Model):
    """
    The unified emissions schema. All three sources are normalized into this shape.

    Design goals:
    1. Single schema regardless of source (SAP / Utility / Travel)
    2. Full provenance: every record traces to a specific raw row in a specific file
    3. Immutability once approved: approved records become locked
    4. Auditability: who reviewed, when, with what notes
    5. Scope categorization: Scope 1 / 2 / 3 per GHG Protocol

    WHY NOT SEPARATE TABLES PER SOURCE: Analysts work across sources in a unified
    view. Auditors need one schema. Having separate tables for each source would
    require either complex UNIONs or a lot of app-layer logic to reconstruct the
    full picture. The tradeoff is some nullable fields — acceptable here.
    """

    class Scope(models.IntegerChoices):
        SCOPE_1 = 1, "Scope 1 - Direct"
        SCOPE_2 = 2, "Scope 2 - Purchased Energy"
        SCOPE_3 = 3, "Scope 3 - Value Chain"

    class EmissionCategory(models.TextChoices):
        # Scope 1
        STATIONARY_COMBUSTION = "STATIONARY_COMBUSTION", "Stationary Combustion"
        MOBILE_COMBUSTION = "MOBILE_COMBUSTION", "Mobile Combustion"
        # Scope 2
        PURCHASED_ELECTRICITY = "PURCHASED_ELECTRICITY", "Purchased Electricity"
        # Scope 3
        BUSINESS_TRAVEL_AIR = "BUSINESS_TRAVEL_AIR", "Business Travel - Air"
        BUSINESS_TRAVEL_RAIL = "BUSINESS_TRAVEL_RAIL", "Business Travel - Rail"
        BUSINESS_TRAVEL_HOTEL = "BUSINESS_TRAVEL_HOTEL", "Business Travel - Hotel"
        BUSINESS_TRAVEL_GROUND = "BUSINESS_TRAVEL_GROUND", "Business Travel - Ground"

    class ActivityUnit(models.TextChoices):
        # Energy
        KWH = "kWh", "Kilowatt-hours"
        MWH = "MWh", "Megawatt-hours"
        # Fuel volume
        LITERS = "L", "Liters"
        CUBIC_METERS = "m3", "Cubic Meters"
        # Travel
        KM = "km", "Kilometers"
        PASSENGER_KM = "pkm", "Passenger-kilometers"
        NIGHTS = "nights", "Nights (hotel)"

    class ReviewStatus(models.TextChoices):
        PENDING = "PENDING", "Pending Review"
        FLAGGED = "FLAGGED", "Flagged - Suspicious"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "Tenant", on_delete=models.PROTECT, related_name="emission_records"
    )
    # Full provenance chain: this record → raw row → source upload → file
    raw_record = models.OneToOneField(
        "RawRecord",
        on_delete=models.PROTECT,
        related_name="normalized",
        # OneToOne because one raw row produces exactly one normalized record.
        # If a row produces multiple emission events (rare edge case), we'd
        # reconsider, but for now this constraint improves data integrity.
    )

    # ── Scope & Category ────────────────────────────────────────────────────
    scope = models.IntegerField(choices=Scope.choices)
    emission_category = models.CharField(
        max_length=64, choices=EmissionCategory.choices
    )

    # ── Activity Data (normalized) ───────────────────────────────────────────
    # Quantity of the activity (fuel burned, electricity consumed, distance traveled)
    # All values are normalized to the canonical unit below.
    activity_quantity = models.DecimalField(max_digits=18, decimal_places=6)
    activity_unit = models.CharField(max_length=16, choices=ActivityUnit.choices)
    # Original value before normalization — keep for audit and re-derivation
    original_quantity = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True
    )
    original_unit = models.CharField(max_length=32, blank=True)

    # ── Emission Calculation ─────────────────────────────────────────────────
    # We store the factor and source so that when factors are updated,
    # we can identify which records need recalculation.
    emission_factor = models.DecimalField(
        max_digits=18, decimal_places=8, null=True, blank=True
    )  # kg CO2e per activity unit
    emission_factor_source = models.CharField(
        max_length=128, blank=True
    )  # e.g., "IPCC AR6", "DEFRA 2023"
    co2e_tonnes = models.DecimalField(
        max_digits=18, decimal_places=6, null=True, blank=True
    )

    # ── Period ───────────────────────────────────────────────────────────────
    # Billing periods don't align with calendar months (utility data).
    # We store both the raw billing period and a canonical reporting period.
    period_start = models.DateField()
    period_end = models.DateField()

    # ── Source Entity ────────────────────────────────────────────────────────
    # The originating entity: plant code for SAP, meter ID for utility,
    # employee/trip ID for travel. Denormalized here for query performance.
    source_entity_id = models.CharField(max_length=128, blank=True)
    source_entity_name = models.CharField(max_length=255, blank=True)
    # For travel: origin and destination
    origin_code = models.CharField(max_length=8, blank=True)  # airport/city code
    destination_code = models.CharField(max_length=8, blank=True)
    # For travel: was distance calculated (estimated) or provided?
    distance_km = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True
    )
    distance_is_estimated = models.BooleanField(default=False)

    # ── Review Workflow ──────────────────────────────────────────────────────
    review_status = models.CharField(
        max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    # is_locked is set when a record is approved and exported.
    # Once locked, NO field may be modified — enforced in save() and serializers.
    is_locked = models.BooleanField(default=False)

    # ── Suspicious Record Flags ──────────────────────────────────────────────
    # We keep flags separate from review_status so an analyst can approve a record
    # they've investigated, while keeping the flag visible for audit trail purposes.
    is_suspicious = models.BooleanField(default=False, db_index=True)
    # List of flag codes + human-readable reasons
    # e.g., [{"code": "NEGATIVE_QUANTITY", "detail": "quantity=-5.2 kWh"}]
    suspicious_reasons = models.JSONField(default=list)

    # ── Provenance & Audit Fields ────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_records",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    # ── Record Lineage ───────────────────────────────────────────────────────
    # If an analyst corrects a record (e.g., wrong unit assigned), we don't update
    # in-place. We create a new NormalizedEmissionRecord and link it here.
    # This preserves the full edit history without a separate versioning table.
    superseded_by = models.OneToOneField(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supersedes",
    )

    class Meta:
        db_table = "normalized_emission_record"
        ordering = ["-period_start"]
        indexes = [
            models.Index(fields=["tenant", "scope", "review_status"]),
            models.Index(fields=["tenant", "emission_category", "-period_start"]),
            models.Index(fields=["is_suspicious", "review_status"]),
            models.Index(fields=["is_locked"]),
        ]

    def save(self, *args, **kwargs):
        if self.is_locked and self.pk:
            # Fetch original to compare
            original = NormalizedEmissionRecord.objects.filter(pk=self.pk).first()
            if original and original.is_locked:
                raise ValidationError(
                    f"Record {self.pk} is locked and cannot be modified. "
                    "Create a new record linked via superseded_by."
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"Scope {self.scope} | {self.emission_category} | "
            f"{self.period_start} → {self.period_end} | {self.review_status}"
        )
