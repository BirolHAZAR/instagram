import json
from datetime import datetime, timedelta
import requests
from django.conf import settings


def _sanitize_error_text(text, token):
    text = str(text or "")
    token = str(token or "")
    if token:
        text = text.replace(token, "[ACCESS_TOKEN]")
    return text


class InstagramAPI:
   

    def __init__(self, access_token=None):
        self.access_token = access_token or getattr(settings, 'INSTAGRAM_ACCESS_TOKEN', '')
        self.base_url = "https://graph.instagram.com"
        self.graph_url = getattr(settings, "FACEBOOK_GRAPH_URL", "https://graph.facebook.com/v25.0")

    def _request(self, url, params=None, method='GET', data=None):
        params = params or {}
        params['access_token'] = self.access_token
        resp = None
        try:
            if method == 'GET':
                resp = requests.get(url, params=params, timeout=30)
            else:
                resp = requests.post(url, params=params, data=data, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            response_body = ""
            if resp is not None:
                try:
                    response_body = resp.text
                except Exception:
                    response_body = ""
            error_text = _sanitize_error_text(str(e), self.access_token)
            response_body = _sanitize_error_text(response_body, self.access_token)
            if response_body:
                error_text = f"{error_text} | response={response_body[:1000]}"
            return {'error': error_text, 'status_code': getattr(resp, 'status_code', 0)}

    def get_user_info(self, user_id="me"):
        return self._request(f"{self.base_url}/{user_id}", {'fields': 'id,username,account_type,media_count'})

    def get_user_media(self, user_id="me", limit=50):
        return self._request(f"{self.base_url}/{user_id}/media", {'fields': 'id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count', 'limit': limit})

    def get_business_accounts(self):
        return self._request(f"{self.graph_url}/me/accounts", {'fields': 'id,name,instagram_business_account,access_token'})

    def get_ads_insights(self, ad_account_id, since_days=30):
        since = (datetime.now() - timedelta(days=since_days)).strftime('%Y-%m-%d')
        until = datetime.now().strftime('%Y-%m-%d')
        return self._request(
            f"{self.graph_url}/act_{ad_account_id}/insights",
            {
                'fields': 'campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,impressions,clicks,ctr,cpc,cpm,spend,reach,frequency,actions,action_values,purchase_roas,website_purchase_roas,date_start,date_stop',
                'time_range': json.dumps({'since': since, 'until': until}),
                'time_increment': 1,
                'level': 'ad',
                'limit': 500,
            },
        )

    def get_competitor_ads(self, competitor=None):
        """Legacy metod. Rakip reklamları artık Ad(source_type='COMPETITOR') olarak saklanır."""
        return []

    def publish_instagram_post(self, instagram_business_id, image_url, caption):
        creation = self._request(f"{self.graph_url}/{instagram_business_id}/media", method='POST', data={'image_url': image_url, 'caption': caption})
        if 'error' in creation:
            return creation
        creation_id = creation.get('id')
        if not creation_id:
            return {'error': 'Container oluşturulamadı'}
        return self._request(f"{self.graph_url}/{instagram_business_id}/media_publish", method='POST', data={'creation_id': creation_id})

    def publish_instagram_carousel(self, instagram_business_id, image_urls, caption):
        image_urls = [str(url).strip() for url in (image_urls or []) if str(url).strip()]
        if not 2 <= len(image_urls) <= 10:
            return {'error': 'Instagram carousel 2 ile 10 görsel içermelidir.'}

        child_ids = []
        for image_url in image_urls:
            child = self._request(
                f"{self.graph_url}/{instagram_business_id}/media",
                method='POST',
                data={'image_url': image_url, 'is_carousel_item': 'true'},
            )
            if 'error' in child:
                return child
            child_id = child.get('id')
            if not child_id:
                return {'error': 'Carousel alt görsel kapsayıcısı oluşturulamadı.'}
            child_ids.append(child_id)

        creation = self._request(
            f"{self.graph_url}/{instagram_business_id}/media",
            method='POST',
            data={'media_type': 'CAROUSEL', 'children': ','.join(child_ids), 'caption': caption},
        )
        if 'error' in creation:
            return creation
        creation_id = creation.get('id')
        if not creation_id:
            return {'error': 'Carousel kapsayıcısı oluşturulamadı.'}
        return self._request(
            f"{self.graph_url}/{instagram_business_id}/media_publish",
            method='POST',
            data={'creation_id': creation_id},
        )

    def refresh_access_token(self):
        return self._request(f"{self.base_url}/refresh_access_token", {'grant_type': 'ig_refresh_token'})

    def get_long_lived_token(self, short_lived_token):
        return self._request(f"{self.graph_url}/oauth/access_token", {'grant_type': 'ig_exchange_token', 'client_secret': settings.INSTAGRAM_APP_SECRET, 'access_token': short_lived_token})
