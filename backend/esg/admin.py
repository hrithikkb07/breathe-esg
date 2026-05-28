from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from esg.models import SourceUpload, SourceMapping, PlantCodeLookup, RawRecord, NormalizedEmissionRecord, AuditLog
from esg.models.tenant import Tenant, User


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "is_active", "created_at"]
    search_fields = ["name", "slug"]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ["username", "email", "tenant", "role", "is_active"]
    list_filter = ["role", "is_active", "tenant"]
    fieldsets = BaseUserAdmin.fieldsets + (
        ("ESG", {"fields": ("tenant", "role")}),
    )


@admin.register(SourceUpload)
class SourceUploadAdmin(admin.ModelAdmin):
    list_display = ["original_filename", "source_type", "status", "tenant", "created_at"]
    list_filter = ["source_type", "status", "tenant"]
    readonly_fields = ["file_hash", "created_at", "completed_at"]


@admin.register(PlantCodeLookup)
class PlantCodeLookupAdmin(admin.ModelAdmin):
    list_display = ["plant_code", "plant_name", "country", "tenant"]
    list_filter = ["tenant", "country"]
    search_fields = ["plant_code", "plant_name"]


@admin.register(NormalizedEmissionRecord)
class NormalizedEmissionRecordAdmin(admin.ModelAdmin):
    list_display = ["scope", "emission_category", "period_start", "review_status", "is_suspicious", "is_locked", "tenant"]
    list_filter = ["scope", "review_status", "is_suspicious", "is_locked", "tenant"]
    readonly_fields = ["created_at", "updated_at", "raw_record"]


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["id", "action", "resource_type", "resource_id", "actor", "created_at"]
    list_filter = ["action", "resource_type"]
    readonly_fields = ["id", "tenant", "actor", "action", "resource_type", "resource_id", "payload", "created_at"]  # everything read-only

    def has_add_permission(self, request):
        return False  # Audit log entries are never manually created

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False  # Audit log is never deleted


@admin.register(SourceMapping)
class SourceMappingAdmin(admin.ModelAdmin):
    list_display = ["source_type", "variant_tag", "tenant", "is_active", "created_at"]
    list_filter = ["source_type", "tenant", "is_active"]
