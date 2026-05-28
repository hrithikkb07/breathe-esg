import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser


class Tenant(models.Model):
    """
    Row-level multi-tenancy. Every data record carries a tenant FK.
    We chose row-level (vs schema-per-tenant) because it keeps migrations
    simple and this is a prototype. In production, schema-per-tenant or
    separate DB per tenant would be more appropriate for true data isolation.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)
    # contact info for the enterprise client
    primary_contact_email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenant"

    def __str__(self):
        return self.name


class User(AbstractUser):
    """
    Extends Django's User to add tenant membership.
    A user belongs to exactly one tenant in this prototype.
    In production, you'd want a many-to-many for consultants who span clients.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.PROTECT,  # PROTECT, not CASCADE — don't nuke users on tenant delete
        related_name="users",
        null=True,
        blank=True,  # null for superusers who span tenants
    )
    role = models.CharField(
        max_length=32,
        choices=[
            ("ANALYST", "Analyst"),
            ("ADMIN", "Admin"),
            ("AUDITOR", "Auditor"),  # read-only, post-approval
        ],
        default="ANALYST",
    )

    class Meta:
        db_table = "auth_user"
