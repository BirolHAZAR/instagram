from celery import shared_task


@shared_task(bind=True, name="core.tasks.analysis_tasks.analyze_ad")
def analyze_ad(self, ad_id, user_id=None):
    from core.tasks.ai_analysis import analyze_single_ad_with_all_agents

    return analyze_single_ad_with_all_agents.run(ad_id, user_id)


@shared_task(name="core.tasks.analysis_tasks.analyze_multiple_ads")
def analyze_multiple_ads(ad_ids):
    from core.tasks.ai_analysis import analyze_multiple_ads as legacy_task

    return legacy_task.run(ad_ids)


@shared_task(name="core.tasks.analysis_tasks.scan_anomalies_for_all_users")
def scan_anomalies_for_all_users():
    from core.services.account_lifecycle import active_user_queryset
    from core.services.anomaly_detector import AnomalyDetector

    total = 0
    for user in active_user_queryset():
        detector = AnomalyDetector(user=user)
        result = detector.scan()
        if isinstance(result, int):
            total += result
    return {"success": True, "alerts_created": total}
