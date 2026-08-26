# core/tasks/budget_tasks.py
"""Bütçe optimizasyon görevleri."""

from celery import shared_task


@shared_task(bind=True, max_retries=2, name="core.tasks.budget_tasks.apply_budget_rule")
def apply_budget_rule(self, campaign_id):
    from core.tasks.budget import run_budget_optimization

    return run_budget_optimization.run(campaign_id)


@shared_task(name="core.tasks.budget_tasks.run_budget_optimizer")
def run_budget_optimizer():
    from core.tasks.budget import optimize_all_campaign_budgets

    return optimize_all_campaign_budgets.run()
