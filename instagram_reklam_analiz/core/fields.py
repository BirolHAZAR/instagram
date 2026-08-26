import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


class EncryptedTextField(models.TextField):
    """
    TextField değerlerini veritabanına yazmadan önce Fernet ile şifreler.
    Okurken otomatik olarak çözer.

    Notlar:
    - Veritabanı kolon tipi TextField olarak kalır, ekstra migration ile kolon tipi değişmez.
    - Eski düz metin değerler okunabilir; kaydedilince şifreli hale gelir.
    - Şifreli değerler `enc:v1:` prefix'i ile tutulur.
    """

    prefix = "enc:v1:"

    def _get_fernet(self):
        key = getattr(settings, "TOKEN_ENCRYPTION_KEY", None) or os.environ.get("TOKEN_ENCRYPTION_KEY")

        if not key:
            # Geçiş sürecinde uygulama kırılmasın diye SECRET_KEY'den deterministik anahtar üretir.
            # Production için mutlaka .env içine TOKEN_ENCRYPTION_KEY eklenmelidir.
            secret_key = getattr(settings, "SECRET_KEY", None)
            if not secret_key:
                raise ImproperlyConfigured("TOKEN_ENCRYPTION_KEY veya SECRET_KEY bulunamadı.")
            digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
            key = base64.urlsafe_b64encode(digest).decode("utf-8")

        if isinstance(key, str):
            key = key.encode("utf-8")

        return Fernet(key)

    def _is_encrypted(self, value):
        return isinstance(value, str) and value.startswith(self.prefix)

    def _encrypt(self, value):
        if value is None or value == "":
            return value
        if self._is_encrypted(value):
            return value
        token = self._get_fernet().encrypt(str(value).encode("utf-8")).decode("utf-8")
        return f"{self.prefix}{token}"

    def _decrypt(self, value):
        if value is None or value == "":
            return value
        if not self._is_encrypted(value):
            return value

        token = value[len(self.prefix):]
        try:
            return self._get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            # Yanlış anahtar kullanılırsa uygulama sessizce bozuk veri göstermesin.
            raise ImproperlyConfigured(
                "Token çözülemedi. TOKEN_ENCRYPTION_KEY yanlış, eksik veya değiştirilmiş olabilir."
            )

    def from_db_value(self, value, expression, connection):
        return self._decrypt(value)

    def to_python(self, value):
        value = super().to_python(value)
        return self._decrypt(value)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self._encrypt(value)

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return self.get_prep_value(value)
