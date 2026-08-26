from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from core.middleware.concurrent_sessions import ConcurrentSessionMiddleware
from core.models import UserProfile


class ConcurrentSessionMiddlewareTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = ConcurrentSessionMiddleware(lambda request: HttpResponse("ok"))

    def _request(self, user):
        request = self.factory.get("/dashboard/")
        SessionMiddleware(lambda req: None).process_request(request)
        request.session.create()
        request.user = user
        request._messages = FallbackStorage(request)
        return request

    def test_second_recent_session_is_rejected_by_default(self):
        user = get_user_model().objects.create_user("normal-user", password="secret123")

        first_response = self.middleware(self._request(user))
        second_response = self.middleware(self._request(user))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 302)
        self.assertIn("/accounts/login/", second_response.url)

    def test_admin_permission_allows_multiple_sessions(self):
        user = get_user_model().objects.create_user("allowed-user", password="secret123")
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.allow_concurrent_sessions = True
        profile.save(update_fields=["allow_concurrent_sessions"])

        self.assertEqual(self.middleware(self._request(user)).status_code, 200)
        self.assertEqual(self.middleware(self._request(user)).status_code, 200)

    def test_demo_user_is_always_exempt(self):
        user = get_user_model().objects.create_user("DeMo", password="secret123")

        self.assertEqual(self.middleware(self._request(user)).status_code, 200)
        self.assertEqual(self.middleware(self._request(user)).status_code, 200)
