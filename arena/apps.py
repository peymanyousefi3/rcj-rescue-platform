from django.apps import AppConfig

class ArenaConfig(AppConfig):
    name = 'arena'
    def ready(self):
        from . import signals  # noqa: F401
