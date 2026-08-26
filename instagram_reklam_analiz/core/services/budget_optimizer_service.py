from core.models.campaigns import AdCampaign
from core.ai_agents.budget_optimizer import BudgetOptimizerAgent

class BudgetOptimizationService:
    @staticmethod
    def optimize_campaign(campaign_id, user):
        try:
            campaign = AdCampaign.objects.get(id=campaign_id, instagram_account__user=user)
            if campaign.status != 'active' or campaign.budget is None or campaign.budget <= 0:
                return {'status': 'skipped', 'reason': 'Kampanya aktif değil veya bütçesiz'}
            agent = BudgetOptimizerAgent(campaign, user)
            log_entry = agent.run()
            if log_entry:
                return {'status': 'updated', 'log_id': log_entry.id, 'new_budget': log_entry.new_budget}
            return {'status': 'no_change', 'reason': 'Bütçe değişikliği gerekmiyor'}
        except AdCampaign.DoesNotExist:
            return {'status': 'error', 'error': 'Kampanya bulunamadı veya size ait değil'}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    @staticmethod
    def optimize_all_user_campaigns(user):
        campaigns = AdCampaign.objects.filter(instagram_account__user=user, status='active', budget__isnull=False, budget__gt=0)
        results = []
        for campaign in campaigns:
            results.append(BudgetOptimizationService.optimize_campaign(campaign.id, user))
        return results