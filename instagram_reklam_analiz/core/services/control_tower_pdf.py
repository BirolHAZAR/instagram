"""Control Tower grafik ekranını Windows uyumlu worker ile PDF'e çevirir.

ÖNEMLİ:
Bu dosyada bilerek sync_playwright KULLANILMAZ.
Windows + Django/Channels ortamında sync_playwright ana proseste
NotImplementedError verebilir. Bu yüzden Playwright sadece ayrı worker
Python prosesinde çalıştırılır.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse


class ControlTowerPdfError(RuntimeError):
    pass


def _pdf_url_from_request(request) -> str:
    query = request.GET.copy()
    query.pop("export", None)
    query["pdf_view"] = "1"
    query["pdf_render"] = "1"
    return request.build_absolute_uri(f"{request.path}?{query.urlencode()}")


def _cookies_from_request(request) -> list[dict]:
    base_url = f"{'https' if request.is_secure() else 'http'}://{request.get_host()}"
    cookies: list[dict] = []
    for name, value in request.COOKIES.items():
        if value is None:
            continue
        cookies.append(
            {
                "name": name,
                "value": str(value),
                "url": base_url,
                "path": "/",
                "httpOnly": name.lower() in {"sessionid", "csrftoken"},
                "secure": request.is_secure(),
                "sameSite": "Lax",
            }
        )
    return cookies


def _friendly_error(exc: Exception) -> str:
    details = (str(exc) or repr(exc)).strip()
    lower = details.lower()

    if "notimplementederror" in lower or "notimplemented" in lower:
        return (
            "Control Tower PDF üretilemedi: Windows event loop / subprocess hatası.\n\n"
            "Bu sürümde Playwright ana Django prosesinde çalışmaz; ayrı worker prosesinde çalışır. "
            "Eğer bu mesajı hâlâ alıyorsanız eski core/services/control_tower_pdf.py dosyası değişmemiş demektir.\n\n"
            f"Teknik detay: {details}"
        )

    if "executable doesn't exist" in lower or "install chromium" in lower or "browser_type.launch" in lower:
        return (
            "Control Tower PDF üretilemedi: Chromium kurulu değil.\n\n"
            "Çözüm:\n"
            "pip install playwright==1.56.0 pillow reportlab\n"
            "python -m playwright install chromium\n\n"
            f"Teknik detay: {details}"
        )

    if "giriş" in lower or "login" in lower or "oturum" in lower:
        return (
            "Control Tower PDF üretilemedi: PDF render ekranı giriş sayfasına düştü.\n\n"
            "Çözüm: Tarayıcıda giriş yaptıktan sonra tekrar deneyin. "
            "Development ortamında SESSION_COOKIE_SECURE=False olmalı.\n\n"
            f"Teknik detay: {details}"
        )

    if "timeout" in lower:
        return (
            "Control Tower PDF üretilemedi: Sayfa zamanında yüklenemedi.\n\n"
            "Çözüm: runserver açıkken tekrar deneyin. Grafiklerin yüklenmesi uzun sürüyorsa tekrar deneyin.\n\n"
            f"Teknik detay: {details}"
        )

    return f"Control Tower PDF üretilemedi: {details}"


def build_control_tower_screenshot_pdf(request) -> HttpResponse:
    """Control Tower ekranının grafik dahil PDF çıktısını üretir.

    Bu fonksiyon Playwright import etmez ve sync_playwright çağırmaz.
    Chromium render işlemi control_tower_pdf_worker.py tarafından ayrı proseste yapılır.
    """
    worker_path = Path(__file__).with_name("control_tower_pdf_worker.py")
    if not worker_path.exists():
        return HttpResponse(
            "Control Tower PDF üretilemedi: control_tower_pdf_worker.py bulunamadı. "
            "Dosyayı core/services/ klasörüne kopyalayın.",
            status=500,
            content_type="text/plain; charset=utf-8",
        )

    target_url = _pdf_url_from_request(request)
    cookies = _cookies_from_request(request)

    try:
        with tempfile.TemporaryDirectory(prefix="control_tower_pdf_") as tmpdir:
            tmpdir_path = Path(tmpdir)
            cookies_path = tmpdir_path / "cookies.json"
            output_path = tmpdir_path / "kontrol-kulesi-grafikli-rapor.pdf"
            cookies_path.write_text(json.dumps(cookies, ensure_ascii=False), encoding="utf-8")

            cmd = [
                sys.executable,
                str(worker_path),
                "--url",
                target_url,
                "--cookies-json",
                str(cookies_path),
                "--output",
                str(output_path),
            ]

            completed = subprocess.run(
                cmd,
                cwd=str(getattr(settings, "BASE_DIR", worker_path.parents[2])),
                capture_output=True,
                text=True,
                timeout=180,
            )

            if completed.returncode != 0:
                err = (completed.stderr or completed.stdout or "PDF worker bilinmeyen hata ile kapandı.").strip()
                raise ControlTowerPdfError(err)

            if not output_path.exists() or output_path.stat().st_size < 1000:
                raise ControlTowerPdfError("PDF dosyası üretildi ama çıktı boş/geçersiz görünüyor.")

            pdf_bytes = output_path.read_bytes()

    except Exception as exc:
        message = _friendly_error(exc)
        if getattr(settings, "DEBUG", False):
            message += "\n\n--- TRACEBACK ---\n" + traceback.format_exc()
        return HttpResponse(message, status=500, content_type="text/plain; charset=utf-8")

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="kontrol-kulesi-grafikli-rapor.pdf"'
    return response
