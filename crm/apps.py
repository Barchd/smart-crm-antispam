from django.apps import AppConfig


class CrmConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "crm"

    def ready(self) -> None:
        from config.sqlite_unicode import enable_sqlite_unicode_search

        enable_sqlite_unicode_search()
