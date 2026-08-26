# Temel/Abstract modeller - Başka hiçbir model dosyasına bağımlılığı YOKTUR
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import random
from decimal import Decimal
from datetime import timedelta

User = get_user_model()

# Burada abstract base class'lar veya bağımsız modeller olabilir

class ContactMessage(models.Model):
    name = models.CharField(max_length=100, verbose_name="Ad Soyad")
    email = models.EmailField(verbose_name="E-posta")
    subject = models.CharField(max_length=200, verbose_name="Konu")
    message = models.TextField(verbose_name="Mesaj")
    is_read = models.BooleanField(default=False, verbose_name="Okundu mu?")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "İletişim Mesajı"
        verbose_name_plural = "İletişim Mesajları"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.subject}"


class DemoRequest(models.Model):
    name = models.CharField(max_length=120, verbose_name="Ad Soyad")
    email = models.EmailField(verbose_name="E-posta")
    phone = models.CharField(max_length=30, verbose_name="Telefon")
    company = models.CharField(max_length=180, blank=True, default="", verbose_name="Firma / Marka")
    role = models.CharField(max_length=120, blank=True, default="", verbose_name="Rol")
    ad_spend = models.CharField(max_length=120, blank=True, default="", verbose_name="Aylık reklam bütçesi")
    platforms = models.JSONField(default=list, blank=True, verbose_name="İlgilendiği alanlar")
    goal = models.CharField(max_length=220, verbose_name="Öncelikli hedef")
    message = models.TextField(blank=True, default="", verbose_name="Ek not")
    is_read = models.BooleanField(default=False, verbose_name="Okundu mu?")
    handled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_demo_requests",
        verbose_name="İlgilenen admin",
    )
    handled_at = models.DateTimeField(null=True, blank=True, verbose_name="İlgilenme zamanı")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Demo Talebi"
        verbose_name_plural = "Demo Talepleri"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["is_read", "-created_at"]),
            models.Index(fields=["email", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.company or 'Firma belirtilmedi'} - {self.name}"
