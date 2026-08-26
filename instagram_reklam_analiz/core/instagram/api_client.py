# core/instagram/api_client.py
"""
Instagram Graph API Ä°stemcisi
Instagram API ile iletiÅŸim kurmak iÃ§in gerekli tÃ¼m fonksiyonlarÄ± iÃ§erir
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from django.conf import settings
from django.core.cache import cache


class InstagramAPIClient:
    """
    Instagram Graph API istemcisi
    Instagram hesap bilgileri, medyalar, iÃ§gÃ¶rÃ¼ler ve reklam verilerini Ã§eker
    """
    
    def __init__(self, access_token: str = None, user_id: str = None):
        """
        API istemcisini baÅŸlat
        
        Args:
            access_token: Instagram access token
            user_id: Instagram kullanÄ±cÄ± ID'si
        """
        self.base_url = "https://graph.instagram.com"
        self.graph_url = getattr(settings, "FACEBOOK_GRAPH_URL", "https://graph.facebook.com/v25.0")
        self.access_token = access_token or getattr(settings, 'INSTAGRAM_ACCESS_TOKEN', None)
        self.user_id = user_id or "me"
        self.rate_limit = 200  # Dakikada maksimum istek
        self.request_count = 0
        self.last_request_time = datetime.now()
    
    def _make_request(self, url: str, params: Dict = None, method: str = 'GET', data: Dict = None) -> Dict:
        """
        API isteÄŸi yap (rate limit kontrolÃ¼ ile)
        
        Args:
            url: API URL
            params: Query parametreleri
            method: HTTP metodu (GET, POST)
            data: POST verileri
        
        Returns:
            Dict: API yanÄ±tÄ±
        """
        # Rate limit kontrolÃ¼
        now = datetime.now()
        if (now - self.last_request_time).seconds < 60:
            self.request_count += 1
            if self.request_count >= self.rate_limit:
                time.sleep(60)
                self.request_count = 0
        else:
            self.request_count = 1
            self.last_request_time = now
        
        # Token'Ä± parametrelere ekle
        if params is None:
            params = {}
        params['access_token'] = self.access_token
        
        try:
            if method == 'GET':
                response = requests.get(url, params=params, timeout=30)
            elif method == 'POST':
                response = requests.post(url, params=params, data=data, timeout=30)
            else:
                response = requests.request(method, url, params=params, data=data, timeout=30)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            if response and response.status_code == 400:
                try:
                    error_data = response.json()
                    return {'error': error_data}
                except:
                    pass
            return {'error': {'message': error_msg, 'status_code': response.status_code if response else 0}}
    
    # ============================================
    # KULLANICI BÄ°LGÄ°LERÄ°
    # ============================================
    
    def get_user_info(self, user_id: str = None) -> Dict:
        """
        KullanÄ±cÄ± bilgilerini al
        
        Args:
            user_id: KullanÄ±cÄ± ID (varsayÄ±lan: me)
        
        Returns:
            Dict: KullanÄ±cÄ± bilgileri
        """
        uid = user_id or self.user_id
        url = f"{self.base_url}/{uid}"
        params = {
            'fields': 'id,username,account_type,media_count'
        }
        
        return self._make_request(url, params)
    
    def get_user_info_detailed(self, user_id: str = None) -> Dict:
        """
        DetaylÄ± kullanÄ±cÄ± bilgilerini al
        
        Args:
            user_id: KullanÄ±cÄ± ID
        
        Returns:
            Dict: DetaylÄ± kullanÄ±cÄ± bilgileri
        """
        uid = user_id or self.user_id
        url = f"{self.graph_url}/{uid}"
        params = {
            'fields': 'id,username,name,biography,followers_count,follows_count,media_count,website,profile_picture_url'
        }
        
        return self._make_request(url, params)
    
    # ============================================
    # MEDYA Ä°ÅLEMLERÄ°
    # ============================================
    
    def get_user_media(self, user_id: str = None, limit: int = 100, after: str = None) -> Dict:
        """
        KullanÄ±cÄ±nÄ±n medyalarÄ±nÄ± al
        
        Args:
            user_id: KullanÄ±cÄ± ID
            limit: Medya sayÄ±sÄ± (max 100)
            after: Pagination cursor
        
        Returns:
            Dict: Medya listesi
        """
        uid = user_id or self.user_id
        url = f"{self.base_url}/{uid}/media"
        params = {
            'fields': 'id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count',
            'limit': min(limit, 100)
        }
        
        if after:
            params['after'] = after
        
        return self._make_request(url, params)
    
    def get_media_by_id(self, media_id: str) -> Dict:
        """
        Medya ID'sine gÃ¶re medya bilgilerini al
        
        Args:
            media_id: Medya ID'si
        
        Returns:
            Dict: Medya bilgileri
        """
        url = f"{self.base_url}/{media_id}"
        params = {
            'fields': 'id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count,children'
        }
        
        return self._make_request(url, params)
    
    def get_media_insights(self, media_id: str) -> Dict:
        """
        Medya iÃ§gÃ¶rÃ¼lerini al
        
        Args:
            media_id: Medya ID'si
        
        Returns:
            Dict: Ä°Ã§gÃ¶rÃ¼ verileri
        """
        url = f"{self.base_url}/{media_id}/insights"
        params = {
            'metric': 'engagement,impressions,reach,saved'
        }
        
        return self._make_request(url, params)
    
    def get_media_children(self, media_id: str) -> Dict:
        """
        Karusel medyasÄ±nÄ±n alt medyalarÄ±nÄ± al
        
        Args:
            media_id: Ana medya ID'si
        
        Returns:
            Dict: Alt medyalar
        """
        url = f"{self.base_url}/{media_id}/children"
        params = {
            'fields': 'id,media_type,media_url,permalink,timestamp'
        }
        
        return self._make_request(url, params)
    
    # ============================================
    # HESAP Ä°Ã‡GÃ–RÃœLERÄ°
    # ============================================
    
    def get_account_insights(self, user_id: str = None, since_days: int = 30) -> Dict:
        """
        Hesap iÃ§gÃ¶rÃ¼lerini al
        
        Args:
            user_id: KullanÄ±cÄ± ID
            since_days: KaÃ§ gÃ¼nlÃ¼k veri
        
        Returns:
            Dict: Ä°Ã§gÃ¶rÃ¼ verileri
        """
        uid = user_id or self.user_id
        since_date = (datetime.now() - timedelta(days=since_days)).strftime('%Y-%m-%d')
        until_date = datetime.now().strftime('%Y-%m-%d')
        
        url = f"{self.base_url}/{uid}/insights"
        params = {
            'metric': 'impressions,reach,profile_views,website_clicks',
            'period': 'day',
            'since': since_date,
            'until': until_date
        }
        
        return self._make_request(url, params)
    
    def get_follower_demographics(self, user_id: str = None) -> Dict:
        """
        TakipÃ§i demografik verilerini al (Business hesap gerektirir)
        
        Args:
            user_id: KullanÄ±cÄ± ID
        
        Returns:
            Dict: Demografik veriler
        """
        uid = user_id or self.user_id
        url = f"{self.graph_url}/{uid}/insights"
        params = {
            'metric': 'follower_demographics',
            'period': 'lifetime'
        }
        
        return self._make_request(url, params)
    
    def get_audience_insights(self, user_id: str = None) -> Dict:
        """
        Hedef kitle iÃ§gÃ¶rÃ¼lerini al
        
        Args:
            user_id: KullanÄ±cÄ± ID
        
        Returns:
            Dict: Hedef kitle verileri
        """
        uid = user_id or self.user_id
        url = f"{self.graph_url}/{uid}/insights"
        params = {
            'metric': 'audience_city,audience_country,audience_gender_age,audience_locale',
            'period': 'lifetime'
        }
        
        return self._make_request(url, params)
    
    # ============================================
    # Ä°ÅLETME HESAP Ä°ÅLEMLERÄ°
    # ============================================
    
    def get_business_accounts(self) -> Dict:
        """
        Facebook sayfalarÄ±na baÄŸlÄ± iÅŸletme hesaplarÄ±nÄ± al
        
        Returns:
            Dict: Ä°ÅŸletme hesaplarÄ±
        """
        url = f"{self.graph_url}/me/accounts"
        params = {
            'fields': 'id,name,instagram_business_account,access_token'
        }
        
        return self._make_request(url, params)
    
    def get_business_insights(self, business_id: str, since_days: int = 30) -> Dict:
        """
        Ä°ÅŸletme hesabÄ± iÃ§gÃ¶rÃ¼lerini al
        
        Args:
            business_id: Ä°ÅŸletme hesap ID'si
            since_days: KaÃ§ gÃ¼nlÃ¼k veri
        
        Returns:
            Dict: Ä°Ã§gÃ¶rÃ¼ verileri
        """
        since_date = (datetime.now() - timedelta(days=since_days)).strftime('%Y-%m-%d')
        until_date = datetime.now().strftime('%Y-%m-%d')
        
        url = f"{self.graph_url}/{business_id}/insights"
        params = {
            'metric': 'impressions,reach,profile_views,website_clicks,email_contacts,phone_call_clicks,text_message_clicks,get_directions_clicks',
            'period': 'day',
            'since': since_date,
            'until': until_date
        }
        
        return self._make_request(url, params)
    
    # ============================================
    # HASHTAG Ä°ÅLEMLERÄ°
    # ============================================
    
    def search_hashtag(self, hashtag: str) -> Dict:
        """
        Hashtag ara
        
        Args:
            hashtag: Hashtag adÄ± (# iÅŸareti olmadan)
        
        Returns:
            Dict: Hashtag bilgileri
        """
        url = f"{self.graph_url}/ig_hashtag_search"
        params = {
            'q': hashtag
        }
        
        return self._make_request(url, params)
    
    def get_hashtag_media(self, hashtag_id: str, limit: int = 100) -> Dict:
        """
        Hashtag'e gÃ¶re medyalarÄ± al
        
        Args:
            hashtag_id: Hashtag ID'si
            limit: Medya sayÄ±sÄ±
        
        Returns:
            Dict: Medya listesi
        """
        url = f"{self.graph_url}/{hashtag_id}/recent_media"
        params = {
            'fields': 'id,caption,media_type,media_url,permalink,timestamp,like_count,comments_count',
            'limit': min(limit, 100)
        }
        
        return self._make_request(url, params)
    
    def get_hashtag_insights(self, hashtag_id: str) -> Dict:
        """
        Hashtag iÃ§gÃ¶rÃ¼lerini al
        
        Args:
            hashtag_id: Hashtag ID'si
        
        Returns:
            Dict: Ä°Ã§gÃ¶rÃ¼ verileri
        """
        url = f"{self.graph_url}/{hashtag_id}/insights"
        params = {
            'metric': 'impressions,reach'
        }
        
        return self._make_request(url, params)
    
    # ============================================
    # REKLAM Ä°ÅLEMLERÄ°
    # ============================================
    
    def get_ad_accounts(self) -> Dict:
        """
        Reklam hesaplarÄ±nÄ± al
        
        Returns:
            Dict: Reklam hesaplarÄ±
        """
        url = f"{self.graph_url}/me/adaccounts"
        params = {
            'fields': 'id,name,account_status,currency,amount_spent,balance'
        }
        
        return self._make_request(url, params)
    
    def get_ad_campaigns(self, ad_account_id: str, limit: int = 100) -> Dict:
        """
        Reklam kampanyalarÄ±nÄ± al
        
        Args:
            ad_account_id: Reklam hesap ID'si
            limit: Kampanya sayÄ±sÄ±
        
        Returns:
            Dict: Kampanya listesi
        """
        url = f"{self.graph_url}/act_{ad_account_id}/campaigns"
        params = {
            'fields': 'id,name,status,objective,start_time,stop_time,daily_budget,lifetime_budget',
            'limit': min(limit, 100)
        }
        
        return self._make_request(url, params)
    
    def get_ad_sets(self, ad_account_id: str, limit: int = 100) -> Dict:
        """
        Reklam setlerini al
        
        Args:
            ad_account_id: Reklam hesap ID'si
            limit: Ad set sayÄ±sÄ±
        
        Returns:
            Dict: Ad set listesi
        """
        url = f"{self.graph_url}/act_{ad_account_id}/adsets"
        params = {
            'fields': 'id,name,status,daily_budget,lifetime_budget,targeting,start_time,end_time',
            'limit': min(limit, 100)
        }
        
        return self._make_request(url, params)
    
    def get_ads(self, ad_account_id: str, limit: int = 100) -> Dict:
        """
        ReklamlarÄ± al
        
        Args:
            ad_account_id: Reklam hesap ID'si
            limit: Reklam sayÄ±sÄ±
        
        Returns:
            Dict: Reklam listesi
        """
        url = f"{self.graph_url}/act_{ad_account_id}/ads"
        params = {
            'fields': 'id,name,status,creative,adset_id,campaign_id',
            'limit': min(limit, 100)
        }
        
        return self._make_request(url, params)
    
    def get_ad_insights(self, ad_account_id: str, since_days: int = 30) -> Dict:
        """
        Reklam iÃ§gÃ¶rÃ¼lerini al
        
        Args:
            ad_account_id: Reklam hesap ID'si
            since_days: KaÃ§ gÃ¼nlÃ¼k veri
        
        Returns:
            Dict: Ä°Ã§gÃ¶rÃ¼ verileri
        """
        since_date = (datetime.now() - timedelta(days=since_days)).strftime('%Y-%m-%d')
        until_date = datetime.now().strftime('%Y-%m-%d')
        
        url = f"{self.graph_url}/act_{ad_account_id}/insights"
        params = {
            'fields': 'campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,impressions,clicks,ctr,cpc,cpm,spend,reach,frequency,actions,action_values,purchase_roas,website_purchase_roas,date_start,date_stop',
            'time_increment': 1,
            'time_range': json.dumps({'since': since_date, 'until': until_date}),
            'level': 'ad',
            'limit': 100
        }
        
        return self._make_request(url, params)
    
    def create_campaign(self, ad_account_id: str, campaign_data: Dict) -> Dict:
        """
        Yeni reklam kampanyasÄ± oluÅŸtur
        
        Args:
            ad_account_id: Reklam hesap ID'si
            campaign_data: Kampanya verileri
        
        Returns:
            Dict: OluÅŸturulan kampanya
        """
        url = f"{self.graph_url}/act_{ad_account_id}/campaigns"
        
        return self._make_request(url, method='POST', data=campaign_data)
    
    # ============================================
    # TOKEN YÃ–NETÄ°MÄ°
    # ============================================
    
    def refresh_access_token(self) -> Dict:
        """
        Access token'Ä± yenile (long-lived token al)
        
        Returns:
            Dict: Yeni token bilgileri
        """
        url = f"{self.base_url}/refresh_access_token"
        params = {
            'grant_type': 'ig_refresh_token'
        }
        
        return self._make_request(url, params)
    
    def get_long_lived_token(self, short_lived_token: str) -> Dict:
        """
        Short-lived token'Ä± long-lived token'a Ã§evir (60 gÃ¼n geÃ§erli)
        
        Args:
            short_lived_token: Short-lived access token
        
        Returns:
            Dict: Long-lived token bilgileri
        """
        url = f"{self.graph_url}/oauth/access_token"
        params = {
            'grant_type': 'ig_exchange_token',
            'client_secret': getattr(settings, 'INSTAGRAM_APP_SECRET', ''),
            'access_token': short_lived_token
        }
        
        return self._make_request(url, params)
    
    def exchange_code_for_token(self, code: str) -> Dict:
        """
        Authorization code'u access token'a Ã§evir
        
        Args:
            code: Authorization code
        
        Returns:
            Dict: Token bilgileri
        """
        url = f"{self.base_url}/oauth/access_token"
        data = {
            'client_id': getattr(settings, 'INSTAGRAM_APP_ID', ''),
            'client_secret': getattr(settings, 'INSTAGRAM_APP_SECRET', ''),
            'grant_type': 'authorization_code',
            'redirect_uri': getattr(settings, 'INSTAGRAM_REDIRECT_URI', 'http://localhost:8000/instagram/callback/'),
            'code': code
        }
        
        return self._make_request(url, method='POST', data=data)
    
    # ============================================
    # WEBHOOK Ä°ÅLEMLERÄ°
    # ============================================
    
    def verify_webhook(self, verify_token: str, challenge: str, mode: str) -> bool:
        """
        Webhook doÄŸrulama
        
        Args:
            verify_token: DoÄŸrulama token'Ä±
            challenge: Challenge deÄŸeri
            mode: Mod (subscribe, unsubscribe)
        
        Returns:
            bool: DoÄŸrulama baÅŸarÄ±lÄ± mÄ±
        """
        expected_token = getattr(settings, 'INSTAGRAM_WEBHOOK_VERIFY_TOKEN', '')
        return verify_token == expected_token
    
    def process_webhook_data(self, data: Dict) -> Dict:
        """
        Webhook verilerini iÅŸle
        
        Args:
            data: Webhook'tan gelen veri
        
        Returns:
            Dict: Ä°ÅŸlenmiÅŸ veri
        """
        result = {
            'object': data.get('object'),
            'entry': []
        }
        
        for entry in data.get('entry', []):
            processed_entry = {
                'id': entry.get('id'),
                'time': entry.get('time'),
                'changes': []
            }
            
            for change in entry.get('changes', []):
                processed_change = {
                    'field': change.get('field'),
                    'value': change.get('value')
                }
                processed_entry['changes'].append(processed_change)
            
            result['entry'].append(processed_entry)
        
        return result
    
    # ============================================
    # YARDIMCI FONKSÄ°YONLAR
    # ============================================
    
    def get_rate_limit_status(self) -> Dict:
        """
        Rate limit durumunu dÃ¶ndÃ¼r
        
        Returns:
            Dict: Rate limit bilgileri
        """
        return {
            'request_count': self.request_count,
            'rate_limit': self.rate_limit,
            'last_request_time': self.last_request_time.isoformat(),
            'remaining': max(0, self.rate_limit - self.request_count)
        }
    
    def clear_cache(self):
        """Cache temizleme"""
        cache.delete_pattern('instagram_*')
    
    def set_access_token(self, token: str):
        """
        Access token'Ä± gÃ¼ncelle
        
        Args:
            token: Yeni access token
        """
        self.access_token = token
    
    def test_connection(self) -> bool:
        """
        API baÄŸlantÄ±sÄ±nÄ± test et
        
        Returns:
            bool: BaÄŸlantÄ± baÅŸarÄ±lÄ± mÄ±
        """
        result = self.get_user_info()
        return 'error' not in result



