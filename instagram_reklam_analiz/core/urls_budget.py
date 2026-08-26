from django.urls import path
from core.views import budget_optimization

urlpatterns = [
    path('budget-optimization/', budget_optimization.optimizasyon_kurallari, name='budget_optimization'),
    path('optimizasyon-kurallari/', budget_optimization.optimizasyon_kurallari, name='optimizasyon_kurallari'),
    path('butce-optimizasyonu/', budget_optimization.optimizasyon_kurallari, name='optimizasyon_kurallari_legacy'),
    path('butce-optimizasyonu/uygula/', budget_optimization.apply_rules_to_campaigns, name='apply_rules_to_campaigns'),
    path('butce-optimizasyonu/sunum/', budget_optimization.budget_sunum, name='budget_sunum'),
    path('reklamlara-uygula/', budget_optimization.apply_rules_to_campaigns, name='apply_rules_to_campaigns_legacy'),
    path('optimizasyon-gecmisi/', budget_optimization.optimization_history, name='optimization_history'),
    path('ajax/reklams/', budget_optimization.ajax_get_reklams, name='ajax_get_reklams'),
    path('ajax/optimize/', budget_optimization.ajax_optimize_reklam, name='ajax_optimize_reklam'),
    path('ajax/remove/', budget_optimization.ajax_remove_reklam, name='ajax_remove_reklam'),
    path('ajax/update-selection/', budget_optimization.ajax_update_selection, name='ajax_update_selection'),
    path('ajax/reklams-simple/', budget_optimization.ajax_get_reklams_simple, name='ajax_reklams_simple'),
    path('ajax/get-accounts/', budget_optimization.ajax_get_accounts, name='ajax_get_accounts'),
]
