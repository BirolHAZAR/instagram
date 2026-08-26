from core.models import Ad
from core.ai_agents.budget_optimizer import BudgetOptimizer


def optimize_reklam_budget(reklam_id, user, rule=None):
    ad = Ad.objects.get(id=reklam_id, user=user, source_type="OWN")
    return BudgetOptimizer(ad, user, rule).analyze()


def get_optimizable_reklams(user):
    return Ad.objects.filter(user=user, source_type="OWN", is_active=True)


class BudgetOptimizationService:
    def __init__(self, user):
        self.user = user

    def optimize_reklam_budget(self, reklam_id, rule=None):
        return optimize_reklam_budget(reklam_id, self.user, rule)

    def get_optimizable_reklams(self):
        return get_optimizable_reklams(self.user)
