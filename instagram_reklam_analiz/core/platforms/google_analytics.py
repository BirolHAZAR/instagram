class GoogleAnalyticsAPI:
    def __init__(self, account):
        self.account = account
        self.connection = getattr(account, "connection", None)
        self.access_token = (
            getattr(account, "access_token", None)
            or getattr(self.connection, "access_token", None)
        )

    def get_properties(self):
        property_id = self.account.extra_data.get("property_id") or self.account.account_id
        property_name = (
            self.account.extra_data.get("property_name")
            or self.account.account_name
            or f"GA4 Property {property_id}"
        )
        return [
            {
                "property_id": str(property_id),
                "property_name": property_name,
                "property_type": "GA4",
                "currency": self.account.extra_data.get("currency", "TRY"),
                "timezone": self.account.extra_data.get("timezone"),
            }
        ]

    def get_daily_metrics(self, property_id, since_days=30):
        return []

    def get_landing_page_metrics(self, property_id, since_days=30):
        return []
