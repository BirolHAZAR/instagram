# core/tasks/budget.py
import logging
from celery import shared_task
from core.models.campaigns import AdCampaign
from core.services.budget_optimization_service import BudgetOptimizationService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def run_budget_optimization(self, campaign_id):
    try:
        campaign = AdCampaign.objects.get(id=campaign_id, is_active=True)
        service = BudgetOptimizationService(campaign)
        result = service.optimize_and_apply()
        return result
    except Exception as e:
        self.retry(exc=e, countdown=60)
        raise


@shared_task(name="core.tasks.budget.optimize_all_campaign_budgets")
def optimize_all_campaign_budgets():
    results = BudgetOptimizationService.optimize_all_active_campaigns()
    logger.info(f"Bütçe optimizasyonu tamamlandı: {results}")
    return results