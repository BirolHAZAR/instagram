from dataclasses import dataclass
from core.models import AdMetricHistory
from core.services.performance_metrics import aggregate_metric_queryset


@dataclass
class BudgetOptimizationResult:
    recommended_action: str
    reason: str
    confidence: float


class BudgetOptimizer:
    """V2 Budget Optimizer: Ad + AdMetricHistory kullanır."""
    def __init__(self, ad, user, rule=None):
        self.ad = ad
        self.user = user
        self.rule = rule

    def analyze(self):
        totals = aggregate_metric_queryset(AdMetricHistory.objects.filter(ad=self.ad))
        spend = float(totals.get('spend') or 0)
        roas = float(totals.get('roas') or 0)
        if roas >= 3:
            return BudgetOptimizationResult("increase", f"ROAS {roas:.2f}x; kontrollü bütçe artırılabilir.", 0.86)
        if spend > 0 and roas < 1:
            return BudgetOptimizationResult("decrease", f"ROAS {roas:.2f}x; harcama verimsiz görünüyor.", 0.82)
        return BudgetOptimizationResult("watch", "Yeterli sinyal yok; izlenmeli.", 0.65)
