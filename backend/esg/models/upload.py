import uuid
import hashlib
from django.db import models
from django.conf import settings


class SourceUpload(models.Model):
    """
    Represents a single file ingestion event. This is the top of the provenance chain.
    Every RawRecord traces back to exactly one SourceUpload.

    We store the file hash to detect re-uploads of identical files —
    a common footgun when facilities teams re-export the same billing period.
    """

    class SourceType(models.TextChoices):
        SAP = "SAP", "SAP Fuel/Procurement"
        UTILITY = "UTILITY", "Utility Electricity"
        TRAVEL = "TRAVEL", "Corporate Travel"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PROCESSING = "PROCESSING", "Processing"
        PARTIAL = "PARTIAL", "Partial (some rows failed)"
        COMPLETE = "COMPLETE", "Complete"
        FAILED = "FAILED", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "Tenant", on_delete=models.PROTECT, related_name="uploads"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploads",
        null=True,  # null if ingested via automation
    )
    source_type = models.CharField(max_length=16, choices=SourceType.choices)
    # Store the original filename for analyst UX — they need to know which file this was
    original_filename = models.CharField(max_length=512)
    file = models.FileField(upload_to="uploads/%Y/%m/")
    # SHA-256 hash of the file contents.
    # Used to: (a) detect exact re-uploads, (b) provide tamper evidence for audit.
    file_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    # Populated after parsing completes
    row_count_total = models.IntegerField(null=True, blank=True)
    row_count_success = models.IntegerField(null=True, blank=True)
    row_count_failed = models.IntegerField(null=True, blank=True)
    row_count_suspicious = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)  # top-level error if FAILED
    # Which source mapping config was used (if any tenant-specific override exists)
    source_mapping = models.ForeignKey(
        "SourceMapping",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploads",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "source_upload"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "source_type", "-created_at"]),
            models.Index(fields=["file_hash"]),
        ]

    def __str__(self):
        return f"{self.source_type}: {self.original_filename} ({self.status})"


class SourceMapping(models.Model):
    """
    Configurable per-tenant column mappings for each source type.

    Problem this solves: SAP exports differ by SAP version, client configuration,
    and locale. One client exports 'Werk', another exports 'Plant', another 'Plant Code'.
    Rather than hardcoding every variant, we store the mapping and let it be
    overridden per tenant.

    The `column_mappings` JSON maps source column name → our canonical field name.
    The `unit_mappings` JSON maps source unit string → our canonical unit string.

    Example column_mappings:
      {"Buchungsdatum": "date", "Werk": "plant_code", "Menge": "quantity", "Einheit": "unit"}

    Example unit_mappings:
      {"Liter": "L", "Kubikmeter": "m3", "kWh": "kWh", "MWh": "MWh"}
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "Tenant", on_delete=models.PROTECT, related_name="source_mappings"
    )
    source_type = models.CharField(
        max_length=16, choices=SourceUpload.SourceType.choices
    )
    # Optional variant tag — e.g., "SAP_DE" for German headers, "CONCUR_V2" for a schema version
    variant_tag = models.CharField(max_length=64, blank=True)
    column_mappings = models.JSONField(default=dict)
    unit_mappings = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "source_mapping"
        # Only one active mapping per (tenant, source_type, variant)
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "source_type", "variant_tag"],
                condition=models.Q(is_active=True),
                name="unique_active_mapping_per_source",
            )
        ]


class PlantCodeLookup(models.Model):
    """
    Translates SAP plant codes (e.g., 'DE01', 'IN_MUM') to human-readable metadata.

    In production this would sync from the client's SAP master data (MM60 / plant master).
    Here we keep it as a manually-maintained lookup table per tenant.
    The lookup is tenant-scoped because plant codes are meaningless across clients.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        "Tenant", on_delete=models.PROTECT, related_name="plant_codes"
    )
    plant_code = models.CharField(max_length=32)
    plant_name = models.CharField(max_length=255)
    country = models.CharField(max_length=64, blank=True)
    region = models.CharField(max_length=128, blank=True)
    # Useful for Scope 2 market-based calculations — grid emissions differ by geography
    grid_region = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "plant_code_lookup"
        unique_together = [("tenant", "plant_code")]

    def __str__(self):
        return f"{self.plant_code} → {self.plant_name}"
