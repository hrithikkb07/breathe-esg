from rest_framework import serializers
from esg.models import SourceUpload, RawRecord, NormalizedEmissionRecord, AuditLog
from esg.models.tenant import User


class SourceUploadSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SourceUpload
        fields = [
            "id", "source_type", "original_filename", "status",
            "row_count_total", "row_count_success", "row_count_failed",
            "row_count_suspicious", "error_message", "created_at",
            "completed_at", "uploaded_by_name",
        ]
        read_only_fields = fields

    def get_uploaded_by_name(self, obj):
        if obj.uploaded_by:
            return obj.uploaded_by.get_full_name() or obj.uploaded_by.username
        return "System"


class UploadCreateSerializer(serializers.Serializer):
    """
    Used for the upload endpoint — separate from the read serializer
    because the write shape is totally different (file + source_type).
    """
    file = serializers.FileField()
    source_type = serializers.ChoiceField(choices=SourceUpload.SourceType.choices)

    def validate_file(self, value):
        # Reject non-CSV files by content type and extension
        name = value.name.lower()
        if not name.endswith(".csv"):
            raise serializers.ValidationError("Only CSV files are supported.")
        if value.size > 100 * 1024 * 1024:  # 100MB limit
            raise serializers.ValidationError("File exceeds 100MB limit.")
        return value


class NormalizedEmissionRecordListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for list views (dashboard table).
    Omits the full suspicious_reasons detail to keep payload small.
    """
    source_name = serializers.CharField(source="raw_record.upload.original_filename", read_only=True)
    upload_id = serializers.UUIDField(source="raw_record.upload.id", read_only=True)

    class Meta:
        model = NormalizedEmissionRecord
        fields = [
            "id", "scope", "emission_category", "activity_quantity", "activity_unit",
            "co2e_tonnes", "period_start", "period_end",
            "source_entity_id", "source_entity_name",
            "review_status", "is_suspicious", "is_locked",
            "reviewed_at", "source_name", "upload_id",
            "origin_code", "destination_code", "distance_km", "distance_is_estimated",
        ]
        read_only_fields = fields


class NormalizedEmissionRecordDetailSerializer(serializers.ModelSerializer):
    """
    Full serializer for detail view — includes raw record data and full flags.
    """
    raw_data = serializers.JSONField(source="raw_record.raw_data", read_only=True)
    parse_error = serializers.CharField(source="raw_record.parse_error", read_only=True)
    upload_filename = serializers.CharField(source="raw_record.upload.original_filename", read_only=True)
    upload_id = serializers.UUIDField(source="raw_record.upload.id", read_only=True)
    last_reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = NormalizedEmissionRecord
        fields = [
            "id", "scope", "emission_category",
            "activity_quantity", "activity_unit", "original_quantity", "original_unit",
            "emission_factor", "emission_factor_source", "co2e_tonnes",
            "period_start", "period_end",
            "source_entity_id", "source_entity_name",
            "origin_code", "destination_code", "distance_km", "distance_is_estimated",
            "review_status", "is_suspicious", "suspicious_reasons", "is_locked",
            "review_notes", "reviewed_at", "last_reviewed_by_name",
            "created_at", "updated_at",
            "raw_data", "parse_error", "upload_filename", "upload_id",
        ]
        read_only_fields = [f for f in fields if f not in ("review_notes",)]

    def get_last_reviewed_by_name(self, obj):
        if obj.last_reviewed_by:
            return obj.last_reviewed_by.get_full_name() or obj.last_reviewed_by.username
        return None


class ReviewActionSerializer(serializers.Serializer):
    """
    Used for APPROVE and REJECT actions.
    Notes are optional for approval, required for rejection (force analysts to explain).
    """
    action = serializers.ChoiceField(choices=["APPROVE", "REJECT"])
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)

    def validate(self, data):
        if data["action"] == "REJECT" and not data.get("notes", "").strip():
            raise serializers.ValidationError(
                {"notes": "A rejection reason is required."}
            )
        return data


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = [
            "id", "action", "resource_type", "resource_id",
            "payload", "created_at", "actor_name",
        ]
        read_only_fields = fields

    def get_actor_name(self, obj):
        if obj.actor:
            return obj.actor.get_full_name() or obj.actor.username
        return "System"


class FailedRawRecordSerializer(serializers.ModelSerializer):
    """
    Serializer for failed parse rows — used in the upload drill-down endpoint.
    Shows the analyst exactly which rows broke and what the error message says.
    """
    class Meta:
        model = RawRecord
        fields = ["id", "row_number", "raw_data", "parse_error", "created_at"]
        read_only_fields = fields
