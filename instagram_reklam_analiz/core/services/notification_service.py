
# core/services/notification_service.py
"""
Çok Kanallı Bildirim Servisi
Email, Dashboard Bildirimi, SMS (gelecek) desteği
"""
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
import logging

logger = logging.getLogger(__name__)


class NotificationService:
    """Bildirim gönderme servisi"""
    
    @staticmethod
    def send_email_alert(user, alerts):
        """Email ile alarm bildirimi gönder"""
        
        if not user.email:
            return False
        
        critical_alerts = [a for a in alerts if a['level'] == 'critical']
        warning_alerts = [a for a in alerts if a['level'] == 'warning']
        
        subject_parts = []
        if critical_alerts:
            subject_parts.append(f'🔴 {len(critical_alerts)} Kritik')
        if warning_alerts:
            subject_parts.append(f'🟡 {len(warning_alerts)} Uyarı')
        
        if not subject_parts:
            return False
        
        subject = f"ReklamAI Alarm: {' | '.join(subject_parts)}"
        
        html_message = render_to_string('emails/alert_notification.html', {
            'user': user,
            'alerts': alerts,
            'critical_alerts': critical_alerts,
            'warning_alerts': warning_alerts,
        })
        
        plain_message = strip_tags(html_message)
        
        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=True,
            )
            logger.info(f"Email alert gönderildi: {user.email}")
            return True
        except Exception as e:
            logger.error(f"Email alert hatası: {str(e)}")
            return False
    
    @staticmethod
    def send_weekly_digest(user, weekly_stats):
        """Haftalık özet email'i gönder"""
        
        subject = f"📊 ReklamAI Haftalık Özet - {weekly_stats.get('week_start', '')} / {weekly_stats.get('week_end', '')}"
        
        html_message = render_to_string('emails/weekly_digest.html', {
            'user': user,
            'stats': weekly_stats,
        })
        
        try:
            send_mail(
                subject=subject,
                message=strip_tags(html_message),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=True,
            )
            return True
        except Exception as e:
            logger.error(f"Weekly digest hatası: {str(e)}")
            return False
    
    @staticmethod
    def send_report_ready(user, report_url):
        """Rapor hazır bildirimi gönder"""
        
        subject = "📄 ReklamAI - Raporunuz Hazır!"
        
        html_message = render_to_string('emails/report_ready.html', {
            'user': user,
            'report_url': report_url,
        })
        
        try:
            send_mail(
                subject=subject,
                message=strip_tags(html_message),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=True,
            )
            return True
        except Exception as e:
            logger.error(f"Report ready hatası: {str(e)}")
            return False