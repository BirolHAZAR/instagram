from django.core.management.base import BaseCommand
from core.models.platform import Platform

class Command(BaseCommand):
    help = 'Varsayılan platformları oluşturur'

    def handle(self, *args, **options):
        platforms = [
            {'name': 'Instagram', 'code': 'instagram', 'icon': 'fab fa-instagram'},
            {'name': 'Facebook', 'code': 'facebook', 'icon': 'fab fa-facebook'},
            {'name': 'Google Ads', 'code': 'google_ads', 'icon': 'fab fa-google'},
            {'name': 'Google Analytics 4', 'code': 'google_analytics', 'icon': 'fas fa-chart-pie'},
            {'name': 'TikTok', 'code': 'tiktok', 'icon': 'fab fa-tiktok'},
            {'name': 'LinkedIn', 'code': 'linkedin', 'icon': 'fab fa-linkedin'},
            {'name': 'X', 'code': 'x', 'icon': 'fab fa-x-twitter'},
            {'name': 'YouTube', 'code': 'youtube', 'icon': 'fab fa-youtube'},
        ]
        
        for platform_data in platforms:
            obj, created = Platform.objects.get_or_create(
                code=platform_data['code'],
                defaults=platform_data
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Platform oluşturuldu: {obj.name}"))
            else:
                self.stdout.write(f"Platform zaten var: {obj.name}")
        
        self.stdout.write(self.style.SUCCESS("Platformlar başarıyla eklendi."))
