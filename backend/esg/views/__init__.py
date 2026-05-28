"""
API views.

These are intentionally thin. Business logic lives in services/.
Views handle: HTTP method dispatch, auth, serialization, HTTP response codes.
"""

import hashlib
from django.utils import timezone
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet, ReadOnlyModelViewSet
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from esg.models import SourceUpload, RawRecord, NormalizedEmissionRecord, AuditLog
from esg.models.audit import log_event
from esg.serializers import (
    SourceUploadSerializer,
    UploadCreateSerializer,
    NormalizedEmissionRecordListSerializer,
    NormalizedEmissionRecordDetailSerializer,
    ReviewActionSerializer,
    AuditLogSerializer,
)
from esg.services.ingestion import process_upload


class TenantScopedMixin:
    """
    Mixin that automatically filters all querysets to the current user's tenant.
    Applied to every ViewSet — no tenant data leaks between clients.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.request.user, "tenant") and self.request.user.tenant:
            return qs.filter(tenant=self.request.user.tenant)
        # Superusers see everything (for admin purposes)
        return qs


class SourceUploadViewSet(TenantScopedMixin, ModelViewSet):
    queryset = SourceUpload.objects.select_related("uploaded_by", "source_mapping")
    serializer_class = SourceUploadSerializer
    http_method_names = ["get", "post", "head", "options"]  # No PUT/PATCH/DELETE
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["source_type", "status"]
    ordering_fields = ["created_at", "status"]
    ordering = ["-created_at"]

    def create(self, request, *args, **kwargs):
        """
        Handle file upload. Parse synchronously (see TRADEOFFS.md for async decision).
        """
        serializer = UploadCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        uploaded_file = serializer.validated_data["file"]
        source_type = serializer.validated_data["source_type"]

        # Compute file hash for dedup detection
        file_content = uploaded_file.read()
        file_hash = hashlib.sha256(file_content).hexdigest()
        uploaded_file.seek(0)  # Reset for subsequent read

        with transaction.atomic():
            upload = SourceUpload.objects.create(
                tenant=request.user.tenant,
                uploaded_by=request.user,
                source_type=source_type,
                original_filename=uploaded_file.name,
                file=uploaded_file,
                file_hash=file_hash,
            )
            log_event(
                tenant=request.user.tenant,
                action=AuditLog.Action.UPLOAD_CREATED,
                resource=upload,
                actor=request.user,
                payload={"source_type": source_type, "filename": uploaded_file.name},
            )

        # Process synchronously. See TRADEOFFS.md for why not Celery.
        try:
            upload = process_upload(str(upload.id), actor=request.user)
        except Exception as e:
            upload.status = SourceUpload.Status.FAILED
            upload.error_message = str(e)
            upload.completed_at = timezone.now()
            upload.save(update_fields=["status", "error_message", "completed_at"])

        return Response(
            SourceUploadSerializer(upload).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["get"], url_path="failed-rows")
    def failed_rows(self, request, pk=None):
        """
        Return all RawRecords that failed parsing for a given upload.
        Analysts use this to diagnose which source rows broke and why.
        """
        upload = self.get_object()
        failed = RawRecord.objects.filter(
            upload=upload,
            parse_error__gt="",
        ).filter(normalized__isnull=True).order_by("row_number")
        from esg.serializers import FailedRawRecordSerializer
        return Response(FailedRawRecordSerializer(failed, many=True).data)


class EmissionRecordViewSet(TenantScopedMixin, ModelViewSet):
    queryset = NormalizedEmissionRecord.objects.select_related(
        "raw_record__upload", "last_reviewed_by"
    )
    http_method_names = ["get", "post", "head", "options"]  # No direct PUT/PATCH
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter, filters.SearchFilter]
    filterset_fields = ["scope", "emission_category", "review_status", "is_suspicious", "is_locked"]
    search_fields = ["source_entity_id", "source_entity_name", "origin_code", "destination_code"]
    ordering_fields = ["period_start", "co2e_tonnes", "activity_quantity", "created_at"]
    ordering = ["-period_start"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return NormalizedEmissionRecordDetailSerializer
        return NormalizedEmissionRecordListSerializer

    @action(detail=True, methods=["post"], url_path="review")
    def review(self, request, pk=None):
        """
        APPROVE or REJECT a record. This is the analyst workflow endpoint.

        Approved records become locked once exported (separate endpoint).
        Rejected records remain in the system for audit — never deleted.
        """
        record = self.get_object()

        if record.is_locked:
            return Response(
                {"detail": "This record is locked and cannot be reviewed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = ReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_val = serializer.validated_data["action"]
        notes = serializer.validated_data.get("notes", "")

        new_status = (
            NormalizedEmissionRecord.ReviewStatus.APPROVED
            if action_val == "APPROVE"
            else NormalizedEmissionRecord.ReviewStatus.REJECTED
        )

        audit_action = (
            AuditLog.Action.RECORD_APPROVED
            if action_val == "APPROVE"
            else AuditLog.Action.RECORD_REJECTED
        )

        with transaction.atomic():
            record.review_status = new_status
            record.last_reviewed_by = request.user
            record.reviewed_at = timezone.now()
            record.review_notes = notes
            record.save(update_fields=[
                "review_status", "last_reviewed_by", "reviewed_at", "review_notes", "updated_at"
            ])

            log_event(
                tenant=record.tenant,
                action=audit_action,
                resource=record,
                actor=request.user,
                payload={
                    "previous_status": record.review_status,
                    "new_status": new_status,
                    "notes": notes,
                },
            )

        return Response(NormalizedEmissionRecordDetailSerializer(record).data)

    @action(detail=False, methods=["post"], url_path="bulk-review")
    def bulk_review(self, request):
        """
        Approve or reject multiple records at once.
        Useful for analysts processing large batches of non-suspicious records.
        """
        record_ids = request.data.get("record_ids", [])
        action_val = request.data.get("action")
        notes = request.data.get("notes", "")

        if not record_ids or action_val not in ("APPROVE", "REJECT"):
            return Response(
                {"detail": "Provide record_ids and action (APPROVE/REJECT)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if action_val == "REJECT" and not notes.strip():
            return Response(
                {"detail": "Rejection reason required for bulk reject."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        records = NormalizedEmissionRecord.objects.filter(
            id__in=record_ids,
            tenant=request.user.tenant,
            is_locked=False,
        )

        new_status = (
            NormalizedEmissionRecord.ReviewStatus.APPROVED
            if action_val == "APPROVE"
            else NormalizedEmissionRecord.ReviewStatus.REJECTED
        )

        now = timezone.now()
        with transaction.atomic():
            updated = records.update(
                review_status=new_status,
                last_reviewed_by=request.user,
                reviewed_at=now,
                review_notes=notes,
            )
            for record in records:
                log_event(
                    tenant=record.tenant,
                    action=AuditLog.Action.RECORD_APPROVED if action_val == "APPROVE" else AuditLog.Action.RECORD_REJECTED,
                    resource=record,
                    actor=request.user,
                    payload={"bulk": True, "notes": notes},
                )

        return Response({"updated": updated})


class AuditLogViewSet(TenantScopedMixin, ReadOnlyModelViewSet):
    """Read-only audit log. No creation via API — logs are only written by services."""
    queryset = AuditLog.objects.select_related("actor")
    serializer_class = AuditLogSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["action", "resource_type", "resource_id"]
    ordering = ["-id"]


class DashboardSummaryView(APIView):
    """
    Aggregated summary for the analyst dashboard header.
    Returns counts by scope, status, and recent upload activity.
    """

    def get(self, request):
        tenant = request.user.tenant
        records = NormalizedEmissionRecord.objects.filter(tenant=tenant)

        summary = {
            "total_records": records.count(),
            "pending_review": records.filter(
                review_status=NormalizedEmissionRecord.ReviewStatus.PENDING
            ).count(),
            "flagged_suspicious": records.filter(
                review_status=NormalizedEmissionRecord.ReviewStatus.FLAGGED
            ).count(),
            "approved": records.filter(
                review_status=NormalizedEmissionRecord.ReviewStatus.APPROVED
            ).count(),
            "rejected": records.filter(
                review_status=NormalizedEmissionRecord.ReviewStatus.REJECTED
            ).count(),
            "scope_breakdown": {
                "scope_1": records.filter(scope=1).count(),
                "scope_2": records.filter(scope=2).count(),
                "scope_3": records.filter(scope=3).count(),
            },
            "recent_uploads": SourceUploadSerializer(
                SourceUpload.objects.filter(tenant=tenant).order_by("-created_at")[:5],
                many=True,
            ).data,
        }

        return Response(summary)

