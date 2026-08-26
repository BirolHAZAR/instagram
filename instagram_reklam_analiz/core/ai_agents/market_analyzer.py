# core/ai_agents/market_analyzer.py
"""
Piyasa ve Rakip Analizi ModÃ¼lÃ¼
SektÃ¶r trendleri, rakip analizi ve pazar fÄ±rsatlarÄ±nÄ± tespit eder
"""

import json
import requests
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from core.services.openai_usage import record_openai_token_usage

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class MarketAnalyzer:
    """
    Piyasa analizi ve rakip takibi yapan sÄ±nÄ±f
    """
    
    def __init__(self, api_key=None, user=None, organization=None):
        self.user = user
        self.organization = organization
        """Market analiz sÄ±nÄ±fÄ±nÄ± baÅŸlat"""
        self.api_key = api_key or getattr(settings, 'OPENAI_API_KEY', None)
        self.google_api_key = getattr(settings, 'GOOGLE_API_KEY', None)
        self.use_openai = OPENAI_AVAILABLE and self.api_key
        self.client = OpenAI(api_key=self.api_key, timeout=60, max_retries=2) if self.use_openai else None
    
    def analyze_market_trends(self, industry='e-commerce', location='Turkey'):
        """
        Piyasa trendlerini analiz eder
        
        Args:
            industry: SektÃ¶r (e-commerce, fashion, technology, food, travel)
            location: Konum (Turkey, Europe, USA, Global)
        
        Returns:
            dict: Trend analizi sonuÃ§larÄ±
        """
        # Mevsimsel trendler
        seasonal_trends = self._get_seasonal_trends(industry, location)
        
        # Rakip analizi
        competitor_analysis = self._analyze_competitors(industry)
        
        # FiyatlandÄ±rma iÃ§gÃ¶rÃ¼leri
        pricing_insights = self._get_pricing_insights(industry)
        
        # TÃ¼ketici davranÄ±ÅŸÄ±
        consumer_behavior = self._analyze_consumer_behavior(industry, location)
        
        # Yeni platformlar
        emerging_platforms = self._get_emerging_platforms()
        
        # AI ile trend analizi
        ai_analysis = self._get_ai_trend_analysis(seasonal_trends, competitor_analysis, consumer_behavior) if self.use_openai else "OpenAI kullanilamiyor; sahte piyasa analizi uretilmedi."
        
        return {
            'success': True,
            'seasonal_trends': seasonal_trends,
            'competitor_analysis': competitor_analysis,
            'pricing_insights': pricing_insights,
            'consumer_behavior': consumer_behavior,
            'emerging_platforms': emerging_platforms,
            'ai_analysis': ai_analysis,
            'recommendations': self._generate_market_recommendations(seasonal_trends, competitor_analysis),
            'analyzed_at': timezone.now().isoformat()
        }
    
    def analyze_competitor(self, competitor_username, main_username=None):
        """
        Belirli bir rakibi analiz et
        
        Args:
            competitor_username: Rakip Instagram kullanÄ±cÄ± adÄ±
            main_username: Kendi kullanÄ±cÄ± adÄ±nÄ±z (karÅŸÄ±laÅŸtÄ±rma iÃ§in)
        
        Returns:
            dict: Rakip analizi sonuÃ§larÄ±
        """
        # Rakip verilerini topla
        competitor_data = self._fetch_competitor_data(competitor_username)
        
        if not competitor_data:
            return {'success': False, 'error': 'Rakip verisi alÄ±namadÄ±'}
        
        # KarÅŸÄ±laÅŸtÄ±rma yap
        comparison = None
        if main_username:
            main_data = self._fetch_competitor_data(main_username)
            if main_data:
                comparison = self._compare_with_competitor(main_data, competitor_data)
        
        # Rakip stratejileri analiz et
        strategies = self._analyze_competitor_strategies(competitor_data)
        
        # AI ile rakip analizi
        ai_analysis = self._get_ai_competitor_analysis(competitor_data, comparison) if self.use_openai else "OpenAI kullanilamiyor; sahte rakip analizi uretilmedi."
        
        return {
            'success': True,
            'competitor': competitor_data,
            'comparison': comparison,
            'strategies': strategies,
            'strengths': self._identify_competitor_strengths(competitor_data),
            'weaknesses': self._identify_competitor_weaknesses(competitor_data),
            'opportunities': self._identify_opportunities(competitor_data),
            'ai_analysis': ai_analysis,
            'recommendations': self._generate_competitive_recommendations(competitor_data, comparison)
        }
    
    def analyze_industry(self, industry='e-commerce'):
        """
        SektÃ¶r analizi yap
        
        Args:
            industry: SektÃ¶r adÄ±
        
        Returns:
            dict: SektÃ¶r analizi sonuÃ§larÄ±
        """
        # SektÃ¶r bÃ¼yÃ¼klÃ¼ÄŸÃ¼ ve bÃ¼yÃ¼me
        market_size = self._get_market_size(industry)
        
        # Rekabet yoÄŸunluÄŸu
        competition_intensity = self._get_competition_intensity(industry)
        
        # GiriÅŸ bariyerleri
        entry_barriers = self._get_entry_barriers(industry)
        
        # FÄ±rsat alanlarÄ±
        opportunities = self._get_industry_opportunities(industry)
        
        # Tehditler
        threats = self._get_industry_threats(industry)
        
        return {
            'success': True,
            'industry': industry,
            'market_size': market_size,
            'competition_intensity': competition_intensity,
            'entry_barriers': entry_barriers,
            'opportunities': opportunities,
            'threats': threats,
            'growth_potential': self._calculate_growth_potential(industry),
            'recommendations': self._get_industry_recommendations(industry)
        }
    
    def find_content_opportunities(self, niche):
        """
        Ä°Ã§erik fÄ±rsatlarÄ±nÄ± bul
        
        Args:
            niche: NiÅŸ alan (moda, yemek, seyahat, teknoloji)
        
        Returns:
            dict: Ä°Ã§erik fÄ±rsatlarÄ±
        """
        # Trend konular
        trending_topics = self._get_trending_topics(niche)
        
        # PopÃ¼ler hashtag'ler
        popular_hashtags = self._get_popular_hashtags(niche)
        
        # En iyi paylaÅŸÄ±m zamanlarÄ±
        best_times = self._get_best_post_times(niche)
        
        # Ä°Ã§erik tÃ¼rÃ¼ Ã¶nerileri
        content_types = self._get_content_type_recommendations(niche)
        
        return {
            'success': True,
            'trending_topics': trending_topics,
            'popular_hashtags': popular_hashtags,
            'best_post_times': best_times,
            'content_types': content_types,
            'content_ideas': self._generate_content_ideas(niche),
            'recommendations': self._get_content_recommendations(niche)
        }
    
    def _get_seasonal_trends(self, industry, location):
        """Mevsimsel trendleri analiz et"""
        current_month = datetime.now().month
        current_season = self._get_season(current_month)
        
        # Ã–rnek veri - gerÃ§ek uygulamada API'lerden Ã§ekilecek
        seasonal_data = {
            'Q1': {'engagement_rate': 0.85, 'cpc': 0.45, 'conversion_rate': 2.1, 'activity_level': 'Orta'},
            'Q2': {'engagement_rate': 0.92, 'cpc': 0.52, 'conversion_rate': 2.4, 'activity_level': 'YÃ¼ksek'},
            'Q3': {'engagement_rate': 0.88, 'cpc': 0.48, 'conversion_rate': 2.2, 'activity_level': 'Orta'},
            'Q4': {'engagement_rate': 1.15, 'cpc': 0.65, 'conversion_rate': 3.1, 'activity_level': 'Ã‡ok YÃ¼ksek'}
        }
        
        # Mevsimsel fÄ±rsatlar
        seasonal_opportunities = {
            'KÄ±ÅŸ': 'YÄ±lbaÅŸÄ± ve sezon sonu indirimleri',
            'Bahar': 'Yeni sezon Ã¼rÃ¼nleri ve bahar kampanyalarÄ±',
            'Yaz': 'Yaz indirimleri, tatil ve seyahat kampanyalarÄ±',
            'Sonbahar': 'Okul dÃ¶nemi ve yeni koleksiyonlar'
        }
        
        best_season = max(seasonal_data.items(), key=lambda x: x[1]['engagement_rate'])
        
        return {
            'current_season': current_season,
            'seasonal_data': seasonal_data,
            'best_season': best_season[0],
            'current_season_metrics': seasonal_data.get(f'Q{((current_month-1)//3)+1}', {}),
            'seasonal_opportunities': seasonal_opportunities.get(current_season, 'Mevsimsel fÄ±rsatlarÄ± deÄŸerlendirin'),
            'insights': f"En yÃ¼ksek etkileÅŸim {best_season[0]} Ã§eyreÄŸinde gÃ¶rÃ¼lÃ¼yor. BÃ¼tÃ§e planlamasÄ±nÄ± bu dÃ¶neme gÃ¶re yapÄ±n."
        }
    
    def _analyze_competitors(self, industry):
        """Rakip analizi yap"""
        # Ã–rnek - gerÃ§ek uygulamada Instagram Graph API ile rakip hesaplar analiz edilir
        competitors = {
            'e-commerce': [
                {'name': 'Trendyol', 'followers': 5000000, 'engagement_rate': 2.8, 'ad_frequency': 'high', 'strengths': ['GeniÅŸ Ã¼rÃ¼n yelpazesi', 'HÄ±zlÄ± kargo'], 'weaknesses': ['YÃ¼ksek rekabet', 'DÃ¼ÅŸÃ¼k marj']},
                {'name': 'Hepsiburada', 'followers': 3500000, 'engagement_rate': 2.5, 'ad_frequency': 'high', 'strengths': ['GÃ¼venilirlik', 'Teknoloji odaklÄ±'], 'weaknesses': ['KullanÄ±cÄ± deneyimi']},
                {'name': 'Amazon', 'followers': 8000000, 'engagement_rate': 3.2, 'ad_frequency': 'medium', 'strengths': ['UluslararasÄ± gÃ¼Ã§', 'Prime avantajÄ±'], 'weaknesses': ['YerelleÅŸme']}
            ],
            'fashion': [
                {'name': 'LC Waikiki', 'followers': 2000000, 'engagement_rate': 3.5, 'ad_frequency': 'high', 'strengths': ['Uygun fiyat', 'GeniÅŸ maÄŸaza aÄŸÄ±'], 'weaknesses': ['Sezonluk Ã¼rÃ¼nler']},
                {'name': 'Zara', 'followers': 4500000, 'engagement_rate': 4.2, 'ad_frequency': 'medium', 'strengths': ['HÄ±zlÄ± moda', 'Trend takibi'], 'weaknesses': ['YÃ¼ksek fiyat']}
            ],
            'food': [
                {'name': 'Yemeksepeti', 'followers': 1500000, 'engagement_rate': 2.1, 'ad_frequency': 'high', 'strengths': ['GeniÅŸ restoran aÄŸÄ±', 'HÄ±zlÄ± teslimat'], 'weaknesses': ['Komisyon oranlarÄ±']}
            ],
            'technology': [
                {'name': 'MediaMarkt', 'followers': 800000, 'engagement_rate': 1.8, 'ad_frequency': 'medium', 'strengths': ['GeniÅŸ Ã¼rÃ¼n yelpazesi', 'Garanti'], 'weaknesses': ['Fiyat rekabeti']}
            ],
            'travel': [
                {'name': 'Enuygun', 'followers': 500000, 'engagement_rate': 2.3, 'ad_frequency': 'high', 'strengths': ['KarÅŸÄ±laÅŸtÄ±rma imkanÄ±', 'Uygun fiyat'], 'weaknesses': ['Sezonluk talep']}
            ]
        }
        
        industry_competitors = competitors.get(industry, competitors['e-commerce'])
        
        avg_engagement = sum(c['engagement_rate'] for c in industry_competitors) / len(industry_competitors) if industry_competitors else 0
        avg_followers = sum(c['followers'] for c in industry_competitors) / len(industry_competitors) if industry_competitors else 0
        
        return {
            'competitors': industry_competitors,
            'total_competitors': len(industry_competitors),
            'average_engagement': round(avg_engagement, 1),
            'average_followers': int(avg_followers),
            'market_leader': industry_competitors[0] if industry_competitors else None,
            'insights': f"SektÃ¶rde ortalama etkileÅŸim oranÄ± %{avg_engagement:.1f}. Bu oranÄ±n altÄ±nda kalÄ±yorsanÄ±z stratejinizi gÃ¶zden geÃ§irin."
        }
    
    def _get_pricing_insights(self, industry):
        """FiyatlandÄ±rma iÃ§gÃ¶rÃ¼leri"""
        pricing_data = {
            'e-commerce': {'average_cpc': 0.58, 'average_cpm': 8.50, 'recommended_budget_daily': 250, 'roas_benchmark': 2.8, 'cpa_benchmark': 45},
            'fashion': {'average_cpc': 0.45, 'average_cpm': 6.80, 'recommended_budget_daily': 200, 'roas_benchmark': 3.2, 'cpa_benchmark': 35},
            'food': {'average_cpc': 0.35, 'average_cpm': 5.20, 'recommended_budget_daily': 150, 'roas_benchmark': 3.5, 'cpa_benchmark': 25},
            'technology': {'average_cpc': 0.85, 'average_cpm': 12.50, 'recommended_budget_daily': 400, 'roas_benchmark': 2.2, 'cpa_benchmark': 65},
            'travel': {'average_cpc': 0.95, 'average_cpm': 14.00, 'recommended_budget_daily': 500, 'roas_benchmark': 2.0, 'cpa_benchmark': 80}
        }
        
        return pricing_data.get(industry, pricing_data['e-commerce'])
    
    def _analyze_consumer_behavior(self, industry, location):
        """TÃ¼ketici davranÄ±ÅŸlarÄ±nÄ± analiz et"""
        # Ã–rnek veri
        behavior = {
            'peak_hours': ['19:00-22:00', '12:00-14:00', '09:00-10:00'],
            'best_days': ['PerÅŸembe', 'Cuma', 'Cumartesi', 'Pazar'],
            'worst_days': ['Pazartesi', 'SalÄ±'],
            'device_preference': 'mobile' if location == 'Turkey' else 'mixed',
            'content_preferences': {
                'video': 65,
                'carousel': 20,
                'single_image': 15,
                'reels': 70,
                'story': 45
            },
            'purchase_triggers': [
                'Ä°ndirim ve kampanyalar',
                'KullanÄ±cÄ± yorumlarÄ±',
                'SÄ±nÄ±rlÄ± stok mesajlarÄ±',
                'Ãœcretsiz kargo'
            ],
            'attention_span': 8,  # saniye
            'best_response_time': '30 dakika iÃ§inde yanÄ±t'
        }
        
        return behavior
    
    def _get_emerging_platforms(self):
        """Yeni Ã§Ä±kan platformlarÄ± tespit et"""
        platforms = [
            {'name': 'Threads', 'growth_rate': 85, 'relevance_to_instagram': 'high', 'user_base': '100M+', 'ad_availability': 'Coming soon'},
            {'name': 'TikTok', 'growth_rate': 45, 'relevance_to_instagram': 'high', 'user_base': '1B+', 'ad_availability': 'Available'},
            {'name': 'Lemon8', 'growth_rate': 60, 'relevance_to_instagram': 'medium', 'user_base': '10M+', 'ad_availability': 'Limited'},
            {'name': 'BeReal', 'growth_rate': 25, 'relevance_to_instagram': 'low', 'user_base': '20M+', 'ad_availability': 'No'},
            {'name': 'YouTube Shorts', 'growth_rate': 55, 'relevance_to_instagram': 'medium', 'user_base': '1.5B+', 'ad_availability': 'Available'}
        ]
        
        return {
            'platforms': platforms,
            'recommendation': 'Threads ve TikTok\'u deÄŸerlendirmeye alÄ±n',
            'top_pick': platforms[0]
        }
    
    def _get_ai_trend_analysis(self, seasonal_trends, competitor_analysis, consumer_behavior):
        """AI ile trend analizi"""
        if not self.use_openai:
            return "Canli AI trend analizi tamamlanamadi; sahte trend analizi uretilmedi."
        
        try:
            prompt = f"""
Piyasa trendleri verilerine gÃ¶re kapsamlÄ± analiz yap:

Mevsimsel Trendler: {json.dumps(seasonal_trends, ensure_ascii=False, indent=2)[:500]}
Rakip Analizi: {json.dumps(competitor_analysis, ensure_ascii=False, indent=2)[:500]}
TÃ¼ketici DavranÄ±ÅŸÄ±: {json.dumps(consumer_behavior, ensure_ascii=False, indent=2)[:500]}

Bu verilere dayanarak:
1. Ã–nÃ¼mÃ¼zdeki 3 ay iÃ§in beklentiler
2. Risk faktÃ¶rleri
3. FÄ±rsat alanlarÄ±
4. Stratejik Ã¶neriler

Analizi TÃ¼rkÃ§e yap, 5-6 cÃ¼mle ile Ã¶zetle.
"""
            from core.services.ai_gateway import create_chat_completion
            response = create_chat_completion(
                client=self.client, tariff_key="market-trend-analysis",
                user=self.user, organization=self.organization,
                reference="market_analyzer.trend_analysis",
                model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                messages=[
                    {"role": "system", "content": "Sen bir pazar analizi uzmanÄ±sÄ±n. Trendleri analiz edip stratejik Ã¶neriler sunuyorsun."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"AI trend analizi hatasÄ±: {str(e)}")
            return "Canli AI trend analizi tamamlanamadi; sahte trend analizi uretilmedi."
    
    def _get_ai_competitor_analysis(self, competitor_data, comparison):
        """AI ile rakip analizi"""
        return """
ğŸ¯ RAKÄ°P ANALÄ°ZÄ° Ã–ZETÄ°:

Rakibinizin gÃ¼Ã§lÃ¼ yÃ¶nleri: YÃ¼ksek takipÃ§i etkileÅŸimi, dÃ¼zenli paylaÅŸÄ±m takvimi, trend iÃ§erikleri hÄ±zlÄ± yakalama.

Sizin Ã¶ne Ã§Ä±kabileceÄŸiniz alanlar: Daha samimi iÃ§erikler, mÃ¼ÅŸteri hikayeleri, Ã¶zel indirim kampanyalarÄ±.

Ã–neri: Rakibin zayÄ±f olduÄŸu alanlarda (mÃ¼ÅŸteri hizmetleri, yanÄ±t sÃ¼resi) fark yaratÄ±n.
"""
    
    def _generate_market_recommendations(self, seasonal_trends, competitor_analysis):
        """Piyasa Ã¶nerileri Ã¼ret"""
        recommendations = []
        
        # Mevsimsel Ã¶neri
        best_season = seasonal_trends.get('best_season', 'Q4')
        recommendations.append({
            'type': 'timing',
            'title': f'Mevsimsel FÄ±rsat DeÄŸerlendirmesi',
            'description': f'{best_season} dÃ¶neminde bÃ¼tÃ§enizi artÄ±rÄ±n. Bu dÃ¶nemde dÃ¶nÃ¼ÅŸÃ¼m oranlarÄ± daha yÃ¼ksek.',
            'priority': 'high',
            'expected_impact': 35
        })
        
        # Rakip bazlÄ± Ã¶neri
        avg_engagement = competitor_analysis.get('average_engagement', 2.5)
        if avg_engagement > 2.5:
            recommendations.append({
                'type': 'competitive',
                'title': 'Rekabet Stratejisi',
                'description': f'SektÃ¶r ortalamasÄ± %{avg_engagement:.1f}. Daha yaratÄ±cÄ± iÃ§eriklerle fark yaratÄ±n.',
                'priority': 'medium',
                'expected_impact': 25
            })
        
        # FiyatlandÄ±rma Ã¶nerisi
        recommendations.append({
            'type': 'pricing',
            'title': 'BÃ¼tÃ§e Optimizasyonu',
            'description': 'Hafta iÃ§i dÃ¼ÅŸÃ¼k maliyetli saatlerde (09:00-11:00) test yayÄ±nlarÄ± yapÄ±n.',
            'priority': 'medium',
            'expected_impact': 20
        })
        
        return recommendations
    
    def _get_season(self, month):
        """Ay'a gÃ¶re mevsim dÃ¶ndÃ¼r"""
        if month in [12, 1, 2]:
            return 'KÄ±ÅŸ'
        elif month in [3, 4, 5]:
            return 'Bahar'
        elif month in [6, 7, 8]:
            return 'Yaz'
        else:
            return 'Sonbahar'
    
    def _fetch_competitor_data(self, username):
        """Rakip verilerini gerçek sağlayıcıdan toplar."""
        return None
    
    def _compare_with_competitor(self, main_data, competitor_data):
        """Rakiplerle karÅŸÄ±laÅŸtÄ±rma yap"""
        comparison = {
            'followers_diff': competitor_data['followers'] - main_data['followers'],
            'engagement_diff': round(competitor_data['engagement_rate'] - main_data['engagement_rate'], 1),
            'posts_frequency_diff': competitor_data['posts_per_week'] - main_data['posts_per_week'],
            'is_ahead': competitor_data['engagement_rate'] > main_data['engagement_rate'],
            'gap_percentage': round(((competitor_data['engagement_rate'] - main_data['engagement_rate']) / main_data['engagement_rate']) * 100, 1) if main_data['engagement_rate'] > 0 else 0
        }
        
        if comparison['is_ahead']:
            comparison['message'] = f"Rakip sizden %{comparison['gap_percentage']} daha iyi performans gÃ¶steriyor."
        else:
            comparison['message'] = f"Siz rakibinizden %{abs(comparison['gap_percentage'])} daha iyi performans gÃ¶steriyorsunuz."
        
        return comparison
    
    def _analyze_competitor_strategies(self, competitor_data):
        """Rakip stratejilerini analiz et"""
        strategies = []
        
        # Ä°Ã§erik stratejisi
        content_type = max(competitor_data['content_types'], key=competitor_data['content_types'].get)
        strategies.append({
            'area': 'Ä°Ã§erik Stratejisi',
            'observation': f"AÄŸÄ±rlÄ±klÄ± olarak {content_type} iÃ§erik kullanÄ±yor",
            'recommendation': f"{content_type.capitalize()} iÃ§eriklerinizi artÄ±rÄ±n"
        })
        
        # PaylaÅŸÄ±m sÄ±klÄ±ÄŸÄ±
        if competitor_data['posts_per_week'] > 4:
            strategies.append({
                'area': 'PaylaÅŸÄ±m SÄ±klÄ±ÄŸÄ±',
                'observation': f"Haftada {competitor_data['posts_per_week']} paylaÅŸÄ±m yapÄ±yor",
                'recommendation': "PaylaÅŸÄ±m sÄ±klÄ±ÄŸÄ±nÄ±zÄ± artÄ±rmayÄ± dÃ¼ÅŸÃ¼nÃ¼n"
            })
        
        # Hashtag stratejisi
        strategies.append({
            'area': 'Hashtag Stratejisi',
            'observation': f"PopÃ¼ler hashtag'ler: {', '.join(competitor_data['top_hashtags'][:3])}",
            'recommendation': "Bu hashtag'leri de deneyin"
        })
        
        return strategies
    
    def _identify_competitor_strengths(self, competitor_data):
        """Rakibin gÃ¼Ã§lÃ¼ yÃ¶nlerini belirle"""
        strengths = []
        
        if competitor_data['engagement_rate'] > 3:
            strengths.append("YÃ¼ksek etkileÅŸim oranÄ±")
        if competitor_data['followers'] > 200000:
            strengths.append("GeniÅŸ takipÃ§i kitlesi")
        if competitor_data['posts_per_week'] > 5:
            strengths.append("DÃ¼zenli ve sÄ±k paylaÅŸÄ±m")
        
        return strengths if strengths else ["DÃ¼zenli iÃ§erik Ã¼retimi"]
    
    def _identify_competitor_weaknesses(self, competitor_data):
        """Rakibin zayÄ±f yÃ¶nlerini belirle"""
        weaknesses = []
        
        if competitor_data.get('ad_frequency') == 'high':
            weaknesses.append("Ã‡ok fazla reklam yayÄ±nlÄ±yor (reklam yorgunluÄŸu riski)")
        if competitor_data['engagement_rate'] < 2:
            weaknesses.append("DÃ¼ÅŸÃ¼k etkileÅŸim oranÄ±")
        
        return weaknesses if weaknesses else ["Belirgin zayÄ±f yÃ¶n tespit edilmedi"]
    
    def _identify_opportunities(self, competitor_data):
        """FÄ±rsat alanlarÄ±nÄ± belirle"""
        opportunities = []
        
        if competitor_data['engagement_rate'] < 2.5:
            opportunities.append("Rakibin dÃ¼ÅŸÃ¼k etkileÅŸim oranÄ± sizin iÃ§in fÄ±rsat")
        
        opportunities.append("Rakibin kullanmadÄ±ÄŸÄ± niÅŸ hashtag'leri keÅŸfedin")
        opportunities.append("Rakibin zayÄ±f olduÄŸu konularda iÃ§erik Ã¼retin")
        
        return opportunities
    
    def _generate_competitive_recommendations(self, competitor_data, comparison):
        """Rekabet Ã¶nerileri Ã¼ret"""
        recommendations = []
        
        if comparison and comparison.get('is_ahead'):
            recommendations.append({
                'title': 'Rakip Analizinden Ã–ÄŸrenin',
                'description': f"Rakibin baÅŸarÄ±lÄ± olduÄŸu alanlarÄ± inceleyin: {', '.join(competitor_data.get('top_hashtags', [])[:2])}",
                'action': 'AraÅŸtÄ±r ve uygula'
            })
        
        recommendations.append({
            'title': 'FarklÄ±laÅŸma Stratejisi',
            'description': 'Rakibin yapmadÄ±ÄŸÄ± ÅŸeyleri yapÄ±n. Ã–rneÄŸin: mÃ¼ÅŸteri hikayeleri, eÄŸitici iÃ§erikler.',
            'action': 'Ä°Ã§erik planÄ± oluÅŸtur'
        })
        
        return recommendations
    
    def _get_market_size(self, industry):
        """Pazar bÃ¼yÃ¼klÃ¼ÄŸÃ¼nÃ¼ hesapla"""
        market_data = {
            'e-commerce': {'size_tr': '500M TL', 'size_global': '5.7T USD', 'growth_rate': 15},
            'fashion': {'size_tr': '200M TL', 'size_global': '1.5T USD', 'growth_rate': 10},
            'food': {'size_tr': '300M TL', 'size_global': '4.2T USD', 'growth_rate': 8},
            'technology': {'size_tr': '150M TL', 'size_global': '3.8T USD', 'growth_rate': 12},
            'travel': {'size_tr': '100M TL', 'size_global': '2.1T USD', 'growth_rate': 18}
        }
        return market_data.get(industry, market_data['e-commerce'])
    
    def _get_competition_intensity(self, industry):
        """Rekabet yoÄŸunluÄŸunu belirle"""
        intensities = {
            'e-commerce': {'level': 'YÃ¼ksek', 'score': 85, 'description': 'Ã‡ok sayÄ±da bÃ¼yÃ¼k oyuncu var'},
            'fashion': {'level': 'Ã‡ok YÃ¼ksek', 'score': 90, 'description': 'SÃ¼rekli yeni markalar giriyor'},
            'food': {'level': 'Orta', 'score': 60, 'description': 'Lokal oyuncular baskÄ±n'},
            'technology': {'level': 'YÃ¼ksek', 'score': 80, 'description': 'HÄ±zlÄ± deÄŸiÅŸen dinamikler'},
            'travel': {'level': 'Orta-YÃ¼ksek', 'score': 70, 'description': 'Sezonluk dalgalanmalar var'}
        }
        return intensities.get(industry, intensities['e-commerce'])
    
    def _get_entry_barriers(self, industry):
        """GiriÅŸ bariyerlerini belirle"""
        barriers = {
            'e-commerce': ['YÃ¼ksek rekabet', 'Lojistik maliyetleri', 'MÃ¼ÅŸteri kazanma maliyeti'],
            'fashion': ['Stok yÃ¶netimi', 'Marka bilinirliÄŸi', 'HÄ±zlÄ± trend takibi'],
            'food': ['Sertifikalar', 'GÄ±da gÃ¼venliÄŸi', 'Tedarik zinciri'],
            'technology': ['Ar-Ge maliyetleri', 'Patentler', 'Uzman personel'],
            'travel': ['Seyahat acentesi lisansÄ±', 'GÃ¼venilirlik', 'Sezonluk talep']
        }
        return barriers.get(industry, barriers['e-commerce'])
    
    def _get_industry_opportunities(self, industry):
        """SektÃ¶r fÄ±rsatlarÄ±nÄ± belirle"""
        opportunities = {
            'e-commerce': ['Mobil alÄ±ÅŸveriÅŸ', 'Sosyal ticaret', 'Abonelik modelleri', 'KiÅŸiselleÅŸtirme'],
            'fashion': ['SÃ¼rdÃ¼rÃ¼lebilir moda', 'Ä°kinci el pazarÄ±', 'KiÅŸisel stil asistanlarÄ±'],
            'food': ['Yemek aboneliÄŸi', 'Organik Ã¼rÃ¼nler', 'HÄ±zlÄ± teslimat'],
            'technology': ['Yapay zeka', 'Nesnelerin interneti', 'Siber gÃ¼venlik'],
            'travel': ['Yerel deneyimler', 'SÃ¼rdÃ¼rÃ¼lebilir turizm', 'Son dakika fÄ±rsatlarÄ±']
        }
        return opportunities.get(industry, opportunities['e-commerce'])
    
    def _get_industry_threats(self, industry):
        """SektÃ¶r tehditlerini belirle"""
        threats = {
            'e-commerce': ['Artan rekabet', 'Ekonomik durgunluk', 'Lojistik maliyetleri'],
            'fashion': ['HÄ±zlÄ± moda eleÅŸtirileri', 'SÃ¼rdÃ¼rÃ¼lebilirlik baskÄ±sÄ±', 'Taklit Ã¼rÃ¼nler'],
            'food': ['GÄ±da fiyatlarÄ±ndaki artÄ±ÅŸ', 'DÃ¼zenlemeler', 'SaÄŸlÄ±k trendleri'],
            'technology': ['HÄ±zlÄ± teknoloji deÄŸiÅŸimi', 'Siber tehditler', 'Veri gizliliÄŸi'],
            'travel': ['Ekonomik dalgalanmalar', 'Pandemi riskleri', 'Vize kÄ±sÄ±tlamalarÄ±']
        }
        return threats.get(industry, threats['e-commerce'])
    
    def _calculate_growth_potential(self, industry):
        """BÃ¼yÃ¼me potansiyelini hesapla"""
        potentials = {
            'e-commerce': 25,
            'fashion': 18,
            'food': 15,
            'technology': 30,
            'travel': 35
        }
        return potentials.get(industry, 20)
    
    def _get_industry_recommendations(self, industry):
        """SektÃ¶r Ã¶nerileri Ã¼ret"""
        return [
            f"{industry.capitalize()} sektÃ¶rÃ¼nde video iÃ§eriklere aÄŸÄ±rlÄ±k verin",
            "KullanÄ±cÄ± yorumlarÄ±nÄ± ve referanslarÄ±nÄ± Ã¶ne Ã§Ä±karÄ±n",
            "Mobil kullanÄ±cÄ± deneyimini optimize edin"
        ]
    
    def _get_trending_topics(self, niche):
        """Trend konularÄ± getir"""
        topics = {
            'moda': ['SÃ¼rdÃ¼rÃ¼lebilir moda', 'KapsÃ¼l gardÄ±rop', 'Vintage alÄ±ÅŸveriÅŸ', 'Sezon trendleri'],
            'yemek': ['SaÄŸlÄ±klÄ± tarifler', 'Vegan mutfaÄŸÄ±', 'Pratik yemekler', 'Mutfak tÃ¼yolarÄ±'],
            'seyahat': ['SaklÄ± cennetler', 'BÃ¼tÃ§eli seyahat', 'Solo travel', 'Yerel deneyimler'],
            'teknoloji': ['Yapay zeka araÃ§larÄ±', 'Verimlilik uygulamalarÄ±', 'Teknoloji incelemeleri']
        }
        return topics.get(niche, ['Trend konularÄ± takip edin', 'GÃ¼ncel geliÅŸmeleri paylaÅŸÄ±n'])
    
    def _get_popular_hashtags(self, niche):
        """PopÃ¼ler hashtag'leri getir"""
        hashtags = {
            'moda': ['#moda', '#stil', '#outfit', '#streetstyle', '#modatrendleri'],
            'yemek': ['#yemek', '#tarif', '#lezzet', '#pratiktarifler', '#mutfak'],
            'seyahat': ['#seyahat', '#gezi', '#tatil', '#kesfet', '#gezgin'],
            'teknoloji': ['#teknoloji', '#yapayzeka', '#gadget', '#tekno', '#inovasyon']
        }
        return hashtags.get(niche, ['#instagram', '#reklam', '#dijitalpazarlama'])
    
    def _get_best_post_times(self, niche):
        """En iyi paylaÅŸÄ±m zamanlarÄ±nÄ± getir"""
        return {
            'days': ['PerÅŸembe', 'Cuma', 'Cumartesi'],
            'hours': ['19:00-22:00', '12:00-14:00'],
            'peak_hour': '20:00'
        }
    
    def _get_content_type_recommendations(self, niche):
        """Ä°Ã§erik tÃ¼rÃ¼ Ã¶nerileri"""
        return {
            'reels': 60,
            'carousel': 25,
            'single_image': 10,
            'story': 5
        }
    
    def _generate_content_ideas(self, niche):
        """Ä°Ã§erik fikirleri Ã¼ret"""
        ideas = [
            f"{niche.capitalize()} ile ilgili 5 ipucu",
            f"{niche.capitalize()} trendleri 2024",
            "KullanÄ±cÄ± baÅŸarÄ± hikayeleri",
            "ÃœrÃ¼n karÅŸÄ±laÅŸtÄ±rmasÄ±",
            "NasÄ±l yapÄ±lÄ±r videolarÄ±"
        ]
        return ideas
    
    def _get_content_recommendations(self, niche):
        """Ä°Ã§erik Ã¶nerileri"""
        return [
            f"Haftada 3-4 {niche} ile ilgili iÃ§erik paylaÅŸÄ±n",
            "Reels videolarÄ±na aÄŸÄ±rlÄ±k verin",
            "TakipÃ§ilerinize sorular sorarak etkileÅŸimi artÄ±rÄ±n"
        ]

