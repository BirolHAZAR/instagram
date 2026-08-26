from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Yeni TOKEN_ENCRYPTION_KEY üretir. Bu değeri .env içine ekleyin."

    def handle(self, *args, **options):
        key = Fernet.generate_key().decode("utf-8")
        self.stdout.write("TOKEN_ENCRYPTION_KEY=" + key)
