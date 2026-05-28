from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from esg.auth import ESGTokenObtainPairView as TokenObtainPairView

from esg.views import (
    SourceUploadViewSet,
    EmissionRecordViewSet,
    AuditLogViewSet,
    DashboardSummaryView,
)

router = DefaultRouter()
router.register(r"uploads", SourceUploadViewSet, basename="upload")
router.register(r"records", EmissionRecordViewSet, basename="record")
router.register(r"audit-log", AuditLogViewSet, basename="auditlog")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/auth/token/", TokenObtainPairView.as_view(), name="token_obtain"),
    path("api/auth/token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("api/dashboard/summary/", DashboardSummaryView.as_view(), name="dashboard-summary"),
    path("api/", include(router.urls)),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
