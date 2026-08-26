from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class BudgetOptimizationRule(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budget_rules')
    platform = models.ForeignKey('core.Platform', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    min_budget = models.DecimalField(max_digits=12, decimal_places=2)
    max_budget = models.DecimalField(max_digits=12, decimal_places=2)
    adjustment_step = models.DecimalField(max_digits=10, decimal_places=2, default=5.00)
    roas_target = models.FloatField(default=2.0)
    lookback_hours = models.IntegerField(default=24)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['user', 'platform', 'name']


class BudgetOptimizationLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='budget_logs')
    reklam = models.ForeignKey('core.Ad', on_delete=models.CASCADE, related_name='budget_logs')
    platform_code = models.CharField(max_length=20)
    rule = models.ForeignKey(BudgetOptimizationRule, on_delete=models.SET_NULL, null=True, blank=True)
    old_budget = models.DecimalField(max_digits=12, decimal_places=2)
    new_budget = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.TextField()
    ai_confidence = models.FloatField(default=0.0)
    success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True)
    performance_data = models.JSONField(default=dict, blank=True)
    is_reverted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['user', '-created_at']), models.Index(fields=['reklam', '-created_at'])]

    def __str__(self):
        return f"{self.user.username} - {self.reklam} - {self.created_at.date()}"
