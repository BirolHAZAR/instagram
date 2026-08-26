from django.core.management.base import BaseCommand

from core.services.social_auth_config import provider_rows, sync_social_apps_from_env


class Command(BaseCommand):
    help = "Env degiskenlerinden allauth SocialApp kayitlarini olusturur/gunceller."

    def handle(self, *args, **options):
        results = sync_social_apps_from_env(stdout=self.stdout)
        skipped = [provider for provider, status in results if status == "skipped"]
        if skipped:
            self.stdout.write("")
            self.stdout.write(self.style.WARNING("Eksik env nedeniyle atlanan providerlar: " + ", ".join(skipped)))
            self.stdout.write("Beklenen env alanlari:")
            for row in provider_rows():
                self.stdout.write(f"- {row['name']}: {row['env_client_id']} / {row['env_secret']}")
        self.stdout.write(self.style.SUCCESS("Sosyal giris ayarlari kontrol edildi."))
