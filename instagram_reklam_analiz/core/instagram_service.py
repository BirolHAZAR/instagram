# core/instagram_service.py

from .instagram_api import InstagramAPI
from .models import InstagramAccount, InstagramMedia, InstagramInsight
from django.utils import timezone
from datetime import datetime

class InstagramService:
    def __init__(self, access_token=None):
        self.api = InstagramAPI(access_token)
    
    def verify_account(self, username, access_token):
        """Hesabı doğrula ve bilgilerini al"""
        api = InstagramAPI(access_token)
        user_info = api.get_user_info()
        
        if 'error' in user_info:
            return {'success': False, 'error': user_info.get('error', {}).get('message', 'Geçersiz token')}
        
        return {
            'success': True,
            'data': {
                'id': user_info.get('id'),
                'username': user_info.get('username'),
                'account_type': user_info.get('account_type', 'personal'),
                'media_count': user_info.get('media_count', 0)
            }
        }
    
    def sync_user_data(self, instagram_account_id):
        """Instagram hesabı verilerini senkronize et"""
        try:
            account = InstagramAccount.objects.get(id=instagram_account_id)
            user_info = self.api.get_user_info()
            
            if 'error' not in user_info:
                account.username = user_info.get('username', account.username)
                account.instagram_id = user_info.get('id')
                account.media_count = user_info.get('media_count', 0)
                account.account_type = user_info.get('account_type', 'personal')
                account.last_sync = timezone.now()
                account.save()
                return account
            return None
        except Exception as e:
            print(f"Senkronizasyon hatası: {str(e)}")
            return None
    
    def sync_media_data(self, instagram_account_id):
        """Medya verilerini senkronize et"""
        try:
            account = InstagramAccount.objects.get(id=instagram_account_id)
            media_data = self.api.get_user_media(limit=50)
            
            if 'error' in media_data:
                return []
            
            saved_media = []
            if 'data' in media_data:
                for media in media_data['data']:
                    media_obj, created = InstagramMedia.objects.update_or_create(
                        instagram_account=account,
                        media_id=media.get('id'),
                        defaults={
                            'media_type': media.get('media_type', 'image'),
                            'caption': media.get('caption', ''),
                            'media_url': media.get('media_url', ''),
                            'permalink': media.get('permalink', ''),
                            'timestamp': media.get('timestamp', timezone.now()),
                            'like_count': media.get('like_count', 0),
                            'comments_count': media.get('comments_count', 0),
                        }
                    )
                    saved_media.append(media_obj)
            
            account.last_sync = timezone.now()
            account.save()
            return saved_media
        except Exception as e:
            print(f"Medya senkronizasyon hatası: {str(e)}")
            return []
    
    def analyze_engagement(self, username):
        """Belirli bir kullanıcının etkileşim analizi"""
        try:
            media_data = self.api.get_user_media(limit=30)
            
            if 'error' in media_data:
                return {'error': 'Veri alınamadı'}
            
            total_likes = 0
            total_comments = 0
            media_count = 0
            
            if 'data' in media_data:
                for media in media_data['data']:
                    total_likes += media.get('like_count', 0)
                    total_comments += media.get('comments_count', 0)
                    media_count += 1
            
            if media_count > 0:
                avg_likes = total_likes / media_count
                avg_comments = total_comments / media_count
                avg_engagement = (total_likes + total_comments) / media_count
                
                if avg_engagement > 100:
                    performance = "Mükemmel"
                elif avg_engagement > 50:
                    performance = "İyi"
                elif avg_engagement > 20:
                    performance = "Orta"
                else:
                    performance = "Geliştirilmeli"
                
                return {
                    'username': username,
                    'total_posts': media_count,
                    'total_likes': total_likes,
                    'total_comments': total_comments,
                    'avg_likes': round(avg_likes, 2),
                    'avg_comments': round(avg_comments, 2),
                    'avg_engagement': round(avg_engagement, 2),
                    'performance': performance,
                    'recommendations': self._generate_recommendations(avg_engagement)
                }
            
            return {'error': 'Medya bulunamadı'}
        except Exception as e:
            return {'error': str(e)}
    
    def _generate_recommendations(self, engagement_score):
        """Etkileşim skoruna göre öneriler üret"""
        recommendations = []
        
        if engagement_score < 20:
            recommendations.append("📸 Daha kaliteli görseller kullanın")
            recommendations.append("⏰ Paylaşım saatlerinizi optimize edin")
            recommendations.append("#️⃣ Popüler hashtag'ler kullanın")
            recommendations.append("💬 Takipçilerinizle daha fazla etkileşime geçin")
        elif engagement_score < 50:
            recommendations.append("🎥 Video içeriklerinizi artırın")
            recommendations.append("📊 Hikaye paylaşımlarınızı çoğaltın")
            recommendations.append("🎯 Hedef kitlenizi belirleyin")
        else:
            recommendations.append("🚀 Reklam bütçenizi artırabilirsiniz")
            recommendations.append("🤝 İşbirlikleri yapın")
            recommendations.append("✨ İçerik takviminize sadık kalın")
        
        return recommendations