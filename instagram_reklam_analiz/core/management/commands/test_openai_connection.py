from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from openai import OpenAI

from core.services.openai_usage import record_openai_token_usage


class Command(BaseCommand):
    help = "OpenAI API anahtari, model erisimi ve kisa uretim testini kontrol eder."

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-generation",
            action="store_true",
            help="Sadece models endpoint'ini test eder, uretim cagrisi yapmaz.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=60,
            help="OpenAI istekleri icin timeout suresi.",
        )

    def handle(self, *args, **options):
        api_key = getattr(settings, "OPENAI_API_KEY", "")
        model = getattr(settings, "OPENAI_MODEL", "gpt-4o")
        if not api_key:
            raise CommandError("OPENAI_API_KEY bos. .env dosyasina anahtari ekleyin.")

        self.stdout.write(f"OpenAI model: {model}")
        self.stdout.write(f"API key: tanimli, uzunluk={len(api_key)}")

        client = OpenAI(api_key=api_key, timeout=options["timeout"], max_retries=2)

        try:
            models = client.models.list()
        except Exception as exc:
            raise CommandError(f"OpenAI models endpoint baglantisi basarisiz: {exc}") from exc

        model_ids = {item.id for item in models.data}
        self.stdout.write(self.style.SUCCESS(f"Models endpoint OK. Model sayisi: {len(model_ids)}"))
        if model in model_ids:
            self.stdout.write(self.style.SUCCESS(f"Secili model erisilebilir: {model}"))
        else:
            self.stdout.write(self.style.WARNING(f"Secili model listede gorunmedi: {model}"))

        if options["skip_generation"]:
            return

        try:
            response = client.responses.create(
                model=model,
                input="Sadece OK yaz.",
                max_output_tokens=16,
            )
        except Exception as exc:
            raise CommandError(f"OpenAI uretim testi basarisiz: {exc}") from exc

        output = (response.output_text or "").strip()
        usage = record_openai_token_usage(response, reference="management.test_openai_connection")
        self.stdout.write(
            self.style.SUCCESS(
                f"Uretim testi OK: {output} "
                f"(input={usage.input_tokens}, output={usage.output_tokens}, total={usage.total_tokens})"
            )
        )
