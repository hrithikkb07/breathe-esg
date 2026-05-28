from django.db import models
from django.conf import settings


class AuditLog(models.Model):
    """
    Append-only audit trail. Every significant state change is recorded here.

    WHY NOT DJANGO-SIMPLE-HISTORY OR SIMILAR:
    Third-party history packages track model field changes generically.
    That's useful, but we want domain-meaningful audit events (APPROVE, REJECT,
    FLAG) rather than just field diffs. We also want to capture WHO did WHAT
    and WHY in one place. Rolling our own is 40 lines and is fully interview-
    defensible. The tradeoff is we have to remember to log manually — no magic.

    WHY BIGAUTOFIELD FOR PK (not UUID):
    The audit log is an ordered sequence. A BigAutoField gives us guaranteed
    ordering by insertion without a secondary sort. UUIDs would require an
    additional `created_at` index for ordering. For this table, sequence matters
    more than global uniqueness.

    WRITE PATTERN: Always insert, never update or delete.
    The DB user running the app should not have UPDATE/DELETE privileges on this
    table in production. (We don't enforce that here — prototype constraint.)
    """

    class Action(models.TextChoices):
        # Upload lifecycle
        UPLOAD_CREATED = "UPLOAD_CREATED", "Upload Created"
        UPLOAD_PROCESSING = "UPLOAD_PROCESSING", "Upload Processing Started"
        UPLOAD_COMPLETE = "UPLOAD_COMPLETE", "Upload Complete"
        UPLOAD_FAILED = "UPLOAD_FAILED", "Upload Failed"
        # Record lifecycle
        RECORD_CREATED = "RECORD_CREATED", "Record Created"
        RECORD_FLAGGED = "RECORD_FLAGGED", "Record Flagged as Suspicious"
        RECORD_APPROVED = "RECORD_APPROVED", "Record Approved"
        RECORD_REJECTED = "RECORD_REJECTED", "Record Rejected"
        RECORD_LOCKED = "RECORD_LOCKED", "Record Locked for Audit"
        RECORD_SUPERSEDED = "RECORD_SUPERSEDED", "Record Superseded by Correction"
        # Config changes
        MAPPING_UPDATED = "MAPPING_UPDATED", "Source Mapping Updated"
        PLANT_CODE_ADDED = "PLANT_CODE_ADDED", "Plant Code Lookup Added"

    # BigAutoField for ordered sequence
    id = models.BigAutoField(primary_key=True)
    tenant = models.ForeignKey(
        "Tenant", on_delete=models.PROTECT, related_name="audit_logs"
    )
    # actor is null for system-generated events (automated ingestion, background jobs)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_entries",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    # Generic resource references — we use strings so we can log events for
    # any model type without complex GenericForeignKey plumbing.
    resource_type = models.CharField(max_length=64)  # e.g., "NormalizedEmissionRecord"
    resource_id = models.CharField(max_length=64)  # the UUID/ID of the resource
    # The full context of the event. For APPROVE, includes review_notes.
    # For FLAG, includes the suspicious_reasons list. etc.
    payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_log"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["tenant", "-created_at"]),
            models.Index(fields=["resource_type", "resource_id"]),
            models.Index(fields=["actor", "-created_at"]),
        ]

    def save(self, *args, **kwargs):
        # Prevent updates to the audit log
        if self.pk:
            raise ValueError("AuditLog entries are immutable.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"[{self.created_at}] {self.action} on {self.resource_type}:{self.resource_id}"


def log_event(*, tenant, action, resource, actor=None, payload=None):
    """
    Helper to create an audit log entry. Use this everywhere instead of
    AuditLog.objects.create() directly — it enforces consistent structure.

    Usage:
        log_event(
            tenant=record.tenant,
            action=AuditLog.Action.RECORD_APPROVED,
            resource=record,
            actor=request.user,
            payload={"notes": "Verified against plant meter readings"},
        )
    """
    AuditLog.objects.create(
        tenant=tenant,
        actor=actor,
        action=action,
        resource_type=type(resource).__name__,
        resource_id=str(resource.pk),
        payload=payload or {},
    )
