import requests


class MarketplaceConnectionError(Exception):
    """Pazaryeri kimlik bilgileri doğrulanamadığında oluşur."""


def _response_error(response):
    try:
        payload = response.json()
        detail = payload.get("message") or payload.get("error_description") or payload.get("error")
        if isinstance(detail, dict):
            detail = detail.get("message") or str(detail)
    except (ValueError, AttributeError):
        detail = ""
    return str(detail or f"HTTP {response.status_code}")[:300]


def verify_marketplace_credentials(account):
    """Kimlik bilgilerini pazaryerinin resmi canlı API'sinde doğrular."""
    code = account.marketplace.code
    key = (account.api_key_encrypted or "").strip()
    secret = (account.api_secret_encrypted or "").strip()
    seller_id = (account.seller_id or "").strip()
    if not key or not secret:
        raise MarketplaceConnectionError("API Key ve API Secret zorunludur.")

    try:
        if code == "trendyol":
            if not seller_id:
                raise MarketplaceConnectionError("Trendyol için Supplier ID zorunludur.")
            response = requests.get(
                f"https://apigw.trendyol.com/integration/product/sellers/{seller_id}/products",
                params={"page": 0, "size": 1}, auth=(key, secret),
                headers={"User-Agent": f"{seller_id} - OctoAds"}, timeout=20,
            )
        elif code == "hepsiburada":
            response = requests.post(
                "https://api.hepsiburada.com/v3/auth",
                json={"client_id": key, "client_secret": secret, "grant_type": "client_credentials"},
                timeout=20,
            )
        elif code == "n11":
            response = requests.get(
                "https://api.n11.com/ms/product-query", params={"page": 0, "size": 1},
                headers={"appkey": key, "appsecret": secret}, timeout=20,
            )
        else:
            raise MarketplaceConnectionError("Bu pazaryeri için canlı bağlantı desteği bulunmuyor.")
    except requests.RequestException as exc:
        raise MarketplaceConnectionError(f"Pazaryeri API'sine ulaşılamadı: {exc}") from exc

    if not response.ok:
        raise MarketplaceConnectionError(f"Kimlik bilgileri doğrulanamadı: {_response_error(response)}")
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if code == "hepsiburada" and not (payload.get("access_token") or payload.get("token")):
        raise MarketplaceConnectionError("Hepsiburada erişim anahtarı üretmedi; kimlik bilgilerini kontrol edin.")
    return {"connection_status": "verified", "connection_platform": code}
