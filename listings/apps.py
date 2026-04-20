from django.apps import AppConfig


class ListingsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "listings"
    verbose_name = "上場会社情報"

    def ready(self):
        import listings.signals  # noqa: F401
