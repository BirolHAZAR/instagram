from __future__ import annotations

import base64
import copy
import hashlib
import json
import mimetypes
import re
import requests
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from openai import OpenAI

from core.models import AIOperationTariff, Marketplace, MarketplaceProductResearch, MarketplaceProductResearchResult
from core.services.ai_gateway import create_response
from core.services.marketplace_research import apply_research_result
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.services.web_market_research import (
    MarketResearchProviderError,
    _decimal_from_price,
    search_market,
    summarize_price_items,
)


PLAN_TARIFF = "shopping-agent-plan"
PREFILTER_TARIFF = "shopping-agent-prefilter"
QA_TARIFF = "shopping-agent-final-qa"


def _tariff_cache_timeout(key, default):
    value = (
        AIOperationTariff.objects.filter(key=key, is_active=True)
        .values_list("cache_timeout_seconds", flat=True)
        .first()
    )
    return int(value if value is not None else default)


def _set_progress(research, status, percent, step):
    research.status = status
    research.progress_percent = max(0, min(100, int(percent)))
    research.current_step = step[:180]
    fields = ["status", "progress_percent", "current_step", "updated_at"]
    if not research.started_at:
        research.started_at = timezone.now()
        fields.append("started_at")
    research.save(update_fields=fields)


def _json_schema():
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "detected_product": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "product_name": {"type": "string"},
                    "category": {"type": "string"},
                    "brand": {"type": "string"},
                    "model": {"type": "string"},
                    "colors": {"type": "array", "items": {"type": "string"}},
                    "attributes": {"type": "array", "items": {"type": "string"}},
                    "search_terms": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["product_name", "category", "brand", "model", "colors", "attributes", "search_terms"],
            },
            "professional_prompt": {"type": "string"},
            "search_plan": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "country": {"type": "string"},
                    "required_brand": {"type": "string"},
                    "required_colors": {"type": "array", "items": {"type": "string"}},
                    "same_product_required": {"type": "boolean"},
                    "include_similar": {"type": "boolean"},
                    "stock_required": {"type": "boolean"},
                    "authenticity_required": {"type": "boolean"},
                    "include_shipping": {"type": "boolean"},
                    "sort_by": {"type": "string"},
                    "query": {"type": "string"},
                },
                "required": [
                    "country", "required_brand", "required_colors", "same_product_required",
                    "include_similar", "stock_required", "authenticity_required",
                    "include_shipping", "sort_by", "query",
                ],
            },
            "uncertainties": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["detected_product", "professional_prompt", "search_plan", "uncertainties"],
    }


def _image_content(research):
    if not research.product_image:
        return None
    research.product_image.open("rb")
    try:
        encoded = base64.b64encode(research.product_image.read()).decode("ascii")
    finally:
        research.product_image.close()
    mime = mimetypes.guess_type(research.product_image.name)[0] or "image/jpeg"
    return {"type": "input_image", "image_url": f"data:{mime};base64,{encoded}", "detail": "high"}


def generate_research_plan(research):
    reference = f"shopping-agent-plan:{research.id}"
    user_attributes = [
        value.strip()
        for value in (research.prompt or "").split(",")
        if value.strip()
    ]
    content = [{
        "type": "input_text",
        "text": (
            "REFERANS ÜRÜNÜ İNCELE VE UYGULANABİLİR BİR E-TİCARET ARAŞTIRMA PLANI HAZIRLA.\n\n"
            f"Kullanıcının yazdığı ürün adı: {research.title or '(belirtilmedi)'}\n"
            f"Kullanıcının virgülle ayırdığı ürün özellikleri: "
            f"{json.dumps(user_attributes, ensure_ascii=False)}\n"
            f"Yüklenen görselin dosya adı (yalnız zayıf arama ipucu): "
            f"{research.product_image.name.rsplit('/', 1)[-1] if research.product_image else '(yok)'}\n\n"
            "Kullanıcının yazdığı ürün adı ve her bir özellik birincil bağlamdır. Bunları görseldeki "
            "kanıtlarla tek tek karşılaştır. Çelişki varsa kullanıcı şartını arama filtresi olarak koru, "
            "çelişkiyi uncertainties alanında açıkla. Görselden kesin okunmayan marka, model, materyal, "
            "orijinallik veya teknik özelliği uydurma. Dosya adındaki marka/model kelimelerini kesin gerçek "
            "sayma; fakat görsel ve ürün tanımıyla uyumluysa ek bir marka/model arama sorgusu üret.\n\n"
            "professional_prompt alanında, başka bir uzman alışveriş ajanına doğrudan verilebilecek "
            "yüksek kaliteli Türkçe bir görev talimatı yaz. Prompt şu unsurları akıcı ama açık biçimde "
            "kapsasın: ürünün kimliği ve kategorisi; görselde gözlenen ayırt edici tasarım detayları; "
            "kullanıcının zorunlu özellikleri; aynı ürün ile çok benzer ürünün nasıl ayrılacağı; renk, "
            "marka, model, varyant, beden ve kondisyon filtreleri; Türkiye'den gönderim, stok, kargo ve "
            "toplam fiyat kontrolü; satıcı ve orijinallik güven sinyalleri; doğrudan ürün sayfasından "
            "doğrulama; doğrulanamayan bilgiye kesinlik atfetmeme; sonuçların eşleşme ve toplam fiyata "
            "göre sıralanması. Genel veya kısa bir arama cümlesi yazma; ölçülebilir kabul/red kriterleri "
            "olan profesyonel bir araştırma talimatı üret.\n\n"
            "search_plan alanındaki query kısa, aranabilir ve ürün adı + en ayırt edici 3-6 özelliği "
            "içeren bir sorgu olsun. required_brand ve required_colors yalnız kullanıcı bunları ürün adı "
            "veya özellik alanında açıkça zorunlu tuttuğunda doldurulsun. Görselde görülen marka/renk "
            "profesyonel promptta gözlem olarak anlatılsın fakat tek başına zorunlu filtre yapılmasın. "
            "Aynı modelin farklı renk varyantlarını ayrı sonuçlar olarak bulmayı özellikle iste."
        ),
    }]
    image = _image_content(research)
    if image:
        content.append(image)
    plan_fingerprint = json.dumps(
        {
            "version": "shopping-plan-v4",
            "title": research.title or "",
            "prompt": research.prompt or "",
            "model": getattr(settings, "OPENAI_SHOPPING_VISION_MODEL", "gpt-5.6-sol"),
            "image_sha256": hashlib.sha256(
                str((image or {}).get("image_url") or "").encode("utf-8")
            ).hexdigest(),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cache_key = "mpr:plan:" + hashlib.sha256(plan_fingerprint.encode("utf-8")).hexdigest()
    cached_plan = cache.get(cache_key)
    if isinstance(cached_plan, dict):
        return copy.deepcopy(cached_plan)

    credit = consume_openai_operation(
        user=research.user,
        organization=research.organization,
        subscription=research.subscription,
        tariff_key=PLAN_TARIFF,
        reference=reference,
        reason="Alışveriş ajanı görsel ve arama planı",
    )
    if not credit.allowed:
        raise MarketResearchProviderError(credit.reason)
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=2)
        response = create_response(
            client=client,
            tariff_key=PLAN_TARIFF,
            user=research.user,
            organization=research.organization,
            reference=reference,
            model=getattr(settings, "OPENAI_SHOPPING_VISION_MODEL", "gpt-5.6-sol"),
            instructions=(
                "Sen kıdemli bir görsel ürün analisti ve Türkiye e-ticaret araştırma uzmanısın. "
                "Çıktın yalnız verilen JSON şemasına uymalı; gözlem, kullanıcı şartı ve belirsizliği "
                "birbirinden ayırmalısın. Profesyonel prompt ayrıntılı, uygulanabilir, dürüst ve "
                "tekrarlanabilir sonuç üretecek kalitede olmalı."
            ),
            input=[{"role": "user", "content": content}],
            text={"format": {"type": "json_schema", "name": "shopping_research_plan", "strict": True, "schema": _json_schema()}},
            max_output_tokens=7000,
        )
        parsed_plan = json.loads(response.output_text)
        cache.set(
            cache_key,
            copy.deepcopy(parsed_plan),
            timeout=_tariff_cache_timeout(PLAN_TARIFF, 60 * 60 * 24 * 30),
        )
        return parsed_plan
    except Exception:
        refund_ai_tariff_credits(
            user=research.user,
            organization=research.organization,
            tariff_key=PLAN_TARIFF,
            reference=reference,
            reason="Alışveriş ajanı planı üretilemedi",
        )
        raise


def choose_marketplaces(research, plan):
    manually_selected = list(research.selected_marketplaces.filter(is_active=True, research_enabled=True))
    if manually_selected:
        return manually_selected
    category = str(plan.get("detected_product", {}).get("category") or "").casefold()
    sources = list(Marketplace.objects.filter(is_active=True, research_enabled=True).order_by("search_priority", "order"))
    limit = max(1, int(getattr(settings, "SHOPPING_AGENT_MAX_SMART_SOURCES", 6) or 6))
    if not category:
        return sources[:limit]
    preferred = [
        source for source in sources
        if not source.categories or any(str(value).casefold() in category or category in str(value).casefold() for value in source.categories)
    ]
    return (preferred or sources)[:limit]


def _domain_allowed(url, marketplace):
    hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    allowed = [str(value).lower().lstrip(".") for value in (marketplace.allowed_domains or []) if value]
    if not allowed:
        fallback = urlparse(marketplace.website_url or "").hostname
        allowed = [fallback.lower()] if fallback else []
    return bool(hostname and any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed))


def _item_matches_marketplace(item, marketplace):
    if _domain_allowed(item.get("url", ""), marketplace):
        return True
    source_text = " ".join([
        str(item.get("platform") or ""),
        str(item.get("seller") or ""),
        str(item.get("source") or ""),
    ]).casefold()
    aliases = {
        marketplace.code.casefold(),
        marketplace.name.casefold(),
        marketplace.code.replace("-", " ").casefold(),
    }
    return any(alias and alias in source_text for alias in aliases)


def discover_candidates(research, plan, marketplaces):
    query = plan["search_plan"].get("query") or plan["professional_prompt"]
    detected = plan.get("detected_product") or {}
    search_terms = [
        str(value).strip()
        for value in detected.get("search_terms", [])
        if str(value).strip()
    ]
    high_signal_terms = [
        value for value in search_terms
        if any(character.isdigit() for character in value)
    ]
    remaining_terms = [value for value in search_terms if value not in high_signal_terms]
    query_variants = []
    for value in [*high_signal_terms, research.title, *remaining_terms, query]:
        normalized = " ".join(str(value or "").split())
        if normalized and normalized.casefold() not in {item.casefold() for item in query_variants}:
            query_variants.append(normalized)
    # Tek, aşırı kısıtlı sorguya bağımlı kalma: ürün adı, daha kısa görsel
    # tanım ve ayrıntılı sorgu ayrı ayrı taranır.
    query_variants = query_variants[:5] or [query]
    collected = []
    errors = []
    for index, marketplace in enumerate(marketplaces, start=1):
        _set_progress(
            research,
            MarketplaceProductResearch.STATUS_SEARCHING,
            25 + int((index / max(1, len(marketplaces))) * 30),
            f"{marketplace.name} aranıyor",
        )
        domains = marketplace.allowed_domains or []
        site_base = query_variants[0]
        site_query = f"{site_base} site:{domains[0]}" if domains else site_base
        try:
            items = search_market(site_query, max_results=marketplace.max_results, include_tavily=False)
        except Exception as exc:
            errors.append({"marketplace": marketplace.code, "error": str(exc)})
            continue
        for item in items:
            if _item_matches_marketplace(item, marketplace):
                item["marketplace_id"] = marketplace.id
                item["marketplace_code"] = marketplace.code
                collected.append(item)
    _set_progress(
        research,
        MarketplaceProductResearch.STATUS_SEARCHING,
        54,
        "Alternatif ürün adları ve renk varyantları genel alışveriş indeksinde taranıyor",
    )
    for fallback_query in query_variants:
        try:
            fallback_items = search_market(fallback_query, max_results=40, include_tavily=False)
        except Exception as exc:
            errors.append({
                "marketplace": "google-shopping-fallback",
                "query": fallback_query,
                "error": str(exc),
            })
            fallback_items = []
        for item in fallback_items:
            matched = next(
                (source for source in marketplaces if _item_matches_marketplace(item, source)),
                None,
            )
            if matched:
                item["marketplace_id"] = matched.id
                item["marketplace_code"] = matched.code
            else:
                item["marketplace_id"] = None
                item["marketplace_code"] = "google-shopping"
            collected.append(item)
    unique = {}
    for item in collected:
        key = (
            str(item.get("product_id") or "").strip()
            or str(item.get("url") or "").split("?")[0].rstrip("/")
            or f"{item.get('platform')}::{item.get('title')}::{item.get('price')}"
        ).casefold()
        if key and key not in unique:
            unique[key] = item
    return list(unique.values()), errors


def expand_direct_seller_offers(items, marketplaces):
    """Resolve Google Shopping products to direct seller offers via Immersive Product."""
    api_key = getattr(settings, "SERPAPI_API_KEY", "") or ""
    limit = max(0, min(10, int(getattr(settings, "SHOPPING_AGENT_IMMERSIVE_PRODUCT_LIMIT", 5) or 5)))
    if not api_key or limit <= 0:
        return items, []
    candidates = []
    seen_api_urls = set()
    for item in items:
        api_url = item.get("serpapi_immersive_product_api")
        if api_url and api_url not in seen_api_urls:
            seen_api_urls.add(api_url)
            candidates.append(item)
        if len(candidates) >= limit:
            break
    expanded = []
    errors = []
    for item in candidates:
        try:
            response = requests.get(
                item["serpapi_immersive_product_api"],
                params={"api_key": api_key, "more_stores": "true"},
                timeout=int(getattr(settings, "SERPAPI_TIMEOUT", 35) or 35),
            )
            response.raise_for_status()
            payload = response.json()
            product_results = payload.get("product_results") or {}
            sellers_results = payload.get("sellers_results") or {}
            stores = product_results.get("stores") or sellers_results.get("online_sellers") or []
        except Exception as exc:
            errors.append({"provider": "serpapi_immersive_product", "error": str(exc)[:300]})
            continue
        for store in stores:
            direct_url = store.get("direct_link") or store.get("link") or ""
            source = next(
                (
                    marketplace for marketplace in marketplaces
                    if _domain_allowed(direct_url, marketplace)
                    or marketplace.name.casefold() in str(store.get("name") or "").casefold()
                ),
                None,
            )
            if not direct_url or source is None:
                continue
            raw_price = store.get("total_price") or store.get("base_price") or store.get("price")
            price = _decimal_from_price(raw_price)
            if not price:
                continue
            expanded.append({
                **item,
                "platform": source.name,
                "seller": store.get("name") or source.name,
                "price": str(price),
                "currency": "TRY",
                "url": direct_url,
                "marketplace_id": source.id,
                "marketplace_code": source.code,
                "delivery": (
                    (store.get("additional_price") or {}).get("shipping")
                    or store.get("delivery")
                    or item.get("delivery")
                    or ""
                ),
                "data_provider": "serpapi_immersive_product",
                "price_source": "direct_seller_offer",
                "source_reliability": 0.9,
            })
    direct_urls = {offer.get("url") for offer in expanded}
    originals = [
        item for item in items
        if item.get("url") not in direct_urls
    ]
    return [*expanded, *originals], errors


def _verify_candidate_pages_impl(research, items, marketplaces):
    enabled = {source.id: source for source in marketplaces if source.browser_verification_enabled}
    if not enabled or not items:
        return items, []
    errors = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return items, [{"error": "Playwright kurulu değil; arama sonuçları doğrulanmadan kullanıldı."}]

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(locale="tr-TR")
        try:
            verify_items = [item for item in items if item.get("marketplace_id") in enabled][:20]
            for index, item in enumerate(verify_items, start=1):
                source = enabled[item["marketplace_id"]]
                if not _domain_allowed(item.get("url", ""), source):
                    continue
                _set_progress(
                    research,
                    MarketplaceProductResearch.STATUS_VERIFYING,
                    55 + int((index / max(1, len(verify_items))) * 20),
                    f"{source.name} ürün sayfası doğrulanıyor",
                )
                page = context.new_page()
                try:
                    page.goto(item["url"], wait_until="domcontentloaded", timeout=source.timeout_seconds * 1000)
                    item["verified_title"] = page.title()[:500]
                    item["verification_status"] = "page_opened"
                    item["verified_at"] = timezone.now().isoformat()
                    canonical = page.locator('link[rel="canonical"]').first
                    if canonical.count():
                        item["canonical_url"] = canonical.get_attribute("href") or ""
                except Exception as exc:
                    item["verification_status"] = "failed"
                    errors.append({"marketplace": source.code, "url": item.get("url"), "error": str(exc)[:300]})
                finally:
                    page.close()
        finally:
            context.close()
            browser.close()
    return items, errors


def verify_candidate_pages(research, items, marketplaces):
    """Browser verification is additive; a browser runtime issue must not discard discovery results."""
    try:
        return _verify_candidate_pages_impl(research, items, marketplaces)
    except Exception as exc:
        enabled = {source.id: source for source in marketplaces if source.browser_verification_enabled}
        verify_items = [
            (index, item, enabled[item["marketplace_id"]])
            for index, item in enumerate(items)
            if item.get("marketplace_id") in enabled
            and _domain_allowed(item.get("url", ""), enabled[item["marketplace_id"]])
        ][:30]
        if not verify_items:
            detail = str(exc).strip() or exc.__class__.__name__
            return items, [{"marketplace": "browser-runtime", "error": f"Doğrulanabilir doğrudan mağaza URL'si yok: {detail}"}]
        payload = {
            "items": [
                {
                    "index": index,
                    "url": item["url"],
                    "timeout_seconds": source.timeout_seconds,
                }
                for index, item, source in verify_items
            ]
        }
        try:
            process = subprocess.run(
                [sys.executable, "-m", "core.services.browser_page_verifier"],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=180,
                cwd=str(settings.BASE_DIR),
                check=True,
            )
            verified = json.loads(process.stdout or "{}").get("results", [])
        except Exception as child_exc:
            detail = str(child_exc).strip() or child_exc.__class__.__name__
            return items, [{"marketplace": "browser-runtime", "error": f"Tarayıcı alt süreci başarısız: {detail}"}]
        errors = []
        for result in verified:
            index = int(result.get("index", -1))
            if index < 0 or index >= len(items):
                continue
            item = items[index]
            status = result.get("status") or "failed"
            item["verification_status"] = status
            if status in {"verified", "page_opened"}:
                item["verified_title"] = result.get("title") or item.get("title")
                item["canonical_url"] = result.get("canonical_url") or item.get("url")
                if result.get("price"):
                    item["price"] = str(result["price"])
                    item["price_source"] = "verified_product_page"
                if result.get("currency"):
                    item["currency"] = result["currency"]
                if result.get("seller"):
                    item["seller"] = result["seller"]
                item["availability"] = result.get("availability") or ""
                item["verified_at"] = timezone.now().isoformat()
            else:
                errors.append({
                    "marketplace": item.get("marketplace_code"),
                    "url": item.get("url"),
                    "error": result.get("error") or "Ürün sayfası doğrulanamadı",
                })
        return items, errors


def _decimal(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def build_price_strategy(items):
    prices = sorted(
        _decimal(item.get("price"))
        for item in items
        if _decimal(item.get("price")) > 0
    )
    if not prices:
        return {"recommended_price": Decimal("0.00"), "bands": [], "insights": []}

    def percentile(ratio):
        index = round((len(prices) - 1) * ratio)
        return prices[max(0, min(len(prices) - 1, index))]

    minimum = prices[0]
    q1 = percentile(0.25)
    median = percentile(0.50)
    q3 = percentile(0.75)
    maximum = prices[-1]
    recommended = max(minimum, (q1 * Decimal("0.99")).quantize(Decimal("0.01")))

    def count_between(low, high, include_high=False):
        if include_high:
            return sum(1 for price in prices if low <= price <= high)
        return sum(1 for price in prices if low <= price < high)

    low_count = count_between(minimum, q1) if q1 > minimum else 1
    middle_count = count_between(q1, q3) if q3 > q1 else max(1, len(prices) - 2)
    high_count = count_between(q3, maximum, include_high=True)
    max_count = max(1, low_count, middle_count, high_count)

    def money(value):
        return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    bands = [
        {
            "key": "strong",
            "label": f"{money(minimum)} – {money(q1)} TL",
            "competition": "Güçlü rekabet",
            "note": (
                "Fiyat odaklı satıcıların yoğunlaştığı alan. Görsel, yorum ve teslimat avantajı "
                "olmadan marj baskısı yüksektir."
            ),
            "density": round((low_count / max_count) * 100),
            "listing_count": low_count,
        },
        {
            "key": "balanced",
            "label": f"{money(q1)} – {money(q3)} TL",
            "competition": "Dengeli rekabet",
            "note": (
                "Piyasanın ana fiyat koridoru. Ürün sunumu ve satıcı güveni güçlüyse fiyat ile "
                "marj arasında dengeli konum sağlar."
            ),
            "density": round((middle_count / max_count) * 100),
            "listing_count": middle_count,
        },
        {
            "key": "low",
            "label": f"{money(q3)} – {money(maximum)} TL",
            "competition": "Daha düşük rekabet",
            "note": (
                "Daha az satıcının bulunduğu üst segment. Güçlü marka, yüksek puan, hızlı teslimat "
                "ve premium içerik gerektirir."
            ),
            "density": round((high_count / max_count) * 100),
            "listing_count": high_count,
        },
    ]
    insights = [
        f"{money(minimum)} – {money(q1)} TL aralığında fiyat rekabeti güçlü; marj baskısı daha yüksek.",
        f"{money(q1)} – {money(q3)} TL aralığı piyasanın dengeli fiyat koridoru.",
        f"{money(q3)} TL üzerindeki fiyatlarda doğrudan fiyat rekabeti azalıyor; güven ve sunum kalitesi daha önemli hale geliyor.",
        f"Hızlı satış için önerilen başlangıç fiyatı {money(recommended)} TL. Bu değer alt fiyat çeyreğinin hemen altında konumlanır.",
        f"Analiz {len(prices)} fiyat örneği üzerinden üretildi; stok, kargo ve satıcı doğrulaması sonucu değiştirebilir.",
    ]
    return {
        "recommended_price": recommended,
        "bands": bands,
        "insights": insights,
        "quartiles": {
            "minimum": str(minimum),
            "q1": str(q1),
            "median": str(median),
            "q3": str(q3),
            "maximum": str(maximum),
            "sample_count": len(prices),
        },
    }


def _simple_match(item, plan):
    detected = plan.get("detected_product", {})
    search_plan = plan.get("search_plan", {})
    haystack = f"{item.get('title', '')} {item.get('snippet', '')}".casefold()
    score = int(item.get("similarity") or 50)
    explanations = []
    brand = search_plan.get("required_brand") or detected.get("brand")
    if brand:
        if str(brand).casefold() in haystack:
            score += 15
            explanations.append("Marka eşleşiyor")
        elif search_plan.get("required_brand"):
            score -= 35
            explanations.append("Zorunlu marka doğrulanamadı")
    colors = search_plan.get("required_colors") or detected.get("colors") or []
    if colors:
        color_match = any(str(color).casefold() in haystack for color in colors)
        score += 10 if color_match else -20
        explanations.append("Renk eşleşiyor" if color_match else "Renk doğrulanamadı")
    score = max(0, min(100, score))
    threshold = 55 if search_plan.get("include_similar") else (
        80 if search_plan.get("same_product_required") else 55
    )
    eligible = score >= threshold
    return score, eligible, explanations


def _hard_constraint_rejection(research, item):
    """Reject explicit contradictions before accepting an AI similarity score."""
    requested = f"{research.title or ''} {research.prompt or ''}".casefold()
    candidate = f"{item.get('title', '')} {item.get('snippet', '')}".casefold()
    reasons = []

    wants_women = any(term in requested for term in ("kadın", "bayan"))
    male_terms = ("erkek", "bay ", "men ", "men's", "man ")
    women_terms = ("kadın", "bayan", "women", "woman", "unisex")
    if wants_women and any(term in candidate for term in male_terms):
        if not any(term in candidate for term in women_terms):
            reasons.append("Zorunlu kadın kategorisiyle çelişen erkek ürünü")

    wants_men = any(term in requested for term in ("erkek", "bay "))
    if wants_men and any(term in candidate for term in ("kadın", "bayan", "women", "woman")):
        if "unisex" not in candidate and "erkek" not in candidate:
            reasons.append("Zorunlu erkek kategorisiyle çelişen kadın ürünü")

    return reasons


def prefilter_candidates(research, items, plan):
    if not items:
        return {}
    reference = f"shopping-agent-prefilter:{research.id}"
    compact_items = [
        {
            "index": index,
            "title": item.get("verified_title") or item.get("title", ""),
            "snippet": item.get("snippet", "")[:500],
            "marketplace": item.get("marketplace_code", ""),
        }
        for index, item in enumerate(items[:35])
    ]
    prefilter_fingerprint = json.dumps(
        {
            "version": "shopping-prefilter-v3",
            "model": getattr(settings, "OPENAI_SHOPPING_PREFILTER_MODEL", "gpt-5.6-luna"),
            "plan": plan,
            "items": compact_items,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    cache_key = "mpr:prefilter:" + hashlib.sha256(prefilter_fingerprint.encode("utf-8")).hexdigest()
    cached_scores = cache.get(cache_key)
    if isinstance(cached_scores, dict):
        return copy.deepcopy(cached_scores)

    credit = consume_openai_operation(
        user=research.user,
        organization=research.organization,
        subscription=research.subscription,
        tariff_key=PREFILTER_TARIFF,
        reference=reference,
        reason="Alışveriş ajanı Luna ürün ön elemesi",
    )
    if not credit.allowed:
        raise MarketResearchProviderError(credit.reason)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "index": {"type": "integer"},
                        "score": {"type": "integer"},
                        "eligible": {"type": "boolean"},
                        "reasons": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["index", "score", "eligible", "reasons"],
                },
            }
        },
        "required": ["results"],
    }
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=2)
        response = create_response(
            client=client,
            tariff_key=PREFILTER_TARIFF,
            user=research.user,
            organization=research.organization,
            reference=reference,
            model=getattr(settings, "OPENAI_SHOPPING_PREFILTER_MODEL", "gpt-5.6-luna"),
            input=[{
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "Referans ürün planı ile aday ürünleri karşılaştır. Zorunlu marka/renk/model "
                        "şartlarını katı uygula. Her aday için 0-100 eşleşme puanı, uygunluk ve kısa "
                        f"gerekçeler üret.\nPLAN={json.dumps(plan, ensure_ascii=False)}\n"
                        f"ADAYLAR={json.dumps(compact_items, ensure_ascii=False)}"
                    ),
                }],
            }],
            text={"format": {"type": "json_schema", "name": "shopping_prefilter", "strict": True, "schema": schema}},
            max_output_tokens=5000,
        )
        parsed = json.loads(response.output_text)
        scores = {int(row["index"]): row for row in parsed.get("results", [])}
        cache.set(
            cache_key,
            copy.deepcopy(scores),
            timeout=_tariff_cache_timeout(PREFILTER_TARIFF, 60 * 60 * 24 * 7),
        )
        return scores
    except Exception:
        refund_ai_tariff_credits(
            user=research.user,
            organization=research.organization,
            tariff_key=PREFILTER_TARIFF,
            reference=reference,
            reason="Luna ürün ön elemesi tamamlanamadı",
        )
        # Ön filtre yardımcı bir aşamadır. Model çıktısı yarım kalırsa
        # araştırmayı düşürmek yerine yerel/deterministik eşleştirme devam eder.
        return {}


def persist_results(research, items, plan, ai_scores=None):
    MarketplaceProductResearchResult.objects.filter(research=research).delete()
    rows = []
    ai_scores = ai_scores or {}
    for index, item in enumerate(items):
        ai_result = ai_scores.get(index)
        if ai_result:
            score = max(0, min(100, int(ai_result.get("score", 0))))
            eligible = bool(ai_result.get("eligible")) or score >= 55
            explanations = [str(value) for value in ai_result.get("reasons", [])][:8]
        else:
            score, eligible, explanations = _simple_match(item, plan)
        hard_rejections = _hard_constraint_rejection(research, item)
        if hard_rejections:
            eligible = False
            score = min(score, 20)
            explanations = [*hard_rejections, *explanations]
        price = _decimal(item.get("price"))
        shipping = _decimal(item.get("shipping_price"))
        if score >= 85:
            explanations = ["Aynı ürün olma ihtimali yüksek.", *explanations]
        elif score >= 70:
            explanations = ["Çok benzer ürün.", *explanations]
        elif score >= 55:
            explanations = ["Benzer alternatif.", *explanations]
        rows.append(MarketplaceProductResearchResult(
            research=research,
            marketplace_id=item.get("marketplace_id"),
            provider=item.get("data_provider", ""),
            title=(item.get("verified_title") or item.get("title") or "Ürün")[:500],
            product_url=item.get("canonical_url") or item.get("url"),
            image_url=item.get("image_url", ""),
            seller_name=(item.get("seller") or "")[:255],
            price=price,
            shipping_price=shipping,
            total_price=price + shipping,
            currency=item.get("currency") or "TRY",
            match_score=score,
            is_eligible=eligible,
            verification_status=item.get("verification_status", "discovered"),
            match_explanation=explanations,
            raw_data=item,
            verified_at=timezone.now() if item.get("verification_status") == "page_opened" else None,
        ))
    MarketplaceProductResearchResult.objects.bulk_create(rows)
    eligible_rows = list(
        MarketplaceProductResearchResult.objects.filter(research=research, is_eligible=True)
        .order_by("total_price", "-match_score")
    )
    if eligible_rows:
        return eligible_rows

    closest = list(
        MarketplaceProductResearchResult.objects.filter(research=research, match_score__gt=20)
        .order_by("-match_score", "total_price")[:10]
    )
    for row in closest:
        row.is_eligible = True
        row.match_explanation = [
            *(row.match_explanation or []),
            "Kesin eşleşme bulunamadığı için en yakın alternatif olarak gösterildi.",
        ]
    MarketplaceProductResearchResult.objects.bulk_update(
        closest,
        ["is_eligible", "match_explanation"],
    )
    return sorted(closest, key=lambda row: (row.total_price, -row.match_score))


def final_quality_check(research, plan, rows):
    reference = f"shopping-agent-final-qa:{research.id}"
    credit = consume_openai_operation(
        user=research.user,
        organization=research.organization,
        subscription=research.subscription,
        tariff_key=QA_TARIFF,
        reference=reference,
        reason="Alışveriş ajanı Sol son kalite kontrolü",
    )
    if not credit.allowed:
        raise MarketResearchProviderError(credit.reason)
    compact = [{
        "id": row.id,
        "title": row.title,
        "marketplace": row.marketplace.code if row.marketplace else row.provider,
        "price": str(row.total_price),
        "match_score": str(row.match_score),
        "verification_status": row.verification_status,
    } for row in rows[:20]]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "summary": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "confidence": {"type": "integer"},
        },
        "required": ["summary", "warnings", "confidence"],
    }
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=2)
        response = create_response(
            client=client,
            tariff_key=QA_TARIFF,
            user=research.user,
            organization=research.organization,
            reference=reference,
            model=getattr(settings, "OPENAI_SHOPPING_QA_MODEL", "gpt-5.6-sol"),
            input=[{
                "role": "user",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "Bu alışveriş araştırmasının son kalite kontrolünü yap. Orijinalliği kesin "
                        "kanıtlanmamış ürünlere garanti verme; eksik doğrulamaları açıkça belirt. "
                        f"PLAN={json.dumps(plan, ensure_ascii=False)}\n"
                        f"SONUCLAR={json.dumps(compact, ensure_ascii=False)}"
                    ),
                }],
            }],
            text={"format": {"type": "json_schema", "name": "shopping_final_qa", "strict": True, "schema": schema}},
            max_output_tokens=2400,
        )
        return json.loads(response.output_text)
    except Exception:
        refund_ai_tariff_credits(
            user=research.user,
            organization=research.organization,
            tariff_key=QA_TARIFF,
            reference=reference,
            reason="Sol son kalite kontrolü tamamlanamadı",
        )
        # Son QA yarım JSON döndürürse bulunan gerçek sonuçları kaybetme.
        return {
            "summary": (
                f"{len(rows)} uygun ürün fiyat, benzerlik ve sayfa doğrulama "
                "sinyallerine göre sıralandı."
            ),
            "warnings": [
                "AI son kalite kontrolü tamamlanamadı; temel doğrulama ölçütleri kullanıldı."
            ],
            "confidence": 0,
        }


def run_shopping_agent(research):
    if research.generated_prompt and research.parsed_intent:
        plan = research.parsed_intent
    else:
        _set_progress(research, MarketplaceProductResearch.STATUS_ANALYZING, 10, "Görsel ve talimat analiz ediliyor")
        plan = generate_research_plan(research)
        research.generated_prompt = plan["professional_prompt"]
        research.parsed_intent = plan
        research.search_plan = plan["search_plan"]
        detected = plan["detected_product"]
        research.detected_product_name = detected.get("product_name", "")
        research.detected_category = detected.get("category", "")
        research.detected_attributes = detected.get("attributes", []) + detected.get("colors", [])
        research.save(update_fields=[
            "generated_prompt", "parsed_intent", "search_plan", "detected_product_name",
            "detected_category", "detected_attributes", "updated_at",
        ])
    _set_progress(
        research,
        MarketplaceProductResearch.STATUS_ANALYZING,
        22,
        "Profesyonel prompt oluşturuldu; pazaryeri araştırması başlıyor",
    )

    marketplaces = choose_marketplaces(research, plan)
    if not marketplaces:
        raise MarketResearchProviderError("Admin panelinde aktif ürün araştırma kaynağı bulunamadı.")
    source_selection = (
        (research.search_plan or {}).get("source_selection")
        or ("manual" if research.selected_marketplaces.exists() else "automatic")
    )
    research.selected_marketplaces.set(marketplaces)
    research.search_plan = {
        **(research.search_plan or {}),
        "source_selection": source_selection,
        "selected_marketplaces": [source.code for source in marketplaces],
    }
    research.save(update_fields=["search_plan", "updated_at"])
    items, search_errors = discover_candidates(research, plan, marketplaces)
    if not items:
        raise MarketResearchProviderError("Aktif pazaryerlerinde fiyatı doğrulanabilen ürün bulunamadı.")
    items, seller_offer_errors = expand_direct_seller_offers(items, marketplaces)
    search_errors.extend(seller_offer_errors)
    items, verify_errors = verify_candidate_pages(research, items, marketplaces)
    _set_progress(research, MarketplaceProductResearch.STATUS_MATCHING, 82, "Ürünler eşleştiriliyor ve sıralanıyor")
    ai_scores = prefilter_candidates(research, items, plan)
    normalized = persist_results(research, items, plan, ai_scores=ai_scores)
    if not normalized:
        raise MarketResearchProviderError("Fiyatı okunabilen bir ürün adayı bulunamadı.")
    qa = final_quality_check(research, plan, normalized)
    qa_points = []
    summary_text = str(qa.get("summary") or "").strip()
    if summary_text:
        qa_points.extend(
            part.strip()
            for part in re.split(r"(?<=[.!?])\s+|;\s*", summary_text)
            if part.strip()
        )
    qa_points.extend(str(value).strip() for value in qa.get("warnings", []) if str(value).strip())

    eligible_items = [row.raw_data | {
        "title": row.title,
        "price": str(row.price),
        "currency": row.currency,
        "similarity": int(row.match_score),
        "url": row.product_url,
        "platform": row.marketplace.name if row.marketplace else row.provider,
        "seller": row.seller_name,
        "competition_level": row.raw_data.get("competition_level", ""),
        "match_explanation": row.match_explanation,
    } for row in normalized]
    summary = summarize_price_items(eligible_items)
    if not summary:
        raise MarketResearchProviderError("Eşleşen ürünlerde kullanılabilir fiyat bilgisi bulunamadı.")
    price_strategy = build_price_strategy(eligible_items)
    verified_count = sum(
        1 for row in normalized
        if row.verification_status in {"verified", "page_opened"}
    )
    verified_price_count = sum(
        1 for row in normalized
        if (row.raw_data or {}).get("price_source") == "verified_product_page"
    )
    result_source_count = len({row.marketplace_id for row in normalized if row.marketplace_id})
    verification_coverage = (verified_count / len(normalized)) if normalized else 0
    source_coverage = result_source_count / max(1, len(marketplaces))
    average_match = sum(float(row.match_score) for row in normalized) / max(1, len(normalized))
    data_confidence = round(min(
        95,
        average_match * 0.35
        + verification_coverage * 45
        + source_coverage * 20,
    ))
    result = {
        "detected_product_name": research.detected_product_name,
        "detected_category": research.detected_category,
        "detected_attributes": research.detected_attributes,
        "items": eligible_items,
        "price_bands": price_strategy["bands"],
        **summary,
        "recommended_price": price_strategy["recommended_price"],
        "recommendation_summary": qa.get("summary") or (
            f"{len(marketplaces)} aktif kaynakta {len(items)} aday incelendi; "
            f"{len(normalized)} uygun sonuç toplam fiyata göre sıralandı."
        ),
        "confidence_score": Decimal(str(max(0, min(100, data_confidence)))),
        "raw_result": {
            "mode": "shopping_browser_agent",
            "professional_prompt": research.generated_prompt,
            "search_plan": research.search_plan,
            "selected_marketplaces": [source.code for source in marketplaces],
            "search_errors": search_errors,
            "verification_errors": verify_errors,
            "qa_warnings": qa.get("warnings", []),
            "qa_points": qa_points[:12],
            "research_insights": price_strategy["insights"],
            "price_strategy": price_strategy.get("quartiles", {}),
            "market_stats": {
                "active_model_count": len(normalized),
                "source_count": result_source_count,
                "selected_source_count": len(marketplaces),
                "verified_result_count": verified_count,
                "verified_price_count": verified_price_count,
                "verification_coverage_pct": round(verification_coverage * 100),
                "published_sales_count": 0,
                "sales_observation_count": 0,
                "sales_coverage_pct": 0,
                "confidence_score": data_confidence,
                "price_consistency": (
                    f"{verified_price_count}/{len(normalized)} fiyat ürün sayfasından doğrulandı"
                ),
                "sales_note": (
                    f"{len(marketplaces)} kaynak seçildi; {result_source_count} kaynak sonuç verdi. "
                    f"{verified_count} ürün sayfası açıldı, {verified_price_count} fiyat sayfadan doğrulandı."
                ),
            },
        },
    }
    apply_research_result(research, result)
    research.status = MarketplaceProductResearch.STATUS_PARTIAL if search_errors or verify_errors else MarketplaceProductResearch.STATUS_COMPLETED
    research.progress_percent = 100
    research.current_step = "Araştırma tamamlandı"
    research.finished_at = timezone.now()
    research.save(update_fields=["status", "progress_percent", "current_step", "finished_at", "updated_at"])
    return research
