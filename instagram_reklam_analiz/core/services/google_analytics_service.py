import json
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import DateRange, Metric, Dimension, RunReportRequest
from google.oauth2 import service_account

def fetch_ga4_report(property_id, credentials_json):
    """
    GA4 property'sinden son 7 günlük temel metrikleri alır.
    - property_id: string, GA4 mülk ID (örn. "123456789")
    - credentials_json: string, hizmet hesabı JSON'unun içeriği
    """
    try:
        creds = service_account.Credentials.from_service_account_info(
            json.loads(credentials_json),
            scopes=['https://www.googleapis.com/auth/analytics.readonly']
        )
        client = BetaAnalyticsDataClient(credentials=creds)
        request = RunReportRequest(
            property=f"properties/{property_id}",
            dimensions=[Dimension(name="date")],
            metrics=[
                Metric(name="activeUsers"),
                Metric(name="screenPageViews"),
                Metric(name="sessions"),
                Metric(name="bounceRate"),
            ],
            date_ranges=[DateRange(start_date="7daysAgo", end_date="today")],
        )
        response = client.run_report(request)
        results = []
        for row in response.rows:
            results.append({
                "date": row.dimension_values[0].value,
                "active_users": int(row.metric_values[0].value),
                "page_views": int(row.metric_values[1].value),
                "sessions": int(row.metric_values[2].value),
                "bounce_rate": float(row.metric_values[3].value),
            })
        return results
    except Exception as e:
        return {"error": str(e)}