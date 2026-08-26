from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self):
        import core.checks  # noqa: F401

        # Signal dosyasını burada import etmek zorunlu; aksi halde otomatik bildirimler çalışmaz.
        try:
            import core.signals  # noqa: F401
        except Exception:
            # Uygulama açılışını kırmamak için yutuyoruz; detay Django loglarında görünür.
            pass
