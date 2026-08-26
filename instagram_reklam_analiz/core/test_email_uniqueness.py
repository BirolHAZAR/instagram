from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse


class EmailUniquenessTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.User.objects.create_user(
            username="first-user",
            email="unique@example.com",
            password="StrongPass123!",
        )

    def test_signup_rejects_same_email_with_different_case(self):
        response = self.client.post(reverse("account_signup"), {
            "username": "second-user",
            "email": "UNIQUE@EXAMPLE.COM",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
        })

        self.assertIn(response.status_code, {200, 302})
        self.assertFalse(self.User.objects.filter(username="second-user").exists())

    def test_database_rejects_case_insensitive_duplicate_email(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                self.User.objects.create_user(
                    username="database-duplicate",
                    email="UNIQUE@EXAMPLE.COM",
                    password="StrongPass123!",
                )
