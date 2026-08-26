from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Geriye dönük uyumluluk: plan limitlerini yeni canlı paket yapısıyla günceller."

    def handle(self, *args, **options):
        self.stdout.write("update_plan_limits artık create_plans komutuna yönlendiriliyor.")
        call_command("create_plans")
