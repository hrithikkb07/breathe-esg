from django.apps import AppConfig


class EsgConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "esg"

    def ready(self):
        # Import signal handlers here if added in future
        pass
