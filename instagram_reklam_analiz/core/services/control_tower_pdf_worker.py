"""Control Tower PDF worker - SINGLE PAGE PDF FINAL.

Bu dosya Playwright'i ayrı Python prosesinde çalıştırır.
Windows'ta Django ana proseste sync_playwright NotImplementedError verdiği için
render işlemi burada yapılır.

SÜRÜM KONTROL:
Bu sürüm dashboard ekran görüntüsünü parçalara bölmez; tek landscape A4 PDF sayfasına sığdırır.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

VERSION = "SINGLE_PAGE_PDF_FILTER_BAR_2026_06_15"


def _force_windows_proactor_policy() -> None:
    if sys.platform.startswith("win"):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def _screenshot_png_to_a4_pdf(png_bytes: bytes) -> bytes:
    """Tam dashboard ekran görüntüsünü TEK PDF sayfasına sığdırır.

    Önceki sürüm uzun ekran görüntüsünü A4 parçalara bölüyordu.
    Bu sürüm kullanıcı isteğine göre tüm görüntüyü tek landscape A4 sayfaya
    oranı bozmadan küçültür ve ortalar.
    """
    from PIL import Image
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas

    img = Image.open(BytesIO(png_bytes)).convert("RGB")
    img_w, img_h = img.size

    page_w, page_h = landscape(A4)
    margin = 10
    usable_w = page_w - (margin * 2)
    usable_h = page_h - (margin * 2)

    # Tek sayfaya sığdırmak için hem genişlik hem yükseklik oranını dikkate al.
    scale = min(usable_w / img_w, usable_h / img_h)
    draw_w = img_w * scale
    draw_h = img_h * scale
    x = (page_w - draw_w) / 2
    y = (page_h - draw_h) / 2

    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=landscape(A4))
    pdf.drawInlineImage(img, x, y, draw_w, draw_h)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


def _normalise_playwright_cookies(raw_cookies, target_url: str) -> list[dict]:
    """Her cookie'yi Playwright'in istediği kesin formata çevirir.

    Playwright kuralı: cookie içinde `url` olmalı veya `domain + path` olmalı.
    Development için en güvenlisi sadece `url` kullanmaktır.
    """
    parsed = urlparse(target_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    normalised: list[dict] = []

    if isinstance(raw_cookies, dict):
        iterable = [{"name": k, "value": v} for k, v in raw_cookies.items()]
    elif isinstance(raw_cookies, list):
        iterable = raw_cookies
    else:
        iterable = []

    for item in iterable:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue

        same_site = item.get("sameSite") or item.get("samesite") or "Lax"
        if same_site not in {"Strict", "Lax", "None"}:
            same_site = "Lax"

        cookie = {
            "name": str(name),
            "value": str(value),
            "url": str(item.get("url") or base_url),
            "httpOnly": bool(item.get("httpOnly", False)),
            "secure": bool(item.get("secure", False)),
            "sameSite": same_site,
        }
        if cookie["sameSite"] == "None":
            cookie["secure"] = True
        normalised.append(cookie)

    return normalised


async def _safe_add_cookies(context, cookies: list[dict]) -> None:
    if not cookies:
        return
    try:
        await context.add_cookies(cookies)
    except Exception:
        # Son güvenlik: tek tek dene, bozuk cookie varsa atla.
        for cookie in cookies:
            safe_cookie = dict(cookie)
            if "url" not in safe_cookie and not ("domain" in safe_cookie and "path" in safe_cookie):
                continue
            try:
                await context.add_cookies([safe_cookie])
            except Exception:
                continue


async def _render(args: argparse.Namespace) -> None:
    from playwright.async_api import async_playwright

    raw_cookies = []
    cookies_path = Path(args.cookies_json)
    if cookies_path.exists():
        raw_cookies = json.loads(cookies_path.read_text(encoding="utf-8"))
    cookies = _normalise_playwright_cookies(raw_cookies, args.url)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox", "--disable-gpu"],
        )
        context = await browser.new_context(
            viewport={"width": 1440, "height": 1800},
            device_scale_factor=1,
            locale="tr-TR",
            timezone_id="Europe/Istanbul",
            ignore_https_errors=True,
        )
        await _safe_add_cookies(context, cookies)

        page = await context.new_page()
        await page.goto(args.url, wait_until="domcontentloaded", timeout=120000)
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass

        await page.wait_for_timeout(3500)
        await page.add_style_tag(
            content="""
            .ct-actions, .ct-filter-toggle, .ct-btn, .ct-auto { display:none!important; }
            body { background:#070B18!important; overflow:visible!important; }
            * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
            """
        )

        title = ((await page.title()) or "").lower()
        body_text = ((await page.locator("body").inner_text(timeout=15000)) or "").lower()
        first_text = body_text[:1500]
        if "login" in title or "giriş" in first_text or "oturum aç" in first_text:
            raise RuntimeError("PDF render ekranı giriş sayfasına düştü; oturum çerezi aktarılamadı.")

        png_bytes = await page.screenshot(full_page=True, type="png", timeout=120000)
        pdf_bytes = _screenshot_png_to_a4_pdf(png_bytes)
        Path(args.output).write_bytes(pdf_bytes)

        await context.close()
        await browser.close()


def main() -> int:
    _force_windows_proactor_policy()
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--cookies-json", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args()
    if args.version:
        print(VERSION)
        return 0
    asyncio.run(_render(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
