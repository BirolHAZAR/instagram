# core/services/ad_ai_analyzer.py

import time
import logging
from typing import Dict, Any
from django.utils import timezone

logger = logging.getLogger(__name__)


class AdAIAnalyzerService:
    """
    Tek bir reklam için tüm AI ajanlarını sırayla çalıştıran servis.
    """
    
    def __init__(self, ad_analysis_obj):
        """
        Args:
            ad_analysis_obj: ReklamAIAnaliz model instance
        """
        self.analysis = ad_analysis_obj
        self.ad = ad_analysis_obj.ad
        self.results = {}
        self.total_agents = 12
        self.completed_agents = 0
    
    def run_all_agents(self) -> Dict[str, Any]:
        """
        Tüm 12 AI ajanını sırayla çalıştırır ve sonuçları kaydeder.
        """
        start_time = time.time()
        
        try:
            # Durumu güncelle
            self._update_status('processing', 0, 'Analiz başlatılıyor...')
            
            # 1. Sentiment Analyzer
            self._run_sentiment_analyzer()
            
            # 2. Content Generator
            self._run_content_generator()
            
            # 3. Hashtag Recommender
            self._run_hashtag_recommender()
            
            # 4. Competitor Analyzer
            self._run_competitor_analyzer()
            
            # 5. Performance Analyzer
            self._run_performance_analyzer()
            
            # 6. Budget Optimizer
            self._run_budget_optimizer()
            
            # 7. Lead Scorer
            self._run_lead_scorer()
            
            # 8. Market Analyzer
            self._run_market_analyzer()
            
            # 9. Auto Responder
            self._run_auto_responder()
            
            # 10. Recommendation Engine
            self._run_recommendation_engine()
            
            # 11. Influencer Connector
            self._run_influencer_connector()
            
            # 12. Error Manager (Son olarak çalışır)
            self._run_error_manager()
            
            # Genel skor hesapla
            self._calculate_overall_score()
            
            # Bitir
            processing_time = time.time() - start_time
            self.analysis.status = 'completed'
            self.analysis.progress = 100
            self.analysis.current_agent = None
            self.analysis.completed_at = timezone.now()
            self.analysis.processing_time = processing_time
            self.analysis.all_results_json = self.results
            self.analysis.save()
            
            logger.info(f"✅ Reklam AI analizi tamamlandı: {self.ad.id} ({processing_time:.2f}s)")
            
            return {
                'status': 'success',
                'overall_score': self.analysis.overall_score,
                'processing_time': processing_time,
                'results': self.results
            }
            
        except Exception as e:
            logger.exception(f"❌ Reklam AI analizi başarısız: {self.ad.id} - {e}")
            self.analysis.status = 'failed'
            self.analysis.error_message = str(e)
            self.analysis.save()
            raise
    
    def _update_status(self, status, progress, current_agent):
        """Analiz durumunu güncelle"""
        self.analysis.status = status
        self.analysis.progress = progress
        self.analysis.current_agent = current_agent
        self.analysis.save(update_fields=['status', 'progress', 'current_agent'])
    
    def _update_progress(self, agent_name):
        """İlerlemeyi güncelle"""
        self.completed_agents += 1
        progress = int((self.completed_agents / self.total_agents) * 100)
        self._update_status('processing', progress, agent_name)
    
    # ============ 12 AI AJANI ============
    
    def _run_sentiment_analyzer(self):
        """1. Duygu Analizi"""
        try:
            self._update_progress('Duygu Analizi')
            
            # Gerçek AI çağrısı (örnek)
            from core.ai_agents.sentiment_analyzer import SentimentAnalyzer
            analyzer = SentimentAnalyzer()
            result = analyzer.analyze_ad_sentiment(self.ad)
            
            # Sonuçları kaydet
            self.analysis.sentiment_score = result.get('score', 0)
            self.analysis.sentiment_label = result.get('label', '')
            self.analysis.sentiment_emotions = result.get('emotions', {})
            self.analysis.sentiment_analysis = result.get('analysis', '')
            
            self.results['sentiment'] = result
            
        except Exception as e:
            logger.error(f"Sentiment Analyzer hatası: {e}")
            self.results['sentiment'] = {'error': str(e)}
    
    def _run_content_generator(self):
        """2. İçerik Analizi"""
        try:
            self._update_progress('İçerik Analizi')
            
            from core.ai_agents.content_generator import ContentGenerator
            generator = ContentGenerator(user=self.user)
            result = generator.analyze_ad_content(self.ad)
            
            self.analysis.content_quality_score = result.get('quality_score', 0)
            self.analysis.content_strengths = result.get('strengths', [])
            self.analysis.content_weaknesses = result.get('weaknesses', [])
            self.analysis.content_suggestions = result.get('suggestions', [])
            
            self.results['content'] = result
            
        except Exception as e:
            logger.error(f"Content Generator hatası: {e}")
            self.results['content'] = {'error': str(e)}
    
    def _run_hashtag_recommender(self):
        """3. Hashtag Analizi"""
        try:
            self._update_progress('Hashtag Analizi')
            
            from core.ai_agents.hashtag_recommender import HashtagRecommender
            recommender = HashtagRecommender()
            result = recommender.analyze_ad_hashtags(self.ad)
            
            self.analysis.hashtag_effectiveness_score = result.get('effectiveness_score', 0)
            self.analysis.recommended_hashtags = result.get('recommended', [])
            self.analysis.hashtag_analysis = result.get('analysis', '')
            
            self.results['hashtag'] = result
            
        except Exception as e:
            logger.error(f"Hashtag Recommender hatası: {e}")
            self.results['hashtag'] = {'error': str(e)}
    
    def _run_competitor_analyzer(self):
        """4. Rakip Analizi"""
        try:
            self._update_progress('Rakip Analizi')
            
            from core.ai_agents.competitor_analyzer import CompetitorAnalyzer
            analyzer = CompetitorAnalyzer()
            result = analyzer.analyze_ad_vs_competitors(self.ad)
            
            self.analysis.competitor_score = result.get('score', 0)
            self.analysis.competitive_advantage = result.get('advantage', '')
            self.analysis.competitor_insights = result.get('insights', [])
            
            self.results['competitor'] = result
            
        except Exception as e:
            logger.error(f"Competitor Analyzer hatası: {e}")
            self.results['competitor'] = {'error': str(e)}
    
    def _run_performance_analyzer(self):
        """5. Performans Analizi"""
        try:
            self._update_progress('Performans Analizi')
            
            from core.ai_agents.performance_analyzer import PerformanceAnalyzer
            analyzer = PerformanceAnalyzer(user=self.user)
            result = analyzer.analyze_ad_performance(self.ad)
            
            self.analysis.performance_score = result.get('score', 0)
            self.analysis.ctr_prediction = result.get('ctr_prediction', 0)
            self.analysis.conversion_prediction = result.get('conversion_prediction', 0)
            self.analysis.performance_insights = result.get('insights', [])
            
            self.results['performance'] = result
            
        except Exception as e:
            logger.error(f"Performance Analyzer hatası: {e}")
            self.results['performance'] = {'error': str(e)}
    
    def _run_budget_optimizer(self):
        """6. Bütçe Optimizasyonu"""
        try:
            self._update_progress('Bütçe Optimizasyonu')
            
            from core.ai_agents.budget_optimizer import BudgetOptimizer
            optimizer = BudgetOptimizer()
            result = optimizer.optimize_ad_budget(self.ad)
            
            self.analysis.budget_efficiency_score = result.get('efficiency_score', 0)
            self.analysis.optimal_budget = result.get('optimal_budget', 0)
            self.analysis.budget_suggestions = result.get('suggestions', [])
            
            self.results['budget'] = result
            
        except Exception as e:
            logger.error(f"Budget Optimizer hatası: {e}")
            self.results['budget'] = {'error': str(e)}
    
    def _run_lead_scorer(self):
        """7. Lead Potansiyeli"""
        try:
            self._update_progress('Lead Skorlama')
            
            from core.ai_agents.lead_scorer import LeadScorer
            scorer = LeadScorer()
            result = scorer.score_ad_lead_potential(self.ad)
            
            self.analysis.lead_potential_score = result.get('score', 0)
            self.analysis.target_audience_analysis = result.get('audience_analysis', [])
            self.analysis.lead_generation_tips = result.get('tips', [])
            
            self.results['lead'] = result
            
        except Exception as e:
            logger.error(f"Lead Scorer hatası: {e}")
            self.results['lead'] = {'error': str(e)}
    
    def _run_market_analyzer(self):
        """8. Pazar Analizi"""
        try:
            self._update_progress('Pazar Analizi')
            
            from core.ai_agents.market_analyzer import MarketAnalyzer
            analyzer = MarketAnalyzer(user=self.user)
            result = analyzer.analyze_ad_market_fit(self.ad)
            
            self.analysis.market_fit_score = result.get('fit_score', 0)
            self.analysis.market_trends = result.get('trends', [])
            self.analysis.market_positioning = result.get('positioning', '')
            
            self.results['market'] = result
            
        except Exception as e:
            logger.error(f"Market Analyzer hatası: {e}")
            self.results['market'] = {'error': str(e)}
    
    def _run_auto_responder(self):
        """9. Otomatik Yanıt Analizi"""
        try:
            self._update_progress('Etkileşim Analizi')
            
            from core.ai_agents.auto_responder import AutoResponder
            responder = AutoResponder()
            result = responder.analyze_ad_comments(self.ad)
            
            self.analysis.comment_sentiment_score = result.get('sentiment_score', 0)
            self.analysis.auto_responses = result.get('suggested_responses', [])
            self.analysis.engagement_strategy = result.get('strategy', '')
            
            self.results['auto_responder'] = result
            
        except Exception as e:
            logger.error(f"Auto Responder hatası: {e}")
            self.results['auto_responder'] = {'error': str(e)}
    
    def _run_recommendation_engine(self):
        """10. Öneri Motoru"""
        try:
            self._update_progress('Öneri Motoru')
            
            from core.ai_agents.recommendation_engine import RecommendationEngine
            engine = RecommendationEngine(user=self.user)
            result = engine.generate_ad_recommendations(
                self.ad, 
                previous_results=self.results
            )
            
            self.analysis.overall_recommendation_score = result.get('score', 0)
            self.analysis.top_recommendations = result.get('recommendations', [])
            self.analysis.action_plan = result.get('action_plan', [])
            
            self.results['recommendations'] = result
            
        except Exception as e:
            logger.error(f"Recommendation Engine hatası: {e}")
            self.results['recommendations'] = {'error': str(e)}
    
    def _run_influencer_connector(self):
        """11. Influencer Bağlantısı"""
        try:
            self._update_progress('Influencer Analizi')
            
            from core.ai_agents.influencer_connector import InfluencerConnector
            connector = InfluencerConnector()
            result = connector.find_influencers_for_ad(self.ad)
            
            self.analysis.influencer_potential_score = result.get('potential_score', 0)
            self.analysis.suggested_influencers = result.get('influencers', [])
            self.analysis.collaboration_ideas = result.get('ideas', [])
            
            self.results['influencer'] = result
            
        except Exception as e:
            logger.error(f"Influencer Connector hatası: {e}")
            self.results['influencer'] = {'error': str(e)}
    
    def _run_error_manager(self):
        """12. Analiz Sağlığı Kontrolü"""
        try:
            self._update_progress('Analiz Sağlığı Kontrolü')
            
            from core.ai_agents.error_manager import ErrorManager
            manager = ErrorManager()
            result = manager.validate_analysis_health(self.results)
            
            self.analysis.analysis_health_score = result.get('health_score', 0)
            self.analysis.warnings = result.get('warnings', [])
            self.analysis.data_quality_notes = result.get('quality_notes', '')
            
            self.results['health_check'] = result
            
        except Exception as e:
            logger.error(f"Error Manager hatası: {e}")
            self.results['health_check'] = {'error': str(e)}
    
    def _calculate_overall_score(self):
        """Tüm skorların ortalamasını hesapla"""
        scores = [
            self.analysis.sentiment_score * 100,  # -1..1 -> 0..100
            self.analysis.content_quality_score,
            self.analysis.hashtag_effectiveness_score,
            self.analysis.competitor_score,
            self.analysis.performance_score,
            self.analysis.budget_efficiency_score,
            self.analysis.lead_potential_score,
            self.analysis.market_fit_score,
            self.analysis.comment_sentiment_score * 100,
            self.analysis.overall_recommendation_score,
            self.analysis.influencer_potential_score,
            self.analysis.analysis_health_score,
        ]
        
        # Sadece 0'dan büyük skorları hesapla
        valid_scores = [s for s in scores if s > 0]
        
        if valid_scores:
            self.analysis.overall_score = sum(valid_scores) / len(valid_scores)
        else:
            self.analysis.overall_score = 0
        
        # Genel özet oluştur
        self.analysis.executive_summary = self._generate_executive_summary()
    
    def _generate_executive_summary(self):
        """Yönetici özeti oluştur"""
        return f"""
        Reklam Analiz Özeti:
        - Genel Skor: {self.analysis.overall_score:.1f}/100
        - Duygu Analizi: {self.analysis.sentiment_label or 'N/A'}
        - İçerik Kalitesi: {self.analysis.content_quality_score:.1f}/100
        - Performans: {self.analysis.performance_score:.1f}/100
        - Bütçe Verimliliği: {self.analysis.budget_efficiency_score:.1f}/100
        - Pazar Uyumu: {self.analysis.market_fit_score:.1f}/100
        """
