from django.apps import AppConfig


class ReservasConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = "reservas"
    
    # Activar signals
    def ready(self):
        import reservas.signals
