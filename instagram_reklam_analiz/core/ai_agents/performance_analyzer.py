# core/ai_agents/performance_analyzer.py
"""
Instagram Reklam Performans Analizi ModÃ¼lÃ¼
Yapay Zeka ile reklam kampanyalarÄ±nÄ±n performansÄ±nÄ± analiz eder
"""

import json
import re
import numpy as np
from datetime import datetime, timedelta
from django.utils import timezone
from django.conf import settings
from core.services.openai_usage import record_openai_token_usage

# OpenAI entegrasyonu (opsiyonel)
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


class PerformanceAnalyzer:
    """
    Instagram reklam kampanyalarÄ±nÄ±n performansÄ±nÄ± analiz eden sÄ±nÄ±f
    """
    
    def __init__(self, api_key=None, user=None, organization=None):
        self.user = user
        self.organization = organization
        """Analiz sÄ±nÄ±fÄ±nÄ± baÅŸlat"""
        self.api_key = api_key or getattr(settings, 'OPENAI_API_KEY', None)
        self.use_openai = OPENAI_AVAILABLE and self.api_key
        self.client = OpenAI(api_key=self.api_key, timeout=60, max_retries=2) if self.use_openai else None
    
    def analyze_campaign_performance(self, campaign_data, metrics_data):
        """
        Kampanya performansÄ±nÄ± analiz et
        
        Args:
            campaign_data: Kampanya bilgileri (dict)
            metrics_data: Metrik verileri (list of dict veya QuerySet)
        
        Returns:
            dict: Analiz sonuÃ§larÄ±
        """
        # Metrikleri hazÄ±rla
        metrics_list = self._prepare_metrics(metrics_data)
        
        if not metrics_list:
            return self._get_empty_analysis(campaign_data)
        
        # Performans skorunu hesapla
        performance_score = self._calculate_performance_score(metrics_list)
        
        # GÃ¼Ã§lÃ¼ ve zayÄ±f yÃ¶nleri belirle
        strengths, weaknesses = self._identify_strengths_weaknesses(metrics_list)
        
        # Trend analizi
        trends = self._analyze_trends(metrics_list)
        
        # AI ile derinlemesine analiz
        ai_analysis = self._get_ai_insights(campaign_data, metrics_list)
        
        # Ã–neriler Ã¼ret
        recommendations = self._generate_recommendations(metrics_list, performance_score)
        
        return {
            'success': True,
            'performance_score': performance_score,
            'strengths': strengths,
            'weaknesses': weaknesses,
            'trends': trends,
            'ai_analysis': ai_analysis,
            'recommendations': recommendations,
            'analyzed_at': timezone.now().isoformat()
        }
    
    def analyze_instagram_account(self, account_data, media_stats):
        """
        Instagram hesabÄ± performansÄ±nÄ± AI ile analiz et
        
        Args:
            account_data: Hesap bilgileri (dict)
            media_stats: Medya istatistikleri (dict)
        
        Returns:
            dict: Analiz sonuÃ§larÄ±
        """
        if self.use_openai:
            return self._get_ai_account_analysis(account_data, media_stats)
        else:
            return "OpenAI kullanilamiyor; hesap analizi icin gercek AI ciktisi uretilemedi."
    
    def generate_recommendations(self, performance_data):
        """
        AI ile Ã¶zel Ã¶neriler Ã¼ret
        
        Args:
            performance_data: Performans verileri (dict)
        
        Returns:
            dict: Ã–neriler
        """
        if self.use_openai:
            return self._get_ai_recommendations(performance_data)
        else:
            return {"recommendations": [], "error": "OpenAI kullanilamiyor; sahte oneri uretilmedi."}
    
    def predict_performance(self, historical_data, future_days=30):
        """
        Gelecek performans tahmini yap
        
        Args:
            historical_data: GeÃ§miÅŸ veriler (list of dict)
            future_days: Tahmin edilecek gÃ¼n sayÄ±sÄ±
        
        Returns:
            dict: Tahmin sonuÃ§larÄ±
        """
        if len(historical_data) < 7:
            return self._get_basic_prediction(historical_data, future_days)
        
        # Basit trend analizi
        recent_ctr = [d.get('ctr', 0) for d in historical_data[-7:]]
        recent_engagement = [d.get('engagement_rate', 0) for d in historical_data[-7:]]
        
        # Trend yÃ¶nÃ¼
        ctr_trend = 'up' if len(recent_ctr) > 1 and recent_ctr[-1] > recent_ctr[0] else 'down'
        engagement_trend = 'up' if len(recent_engagement) > 1 and recent_engagement[-1] > recent_engagement[0] else 'down'
        
        # Ortalama deÄŸerler
        avg_ctr = np.mean(recent_ctr) if recent_ctr else 0
        avg_engagement = np.mean(recent_engagement) if recent_engagement else 0
        
        # Tahmini deÄŸerler
        predicted_ctr = avg_ctr * (1.05 if ctr_trend == 'up' else 0.95)
        predicted_engagement = avg_engagement * (1.05 if engagement_trend == 'up' else 0.95)
        
        return {
            'success': True,
            'predicted_ctr': round(predicted_ctr, 2),
            'predicted_engagement': round(predicted_engagement, 2),
            'trend': 'yÃ¼kseliÅŸ' if ctr_trend == 'up' else 'dÃ¼ÅŸÃ¼ÅŸ',
            'confidence': 75 if len(historical_data) > 30 else 60,
            'recommended_budget_increase': 20 if ctr_trend == 'up' else 10,
            'future_days': future_days
        }
    
    def compare_campaigns(self, campaigns_data):
        """
        Birden fazla kampanyayÄ± karÅŸÄ±laÅŸtÄ±r
        
        Args:
            campaigns_data: Kampanya verileri listesi
        
        Returns:
            dict: KarÅŸÄ±laÅŸtÄ±rma sonuÃ§larÄ±
        """
        if not campaigns_data:
            return {'success': False, 'error': 'Kampanya verisi yok'}
        
        # En iyi kampanyayÄ± bul
        best_campaign = max(campaigns_data, key=lambda x: x.get('performance_score', 0))
        worst_campaign = min(campaigns_data, key=lambda x: x.get('performance_score', 0))
        
        # Ortalama deÄŸerler
        avg_score = np.mean([c.get('performance_score', 0) for c in campaigns_data])
        
        return {
            'success': True,
            'total_campaigns': len(campaigns_data),
            'average_score': round(avg_score, 1),
            'best_campaign': {
                'name': best_campaign.get('name', 'Bilinmiyor'),
                'score': best_campaign.get('performance_score', 0),
                'ad_type': best_campaign.get('ad_type', 'Bilinmiyor')
            },
            'worst_campaign': {
                'name': worst_campaign.get('name', 'Bilinmiyor'),
                'score': worst_campaign.get('performance_score', 0),
                'ad_type': worst_campaign.get('ad_type', 'Bilinmiyor')
            },
            'recommendations': self._get_comparison_recommendations(best_campaign, worst_campaign)
        }
    
    def _prepare_metrics(self, metrics_data):
        """Metrik verilerini numpy array'e dÃ¶nÃ¼ÅŸtÃ¼r"""
        metrics_list = []
        
        # QuerySet ise values'a Ã§evir
        if hasattr(metrics_data, 'values'):
            metrics_data = metrics_data.values()
        
        for metric in metrics_data:
            # Decimal deÄŸerleri float'a Ã§evir
            ctr = float(metric.get('ctr', 0)) if metric.get('ctr') else 0
            engagement = float(metric.get('engagement_rate', 0)) if metric.get('engagement_rate') else 0
            cpc = float(metric.get('cost_per_click', 0)) if metric.get('cost_per_click') else 0
            
            metrics_list.append({
                'impressions': int(metric.get('impressions', 0)),
                'clicks': int(metric.get('clicks', 0)),
                'ctr': ctr,
                'engagement_rate': engagement,
                'cost_per_click': cpc,
                'likes': int(metric.get('likes', 0)),
                'comments': int(metric.get('comments', 0)),
                'shares': int(metric.get('shares', 0))
            })
        
        return metrics_list
    
    def _calculate_performance_score(self, metrics_list):
        """Performans skorunu hesapla (0-100 arasÄ±)"""
        if not metrics_list:
            return 0
        
        # Son 7 gÃ¼n veya tÃ¼m veriler
        recent_metrics = metrics_list[-7:] if len(metrics_list) >= 7 else metrics_list
        
        # Metrik aÄŸÄ±rlÄ±klarÄ±
        weights = {
            'ctr': 0.30,
            'engagement_rate': 0.30,
            'cost_per_click': 0.20,
            'likes_per_impression': 0.20
        }
        
        scores = []
        for metric in recent_metrics:
            # CTR skoru (ideal CTR: %1-3 arasÄ±)
            ctr = metric.get('ctr', 0)
            ctr_score = min(100, (ctr / 3) * 100) if ctr > 0 else 0
            
            # EtkileÅŸim skoru (ideal: %2-5 arasÄ±)
            engagement = metric.get('engagement_rate', 0)
            engagement_score = min(100, (engagement / 5) * 100) if engagement > 0 else 0
            
            # CPC skoru (dÃ¼ÅŸÃ¼k CPC iyidir)
            cpc = metric.get('cost_per_click', 0)
            cpc_score = max(0, 100 - (cpc * 20)) if cpc > 0 else 50
            
            # BeÄŸeni/EtkileÅŸim oranÄ±
            likes = metric.get('likes', 0)
            impressions = metric.get('impressions', 1)
            likes_ratio = (likes / impressions) * 100
            likes_score = min(100, likes_ratio * 10)
            
            # AÄŸÄ±rlÄ±klÄ± toplam
            weighted_score = (
                ctr_score * weights['ctr'] +
                engagement_score * weights['engagement_rate'] +
                cpc_score * weights['cost_per_click'] +
                likes_score * weights['likes_per_impression']
            )
            scores.append(weighted_score)
        
        return round(np.mean(scores), 1)
    
    def _identify_strengths_weaknesses(self, metrics_list):
        """GÃ¼Ã§lÃ¼ ve zayÄ±f yÃ¶nleri belirle"""
        strengths = []
        weaknesses = []
        
        if not metrics_list:
            return strengths, weaknesses
        
        # Son 7 gÃ¼nÃ¼n ortalamalarÄ±
        recent = metrics_list[-7:] if len(metrics_list) >= 7 else metrics_list
        
        avg_ctr = np.mean([m.get('ctr', 0) for m in recent])
        avg_engagement = np.mean([m.get('engagement_rate', 0) for m in recent])
        avg_cpc = np.mean([m.get('cost_per_click', 0) for m in recent if m.get('cost_per_click', 0) > 0])
        total_likes = sum([m.get('likes', 0) for m in recent])
        total_comments = sum([m.get('comments', 0) for m in recent])
        
        # SektÃ¶r ortalamalarÄ± (Ã¶rnek deÄŸerler)
        industry_avg_ctr = 0.89
        industry_avg_engagement = 1.5
        industry_avg_cpc = 0.50
        
        # CTR deÄŸerlendirmesi
        if avg_ctr > industry_avg_ctr:
            strengths.append(f"TÄ±klama oranÄ± (CTR) sektÃ¶r ortalamasÄ±nÄ±n %{((avg_ctr/industry_avg_ctr - 1)*100):.0f} Ã¼zerinde")
        elif avg_ctr < industry_avg_ctr:
            weaknesses.append(f"TÄ±klama oranÄ± (CTR) sektÃ¶r ortalamasÄ±nÄ±n altÄ±nda (%{avg_ctr:.2f})")
        
        # EtkileÅŸim deÄŸerlendirmesi
        if avg_engagement > industry_avg_engagement:
            strengths.append(f"EtkileÅŸim oranÄ± sektÃ¶r ortalamasÄ±nÄ±n Ã¼zerinde (%{avg_engagement:.2f})")
        elif avg_engagement < industry_avg_engagement:
            weaknesses.append(f"EtkileÅŸim oranÄ± dÃ¼ÅŸÃ¼k, iÃ§erikler yeniden deÄŸerlendirilmeli")
        
        # CPC deÄŸerlendirmesi
        if avg_cpc and avg_cpc < industry_avg_cpc:
            strengths.append(f"TÄ±klama baÅŸÄ± maliyet (CPC) sektÃ¶r ortalamasÄ±nÄ±n altÄ±nda (â‚º{avg_cpc:.2f})")
        elif avg_cpc and avg_cpc > industry_avg_cpc:
            weaknesses.append(f"TÄ±klama baÅŸÄ± maliyet yÃ¼ksek (â‚º{avg_cpc:.2f}), hedefleme iyileÅŸtirilmeli")
        
        # BeÄŸeni/Yorum oranÄ±
        if total_comments > 0 and total_likes / total_comments < 20:
            strengths.append("TakipÃ§ilerinizle gÃ¼Ã§lÃ¼ bir etkileÅŸiminiz var (yorum oranÄ± yÃ¼ksek)")
        elif total_likes > 0 and total_comments == 0:
            weaknesses.append("Yorum etkileÅŸiminiz dÃ¼ÅŸÃ¼k, takipÃ§ilerinizle daha fazla iletiÅŸime geÃ§in")
        
        # En az 3 madde olmasÄ±nÄ± saÄŸla
        if len(strengths) < 3:
            strengths.append("ReklamlarÄ±nÄ±z dÃ¼zenli olarak yayÄ±nlanÄ±yor")
            strengths.append("Hedef kitlenizle uyumlu iÃ§erikler Ã¼retiyorsunuz")
        
        if len(weaknesses) < 3:
            weaknesses.append("Reklam metinlerinizi gÃ¼Ã§lendirebilirsiniz")
            weaknesses.append("GÃ¶rsel kalitesini artÄ±rabilirsiniz")
        
        return strengths[:5], weaknesses[:5]
    
    def _analyze_trends(self, metrics_list):
        """Trend analizi yap"""
        if len(metrics_list) < 3:
            return {'direction': 'stable', 'message': 'Yeterli veri yok'}
        
        # Son 7 gÃ¼n vs Ã¶nceki 7 gÃ¼n
        recent = metrics_list[-7:] if len(metrics_list) >= 14 else metrics_list[:len(metrics_list)//2]
        previous = metrics_list[-14:-7] if len(metrics_list) >= 14 else []
        
        if not previous:
            return {'direction': 'stable', 'message': 'Trend analizi iÃ§in daha fazla veri gerekli'}
        
        recent_ctr = np.mean([m.get('ctr', 0) for m in recent])
        previous_ctr = np.mean([m.get('ctr', 0) for m in previous])
        
        if recent_ctr > previous_ctr * 1.1:
            direction = 'up'
            message = 'CTR deÄŸerinde yÃ¼kseliÅŸ trendi gÃ¶rÃ¼lÃ¼yor'
        elif recent_ctr < previous_ctr * 0.9:
            direction = 'down'
            message = 'CTR deÄŸerinde dÃ¼ÅŸÃ¼ÅŸ trendi var, dikkatli olun'
        else:
            direction = 'stable'
            message = 'CTR deÄŸerlerinde istikrarlÄ± seyir'
        
        return {
            'direction': direction,
            'message': message,
            'recent_ctr': round(recent_ctr, 2),
            'previous_ctr': round(previous_ctr, 2),
            'change_percent': round(((recent_ctr - previous_ctr) / previous_ctr) * 100, 1) if previous_ctr > 0 else 0
        }
    
    def _get_ai_insights(self, campaign_data, metrics_list):
        """AI ile derinlemesine analiz yap"""
        # OpenAI API kullanÄ±mÄ±
        if OPENAI_AVAILABLE and self.api_key:
            try:
                prompt = self._build_analysis_prompt(campaign_data, metrics_list)
                from core.services.ai_gateway import create_chat_completion
                response = create_chat_completion(
                    client=self.client, tariff_key="performance-insights",
                    user=self.user, organization=self.organization,
                    reference="performance_analyzer.insights",
                    model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                    messages=[
                        {"role": "system", "content": "Sen bir Instagram reklam uzmanÄ±sÄ±n. Reklam performansÄ±nÄ± detaylÄ± analiz ediyorsun."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=500,
                    temperature=0.7
                )
                return response.choices[0].message.content
            except Exception as e:
                pass
        
        # OpenAI kullanilamadiginda yalnizca mevcut metriklerden ozet don.
        recent_metrics = metrics_list[-7:] if len(metrics_list) >= 7 else metrics_list
        avg_ctr = np.mean([m.get('ctr', 0) for m in recent_metrics])
        avg_engagement = np.mean([m.get('engagement_rate', 0) for m in recent_metrics])
        impressions = sum([m.get('impressions', 0) for m in recent_metrics])
        clicks = sum([m.get('clicks', 0) for m in recent_metrics])
        return (
            f"- Kampanya: {campaign_data.get('campaign_name', 'Kampanya')}\n"
            f"- Ortalama CTR: %{avg_ctr:.2f}\n"
            f"- Ortalama etkileÅŸim orani: %{avg_engagement:.2f}\n"
            f"- Toplam gosterim: {impressions:,}\n"
            f"- Toplam tiklama: {clicks:,}\n"
            "- OpenAI kapali veya kullanilamiyor; bu bolum yalnizca metrik ozeti icerir."
        )
    
    def _get_ai_account_analysis(self, account_data, media_stats):
        """AI ile hesap analizi"""
        return "Hesap analizi icin OpenAI prompt akisi bu modulde etkin degil."
    
    def _get_ai_recommendations(self, performance_data):
        """AI ile Ã¶zel Ã¶neriler"""
        return {"recommendations": [], "error": "Oneri uretimi kampanya AI onerisi akisi uzerinden yapilmalidir."}
    
    def _get_basic_prediction(self, historical_data, future_days):
        """Basit tahmin (yetersiz veri durumunda)"""
        return {
            'success': True,
            'predicted_ctr': 0.85,
            'predicted_engagement': 1.2,
            'trend': 'bilinmiyor',
            'confidence': 40,
            'recommended_budget_increase': 10,
            'future_days': future_days,
            'warning': 'Yeterli geÃ§miÅŸ veri yok, tahmin dÃ¼ÅŸÃ¼k gÃ¼venilirliktedir'
        }
    
    def _get_comparison_recommendations(self, best_campaign, worst_campaign):
        """KarÅŸÄ±laÅŸtÄ±rma Ã¶nerileri"""
        return [
            f"En iyi performans gÃ¶steren kampanya '{best_campaign.get('name')}', {best_campaign.get('ad_type')} reklam tÃ¼rÃ¼nÃ¼ kullanÄ±yor",
            f"BaÅŸarÄ±sÄ±z kampanyanÄ±n hedefleme ayarlarÄ±nÄ± gÃ¶zden geÃ§irin",
            f"En iyi kampanyanÄ±n gÃ¶rsel/metin stilini diÄŸer kampanyalara da uyarlayÄ±n"
        ]
    
    def _get_empty_analysis(self, campaign_data):
        """BoÅŸ analiz (veri yoksa)"""
        return {
            'success': False,
            'performance_score': 0,
            'strengths': ['HenÃ¼z yeterli veri yok'],
            'weaknesses': ['Veri toplanmasÄ± bekleniyor'],
            'trends': {'direction': 'unknown', 'message': 'Yeterli veri yok'},
            'ai_analysis': 'Kampanya henÃ¼z yeterli veriye sahip deÄŸil. Veriler toplandÄ±kÃ§a analiz yapÄ±labilecektir.',
            'recommendations': [
                {'type': 'general', 'title': 'Veri Toplama', 'description': 'KampanyanÄ±n devam etmesini bekleyin, daha fazla veri toplandÄ±ÄŸÄ±nda detaylÄ± analiz yapÄ±labilecektir.', 'priority': 'low', 'expected_impact': 0}
            ],
            'analyzed_at': timezone.now().isoformat()
        }
    
    def _build_analysis_prompt(self, campaign_data, metrics_list):
        """AI analiz prompt'u oluÅŸtur"""
        recent_metrics = metrics_list[-14:] if len(metrics_list) >= 14 else metrics_list
        total_impressions = sum([m.get('impressions', 0) for m in recent_metrics])
        total_clicks = sum([m.get('clicks', 0) for m in recent_metrics])
        avg_ctr = np.mean([m.get('ctr', 0) for m in recent_metrics])
        avg_engagement = np.mean([m.get('engagement_rate', 0) for m in recent_metrics])
        
        prompt = f"""
Bir Instagram reklam kampanyasÄ±nÄ±n performansÄ±nÄ± analiz et.

KAMPANYA BÄ°LGÄ°LERÄ°:
- Kampanya AdÄ±: {campaign_data.get('campaign_name', 'Bilinmiyor')}
- Reklam TÃ¼rÃ¼: {campaign_data.get('ad_type', 'Bilinmiyor')}
- BÃ¼tÃ§e: {campaign_data.get('budget', 0)} TL

PERFORMANS METRÄ°KLERÄ° (Son 14 gÃ¼n):
- Toplam GÃ¶sterim: {total_impressions:,}
- Toplam TÄ±klanma: {total_clicks:,}
- Ortalama TÄ±klama OranÄ± (CTR): %{avg_ctr:.2f}
- Ortalama EtkileÅŸim OranÄ±: %{avg_engagement:.2f}

LÃ¼tfen kÄ±sa ve Ã¶z bir analiz yap:
1. Performans deÄŸerlendirmesi
2. 2-3 iyileÅŸtirme Ã¶nerisi
3. Genel puan (0-100 arasÄ±)

Analizi TÃ¼rkÃ§e yap.
"""
        return prompt

