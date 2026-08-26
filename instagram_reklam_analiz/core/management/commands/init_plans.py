from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Geriye dönük uyumluluk: canlı paket yapısını create_plans ile kurar."

    def handle(self, *args, **options):
        self.stdout.write("init_plans artık create_plans komutuna yönlendiriliyor.")
        call_command("create_plans")
