import requests
import hashlib
import hmac
import json
from django.conf import settings
from urllib.parse import urlencode

class InstagramAuth:
    """Instagram kimlik doğrulama ve token yönetimi"""
    
    def __init__(self):
        self.app_id = getattr(settings, 'INSTAGRAM_APP_ID', '')
        self.app_secret = getattr(settings, 'INSTAGRAM_APP_SECRET', '')
        self.redirect_uri = getattr(settings, 'INSTAGRAM_REDIRECT_URI', 'http://localhost:8000/instagram/callback/')
        self.base_url = getattr(settings, 'INSTAGRAM_BASE_URL', 'https://graph.instagram.com')
        self.graph_url = getattr(settings, 'FACEBOOK_GRAPH_URL', 'https://graph.facebook.com/v25.0')
    
    def get_auth_url(self):
        """Instagram giriş URL'ini oluştur"""
        params = {
            'client_id': self.app_id,
            'redirect_uri': self.redirect_uri,
            'scope': 'user_profile,user_media,instagram_basic,instagram_content_publish,ads_read,ads_management',
            'response_type': 'code',
            'state': self._generate_state()
        }
        
        auth_url = f"{self.base_url}/oauth/authorize?{urlencode(params)}"
        return auth_url
    
    def exchange_code_for_token(self, code):
        """Authorization code'u access token'a çevir"""
        url = f"{self.base_url}/oauth/access_token"
        
        data = {
            'client_id': self.app_id,
            'client_secret': self.app_secret,
            'grant_type': 'authorization_code',
            'redirect_uri': self.redirect_uri,
            'code': code
        }
        
        try:
            response = requests.post(url, data=data)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e)}
    
    def get_long_lived_token(self, short_lived_token):
        """Short-lived token'ı long-lived token'a çevir"""
        url = f"{self.graph_url}/oauth/access_token"
        
        params = {
            'grant_type': 'ig_exchange_token',
            'client_secret': self.app_secret,
            'access_token': short_lived_token
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e)}
    
    def refresh_token(self, access_token):
        """Access token'ı yenile"""
        url = f"{self.base_url}/refresh_access_token"
        
        params = {
            'grant_type': 'ig_refresh_token',
            'access_token': access_token
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e)}
    
    def get_user_info(self, access_token):
        """Token ile kullanıcı bilgilerini al"""
        url = f"{self.base_url}/me"
        params = {
            'fields': 'id,username,account_type,media_count',
            'access_token': access_token
        }
        
        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {'error': str(e)}
    
    def _generate_state(self):
        """Random state üret (CSRF koruması)"""
        import secrets
        return secrets.token_urlsafe(32)
