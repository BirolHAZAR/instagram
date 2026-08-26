from core.services.ad_entity_service import sync_ad_entity_tree
from core.services.metric_history_service import save_metric_tree


def sync_ad_with_metrics(platform_account, payload):
    entity_result = sync_ad_entity_tree(platform_account, payload)
    metric_result = save_metric_tree(entity_result, payload)

    return {
        "entities": entity_result,
        "metrics": metric_result,
        "campaign": entity_result.get("campaign"),
        "ad_group": entity_result.get("ad_group"),
        "ad": entity_result.get("ad"),
    }