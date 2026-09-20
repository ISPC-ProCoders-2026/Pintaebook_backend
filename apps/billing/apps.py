from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.billing'
    verbose_name = 'Facturación y Créditos'

    def ready(self):
        # Al importar signals aca, garantizamos que el decorador @receiver
        # se registre en el dispatcher de señales de Django al iniciar la aplicación.
        import apps.billing.signals  # noqa: F401
        