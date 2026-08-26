"""Isolated Playwright process used by Windows Celery workers."""

from __future__ import annotations

import json
import sys

from playwright.sync_api import sync_playwright


def _json_ld_product(page):
    for script in page.locator('script[type="application/ld+json"]').all():
        try:
            payload = json.loads(script.text_content() or "{}")
        except (TypeError, ValueError):
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            graph = candidate.get("@graph") if isinstance(candidate.get("@graph"), list) else []
            for value in [candidate, *graph]:
                if isinstance(value, dict) and str(value.get("@type", "")).casefold() == "product":
                    return value
    return {}


def verify(payload):
    results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="tr-TR")
        try:
            for item in payload.get("items", []):
                page = context.new_page()
                result = {"index": item["index"], "status": "failed"}
                try:
                    response = page.goto(
                        item["url"],
                        wait_until="domcontentloaded",
                        timeout=max(5, int(item.get("timeout_seconds", 20))) * 1000,
                    )
                    product = _json_ld_product(page)
                    offers = product.get("offers") if isinstance(product, dict) else {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    canonical = page.locator('link[rel="canonical"]').first
                    price_meta = page.locator(
                        'meta[property="product:price:amount"],meta[itemprop="price"]'
                    ).first
                    result.update({
                        "status": "verified" if response and response.ok else "page_opened",
                        "http_status": response.status if response else None,
                        "title": (product.get("name") or page.title() or "")[:500],
                        "canonical_url": canonical.get_attribute("href") if canonical.count() else "",
                        "price": (
                            (offers or {}).get("price")
                            or (offers or {}).get("lowPrice")
                            or (price_meta.get_attribute("content") if price_meta.count() else "")
                        ),
                        "currency": (offers or {}).get("priceCurrency") or "",
                        "availability": (offers or {}).get("availability") or "",
                        "seller": (
                            ((offers or {}).get("seller") or {}).get("name", "")
                            if isinstance((offers or {}).get("seller"), dict)
                            else ""
                        ),
                    })
                except Exception as exc:
                    result["error"] = (str(exc).strip() or exc.__class__.__name__)[:400]
                finally:
                    page.close()
                results.append(result)
        finally:
            context.close()
            browser.close()
    return results


def main():
    payload = json.loads(sys.stdin.read() or "{}")
    sys.stdout.write(json.dumps({"results": verify(payload)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
