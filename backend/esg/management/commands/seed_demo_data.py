"""
Management command: seed_demo_data

Creates a demo tenant, users, and plant code lookups so the deployed
app has something to log into and explore immediately.

Usage:
    python manage.py seed_demo_data
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from esg.models.tenant import Tenant, User
from esg.models.upload import PlantCodeLookup


PLANT_CODES = [
    {"plant_code": "DE01", "plant_name": "Frankfurt Production Plant", "country": "Germany", "region": "Hessen", "grid_region": "DE"},
    {"plant_code": "DE02", "plant_name": "Munich Logistics Hub", "country": "Germany", "region": "Bavaria", "grid_region": "DE"},
    {"plant_code": "DE03", "plant_name": "Hamburg Distribution Centre", "country": "Germany", "region": "Hamburg", "grid_region": "DE"},
    {"plant_code": "IN_MUM", "plant_name": "Mumbai Office Campus", "country": "India", "region": "Maharashtra", "grid_region": "IN_WEST"},
    {"plant_code": "IN_DEL", "plant_name": "Delhi Operations Centre", "country": "India", "region": "Delhi", "grid_region": "IN_NORTH"},
    {"plant_code": "UK01", "plant_name": "London Head Office", "country": "United Kingdom", "region": "England", "grid_region": "GB"},
]


class Command(BaseCommand):
    help = "Seed demo tenant, users, and plant code lookups"

    @transaction.atomic
    def handle(self, *args, **options):
        # Create tenant
        tenant, created = Tenant.objects.get_or_create(
            slug="acme-corp",
            defaults={"name": "Acme Corporation", "primary_contact_email": "esg@acme.com"},
        )
        self.stdout.write(f"{'Created' if created else 'Found'} tenant: {tenant.name}")

        # Create analyst user
        analyst, created = User.objects.get_or_create(
            username="analyst",
            defaults={
                "email": "analyst@acme.com",
                "first_name": "Alex",
                "last_name": "Chen",
                "tenant": tenant,
                "role": "ANALYST",
            },
        )
        if created:
            analyst.set_password("demo1234")
            analyst.save()
            self.stdout.write("Created analyst user (username: analyst, password: demo1234)")

        # Create admin user
        admin_user, created = User.objects.get_or_create(
            username="admin",
            defaults={
                "email": "admin@acme.com",
                "first_name": "Admin",
                "last_name": "User",
                "tenant": tenant,
                "role": "ADMIN",
                "is_staff": True,
            },
        )
        if created:
            admin_user.set_password("admin1234")
            admin_user.save()
            self.stdout.write("Created admin user (username: admin, password: admin1234)")

        # Create plant code lookups
        for pc in PLANT_CODES:
            obj, created = PlantCodeLookup.objects.get_or_create(
                tenant=tenant,
                plant_code=pc["plant_code"],
                defaults=pc,
            )
            if created:
                self.stdout.write(f"  + Plant code: {pc['plant_code']} → {pc['plant_name']}")

        self.stdout.write(self.style.SUCCESS("\nDemo data seeded successfully."))
        self.stdout.write("Login credentials:")
        self.stdout.write("  analyst / demo1234")
        self.stdout.write("  admin   / admin1234")
