from django.apps import AppConfig


class BomConfig(AppConfig):
    name = 'bom'

    def ready(self):
        import bom.signals  # noqa: F401
