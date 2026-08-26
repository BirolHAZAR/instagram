# core/ai_agents/recommendation_engine.py
"""
AI Destekli Öneri Motoru
Instagram reklam kampanyaları için akıllı öneriler üretir
"""

import json
import random
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from core.services.openai_usage import record_openai_token_usage

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class RecommendationEngine:
    """
    AI destekli öneri motoru
    Kampanya performansına göre akıllı öneriler üretir
    """
    
    def __init__(self, api_key=None, user=None, organization=None):
        self.user = user
        self.organization = organization
        """Öneri motorunu başlat"""
        self.api_key = api_key or getattr(settings, 'OPENAI_API_KEY', None)
        self.use_openai = OPENAI_AVAILABLE and self.api_key
        self.client = OpenAI(api_key=self.api_key, timeout=60, max_retries=2) if self.use_openai else None
    
    def generate_recommendations(self, campaign, performance_data):
        """
        Kampanya için öneriler üret
        
        Args:
            campaign: Kampanya nesnesi
            performance_data: Performans analiz verileri
        
        Returns:
            list: Öneri listesi
        """
        recommendations = []
        
        # Performans skoruna göre öneriler
        score = performance_data.get('performance_score', 50)
        
        # Hedefleme önerileri
        recommendations.extend(self._get_targeting_recommendations(campaign, score))
        
        # Kreatif öneriler
        recommendations.extend(self._get_creative_recommendations(campaign, score))
        
        # Bütçe önerileri
        recommendations.extend(self._get_budget_recommendations(campaign, score))
        
        # Zamanlama önerileri
        recommendations.extend(self._get_timing_recommendations(campaign, score))
        
        # İçerik önerileri
        recommendations.extend(self._get_content_recommendations(campaign, score))
        
        # Platform önerileri
        recommendations.extend(self._get_platform_recommendations(campaign, score))
        
        # AI destekli özel öneriler
        if self.use_openai:
            ai_recommendations = self._get_ai_recommendations(campaign, performance_data)
            if ai_recommendations:
                recommendations.extend(ai_recommendations)
        
        # Önerileri önceliğe göre sırala
        recommendations.sort(key=lambda x: self._get_priority_weight(x.get('priority', 'medium')))
        
        return recommendations[:10]  # En iyi 10 öneriyi döndür
    
    def generate_quick_wins(self, campaign, performance_data):
        """
        Hızlı kazanç önerileri (hemen uygulanabilir)
        
        Args:
            campaign: Kampanya nesnesi
            performance_data: Performans analiz verileri
        
        Returns:
            list: Hızlı kazanç önerileri
        """
        quick_wins = []
        
        # Düşük asılı meyveler
        if performance_data.get('weaknesses'):
            quick_wins.append({
                'title': 'Reklam Metnini Güçlendirin',
                'description': 'Mevcut metni daha dikkat çekici hale getirin, harekete geçirici ifadeler ekleyin.',
                'estimated_time': '15 dakika',
                'expected_impact': 'Orta'
            })
        
        # Hashtag optimizasyonu
        quick_wins.append({
            'title': 'Hashtag Optimizasyonu',
            'description': 'Popüler ve niş hashtag\'leri birlikte kullanın. 5-10 arası hashtag önerilir.',
            'estimated_time': '10 dakika',
            'expected_impact': 'Düşük-Orta'
        })
        
        # Görsel güncelleme
        if campaign.ad_type == 'image':
            quick_wins.append({
                'title': 'Görsel Kontrastını Artırın',
                'description': 'Daha canlı renkler ve yüksek kontrast kullanarak dikkat çekiciliği artırın.',
                'estimated_time': '30 dakika',
                'expected_impact': 'Orta'
            })
        
        # CTA butonu iyileştirmesi
        quick_wins.append({
            'title': 'CTA Butonunu İyileştirin',
            'description': '"Daha Fazla Bilgi" yerine "Hemen Keşfet", "Şimdi Al" gibi ifadeler kullanın.',
            'estimated_time': '5 dakika',
            'expected_impact': 'Düşük'
        })
        
        return quick_wins[:3]
    
    def generate_seasonal_recommendations(self, campaign):
        """
        Mevsimsel öneriler üret
        
        Args:
            campaign: Kampanya nesnesi
        
        Returns:
            list: Mevsimsel öneriler
        """
        now = timezone.now()
        month = now.month
        recommendations = []
        
        # Mevsimsel fırsatlar
        if month in [11, 12]:
            recommendations.append({
                'title': 'Yılbaşı Fırsatlarını Değerlendirin',
                'description': 'Yılbaşı temalı içerikler ve indirimlerle dönüşümleri artırın.',
                'season': 'Kış',
                'urgency': 'Yüksek'
            })
        elif month in [3, 4, 5]:
            recommendations.append({
                'title': 'Bahar İndirim Kampanyası',
                'description': 'Bahar temalı görseller ve "Yenilenme" teması kullanın.',
                'season': 'Bahar',
                'urgency': 'Orta'
            })
        elif month in [6, 7, 8]:
            recommendations.append({
                'title': 'Yaz Kampanyası Fırsatı',
                'description': 'Yaz indirimleri ve tatil temalı içeriklerle etkileşimi artırın.',
                'season': 'Yaz',
                'urgency': 'Yüksek'
            })
        elif month in [9, 10]:
            recommendations.append({
                'title': 'Sonbahar Kampanyası',
                'description': 'Yeni sezon ürünlerini öne çıkarın.',
                'season': 'Sonbahar',
                'urgency': 'Orta'
            })
        
        # Özel günler
        special_days = self._get_special_days(now)
        for day in special_days:
            recommendations.append({
                'title': f'{day["name"]} Fırsatı',
                'description': day['description'],
                'date': day['date'],
                'urgency': 'Yüksek'
            })
        
        return recommendations
    
    def _get_targeting_recommendations(self, campaign, score):
        """Hedefleme önerileri"""
        recommendations = []
        
        if score < 50:
            recommendations.append({
                'type': 'targeting',
                'title': 'Hedef Kitlenizi Daraltın',
                'description': 'Yaş aralığını, konumu ve ilgi alanlarını daha spesifik belirleyin.',
                'priority': 'high',
                'expected_impact': 40,
                'implementation_steps': [
                    'Yaş aralığını 5 yıl daraltın',
                    'Belirli şehirleri hedefleyin',
                    'İlgi alanlarını 3-5 ile sınırlayın'
                ]
            })
        
        if score < 70:
            recommendations.append({
                'type': 'targeting',
                'title': 'Lookalike Audience Kullanın',
                'description': 'Mevcut müşterilerinize benzer kitleler oluşturun.',
                'priority': 'medium',
                'expected_impact': 35,
                'implementation_steps': [
                    'Mevcut müşteri verilerinizi yükleyin',
                    '%1-3 lookalike oluşturun',
                    'A/B testi yapın'
                ]
            })
        
        # Yeniden hedefleme
        recommendations.append({
            'type': 'targeting',
            'title': 'Yeniden Hedefleme (Retargeting)',
            'description': 'Web sitenizi ziyaret eden veya sepete ürün ekleyen kullanıcıları hedefleyin.',
            'priority': 'medium',
            'expected_impact': 45,
            'implementation_steps': [
                'Facebook Pixel kurun',
                'Web site ziyaretçilerini hedefleyin',
                'Sepet terk edenler için özel teklif hazırlayın'
            ]
        })
        
        return recommendations
    
    def _get_creative_recommendations(self, campaign, score):
        """Kreatif öneriler"""
        recommendations = []
        
        if campaign.ad_type == 'image':
            recommendations.append({
                'type': 'creative',
                'title': 'Görsel Kalitesini Artırın',
                'description': 'Yüksek çözünürlüklü, dikkat çekici görseller kullanın. Metin görselin %20\'sinden az olmalı.',
                'priority': 'high' if score < 60 else 'medium',
                'expected_impact': 30,
                'tips': [
                    'Canlı renkler kullanın',
                    'Ürünü ön plana çıkarın',
                    'Minimalist tasarım tercih edin'
                ]
            })
        
        elif campaign.ad_type == 'video':
            recommendations.append({
                'type': 'creative',
                'title': 'Video Süresini Optimize Edin',
                'description': 'İlk 3 saniyede dikkat çekin, 15-30 saniye ideal süredir.',
                'priority': 'high',
                'expected_impact': 35,
                'tips': [
                    'Altyazı ekleyin',
                    'Harekete geçirici mesaj ekleyin',
                    'Logo ve marka görünürlüğü sağlayın'
                ]
            })
        
        # A/B Test önerisi
        recommendations.append({
            'type': 'creative',
            'title': 'A/B Testi Yapın',
            'description': 'Farklı görsel, metin ve CTA kombinasyonlarını test edin.',
            'priority': 'medium',
            'expected_impact': 25,
            'implementation_steps': [
                '2-3 farklı görsel hazırlayın',
                'Farklı başlıklar deneyin',
                'En iyi performans göstereni seçin'
            ]
        })
        
        return recommendations
    
    def _get_budget_recommendations(self, campaign, score):
        """Bütçe önerileri"""
        recommendations = []
        
        if score >= 70:
            recommendations.append({
                'type': 'budget',
                'title': 'Başarılı Kampanyaya Bütçe Artırın',
                'description': f'Kampanya performansı yüksek, bütçeyi %20-30 artırarak daha fazla dönüşüm elde edin.',
                'priority': 'high',
                'expected_impact': 50,
                'suggested_increase': '20-30%'
            })
        elif score < 40:
            recommendations.append({
                'type': 'budget',
                'title': 'Düşük Performanslı Kampanyayı Durdurun',
                'description': 'Bu kampanya için harcamayı durdurun veya azaltın, bütçeyi daha iyi performans gösteren kampanyalara kaydırın.',
                'priority': 'high',
                'expected_impact': -20,
                'suggested_action': 'Durdur veya Azalt'
            })
        
        # Bütçe dağılım önerisi
        recommendations.append({
            'type': 'budget',
            'title': 'Bütçe Dağılımını Optimize Edin',
            'description': 'Bütçenin %70\'ini en iyi performans gösteren kampanyalara, %30\'unu test kampanyalarına ayırın.',
            'priority': 'medium',
            'expected_impact': 20,
            'distribution': {
                'high_performance': '70%',
                'testing': '30%'
            }
        })
        
        return recommendations
    
    def _get_timing_recommendations(self, campaign, score):
        """Zamanlama önerileri"""
        recommendations = []
        
        # Yayın saati önerisi
        recommendations.append({
            'type': 'timing',
            'title': 'Yayın Saatlerini Optimize Edin',
            'description': 'Hedef kitlenizin en aktif olduğu saatlerde yayın yapın: 19:00-22:00 ve 12:00-14:00.',
            'priority': 'medium',
            'expected_impact': 25,
            'best_hours': ['19:00-22:00', '12:00-14:00']
        })
        
        # Haftanın günleri
        recommendations.append({
            'type': 'timing',
            'title': 'Haftanın Günlerini Optimize Edin',
            'description': 'Perşembe, Cuma ve Cumartesi günleri etkileşim oranları daha yüksektir.',
            'priority': 'low',
            'expected_impact': 15,
            'best_days': ['Perşembe', 'Cuma', 'Cumartesi']
        })
        
        return recommendations
    
    def _get_content_recommendations(self, campaign, score):
        """İçerik önerileri"""
        recommendations = []
        
        recommendations.append({
            'type': 'content',
            'title': 'Reklam Metnini Güçlendirin',
            'description': 'Daha fazla harekete geçirici ifade kullanın. "Şimdi Al", "Hemen Keşfet", "Sınırlı Stok" gibi.',
            'priority': 'high' if score < 60 else 'medium',
            'expected_impact': 20,
            'example_ctas': ['Hemen Al', 'Şimdi Keşfet', 'Detayları Gör', 'Sınırlı Stok']
        })
        
        # Kullanıcı tarafından oluşturulan içerik
        recommendations.append({
            'type': 'content',
            'title': 'Kullanıcı İçeriklerini Kullanın (UGC)',
            'description': 'Müşteri yorumları, fotoğrafları ve videolarını reklamlarınızda kullanın.',
            'priority': 'medium',
            'expected_impact': 30,
            'benefits': [
                'Daha güvenilir görünür',
                'Daha yüksek dönüşüm',
                'Daha düşük maliyet'
            ]
        })
        
        return recommendations
    
    def _get_platform_recommendations(self, campaign, score):
        """Platform önerileri"""
        recommendations = []
        
        recommendations.append({
            'type': 'platform',
            'title': 'Platform Çeşitlendirmesi Yapın',
            'description': 'Instagram yanında Facebook, TikTok ve Twitter\'da da reklam verin.',
            'priority': 'low',
            'expected_impact': 25,
            'platforms': [
                {'name': 'Facebook', 'benefit': 'Geniş kitle'},
                {'name': 'TikTok', 'benefit': 'Genç kitle'},
                {'name': 'Twitter', 'benefit': 'Trend takip'}
            ]
        })
        
        return recommendations
    
    def _get_ai_recommendations(self, campaign, performance_data):
        """AI destekli özel öneriler"""
        if not self.use_openai:
            return []
        
        try:
            prompt = self._build_recommendation_prompt(campaign, performance_data)
            from core.services.ai_gateway import create_chat_completion
            response = create_chat_completion(
                client=self.client, tariff_key="performance-insights",
                user=self.user, organization=self.organization,
                reference="recommendation_engine.recommendations",
                model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                messages=[
                    {"role": "system", "content": "Sen bir Instagram reklam uzmanısın. Kısa ve uygulanabilir öneriler sun."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            ai_response = response.choices[0].message.content
            return self._parse_ai_recommendations(ai_response)
            
        except Exception as e:
            print(f"AI öneri hatası: {str(e)}")
            return []
    
    def _build_recommendation_prompt(self, campaign, performance_data):
        """AI prompt'u oluştur"""
        score = performance_data.get('performance_score', 50)
        strengths = performance_data.get('strengths', [])
        weaknesses = performance_data.get('weaknesses', [])
        
        prompt = f"""
Kampanya Performans Verileri:
- Performans Puanı: {score}/100
- Güçlü Yönler: {', '.join(strengths[:3])}
- Zayıf Yönler: {', '.join(weaknesses[:3])}
- Reklam Türü: {campaign.ad_type}
- Bütçe: {campaign.budget} TL

Bu kampanya için 3 özel öneri üret. Her öneri şunları içersin:
- Başlık
- Kısa açıklama
- Beklenen etki (yüzde olarak)

Öneriler spesifik, uygulanabilir ve ölçülebilir olsun.
"""
        return prompt
    
    def _parse_ai_recommendations(self, ai_response):
        """AI yanıtını parse et"""
        recommendations = []
        lines = ai_response.strip().split('\n')
        
        current_rec = {}
        for line in lines:
            line = line.strip()
            if line.startswith(('1.', '2.', '3.', '-')) or (line and line[0].isdigit() and '.' in line[:3]):
                if current_rec:
                    recommendations.append(current_rec)
                current_rec = {
                    'type': 'ai',
                    'title': line.lstrip('1234567890.- '),
                    'description': '',
                    'priority': 'medium',
                    'expected_impact': 25
                }
            elif current_rec and line:
                current_rec['description'] += line + ' '
        
        if current_rec:
            recommendations.append(current_rec)
        
        return recommendations
    
    def _get_priority_weight(self, priority):
        """Öncelik ağırlığını döndür"""
        weights = {'high': 1, 'medium': 2, 'low': 3}
        return weights.get(priority, 2)
    
    def _get_special_days(self, date):
        """Özel günleri döndür"""
        month = date.month
        day = date.day
        
        special_days = []
        
        # Yılbaşı
        if month == 1 and day <= 7:
            special_days.append({
                'name': 'Yılbaşı İndirimi',
                'description': 'Yeni yıl fırsatlarıyla dönüşümleri artırın.',
                'date': '1-7 Ocak'
            })
        
        # Sevgililer Günü
        if month == 2 and day <= 14:
            special_days.append({
                'name': 'Sevgililer Günü Kampanyası',
                'description': 'Hediye önerileri ve özel indirimler sunun.',
                'date': '14 Şubat'
            })
        
        # Anneler Günü (Mayıs 2. Pazar)
        if month == 5:
            special_days.append({
                'name': 'Anneler Günü Fırsatı',
                'description': 'Anne hediyesi önerileri ve özel teklifler hazırlayın.',
                'date': 'Mayıs (2. Pazar)'
            })
        
        # Black Friday
        if month == 11:
            special_days.append({
                'name': 'Black Friday Fırsatı',
                'description': 'Büyük indirimlerle dönüşümleri maksimize edin.',
                'date': 'Kasım (4. Cuma)'
            })
        
        return special_days


class QuickRecommendationEngine(RecommendationEngine):
    """Hızlı öneri motoru - daha basit ve hızlı öneriler"""
    
    def generate_recommendations(self, campaign, performance_data):
        """Basit ve hızlı öneriler"""
        score = performance_data.get('performance_score', 50)
        recommendations = []
        
        # Sadece en kritik öneriler
        if score < 50:
            recommendations.append({
                'title': '🚨 Acil: Hedef Kitleyi Daraltın',
                'description': 'Hedef kitleniz çok geniş, daha spesifik bir kitle belirleyin.',
                'action': 'Hemen uygula',
                'priority': 'critical'
            })
        
        if score < 60:
            recommendations.append({
                'title': '📸 Görselleri Güncelleyin',
                'description': 'Daha kaliteli ve dikkat çekici görseller kullanın.',
                'action': 'Bugün dene',
                'priority': 'high'
            })
        
        recommendations.append({
            'title': '⏰ Yayın Saatini Optimize Edin',
            'description': 'Akşam 19:00-22:00 arasında yayın yapmayı deneyin.',
            'action': 'Hemen ayarla',
            'priority': 'medium'
        })
        
        return recommendations
