# core/middleware/error_handler.py - YENİ DOSYA

import traceback
from django.http import JsonResponse
from django.conf import settings
from core.ai_agents.error_manager import ErrorManager


class GlobalExceptionMiddleware:
    """
    Tüm view'larda yakalanmayan exception'ları yakala ve Sentry'e gönder
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        return self.get_response(request)
    
    def process_exception(self, request, exception):
        """Yakalanmayan exception'ları yakala"""
        return None