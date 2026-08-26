import base64
import hashlib
import json
import mimetypes
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from core.models import AIOperationTariff, FeatureUsageLedger, MarketplaceProductResearch, MarketplaceProductResearchMetricHistory
from core.services.notification_events import notify_user
from core.services.openai_usage import record_openai_token_usage
from core.services.usage_metering import consume_usage, record_usage_failure
from core.services.web_market_research import (
    MarketResearchProviderError,
    search_market,
    summarize_price_items,
)


def _money(value):
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _prompt_parts(prompt):
    return [part.strip() for part in (prompt or "").split(",") if part.strip()]


def _parse_json_content(content):
    content = (content or "").strip()
    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in content:
        content = content.split("```", 1)[1].split("```", 1)[0]
    return json.loads(content)


def analyze_product_image(research):
    """Ürün görselini arama sorgusuna dönüştürülebilecek yapılandırılmış veriye çevirir."""
    if not research.product_image:
        return {}
    api_key = getattr(settings, "OPENAI_API_KEY", "") or ""
    if not api_key:
        raise MarketResearchProviderError("Ürün görseli analizi için OPENAI_API_KEY tanımlı değil.")
    try:
        research.product_image.open("rb")
        image_bytes = research.product_image.read()
        research.product_image.close()
        context_fingerprint = json.dumps(
            {
                "title": research.title or "",
                "prompt": research.prompt or "",
                "model": getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                "version": "marketplace-vision-v2",
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        cache_key = "mpr:vision:" + hashlib.sha256(image_bytes + context_fingerprint).hexdigest()
        cached_result = cache.get(cache_key)
        if isinstance(cached_result, dict):
            return cached_result
        mime_type = mimetypes.guess_type(research.product_image.name)[0] or "image/jpeg"
        encoded = base64.b64encode(image_bytes).decode("ascii")
        from core.services.ai_gateway import create_chat_completion_http
        payload = create_chat_completion_http(
            api_url="https://api.openai.com/v1/chat/completions",
            api_key=api_key,
            tariff_key="vision-analysis",
            reference=f"marketplace.product_research.vision:{research.id}",
            payload={
                "model": getattr(settings, "OPENAI_MODEL", "gpt-4o"),
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Sen Türkiye e-ticaret pazar araştırması için ürün görseli sınıflandıran bir uzmansın. "
                            "Yalnızca görselde açıkça görülen özellikleri yaz ve sadece JSON döndür."
                        ),
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "Ürünü tanımla. JSON şeması: "
                                    '{"product_name":"", "category":"", "brand":"", "attributes":[""], "search_terms":[""]}. '
                                    f"Kullanıcının ek bağlamı: {research.title} {research.prompt}"
                                ),
                            },
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                        ],
                    },
                ],
                "max_tokens": 500,
                "temperature": 0.1,
            },
            timeout=45,
        )
        result = _parse_json_content(payload["choices"][0]["message"]["content"])
        normalized_result = {
            "product_name": str(result.get("product_name") or "").strip(),
            "category": str(result.get("category") or "").strip(),
            "brand": str(result.get("brand") or "").strip(),
            "attributes": [str(value).strip() for value in result.get("attributes", []) if str(value).strip()][:12],
            "search_terms": [str(value).strip() for value in result.get("search_terms", []) if str(value).strip()][:8],
        }
        cache_timeout = (
            AIOperationTariff.objects.filter(key="vision-analysis", is_active=True)
            .values_list("cache_timeout_seconds", flat=True)
            .first()
        )
        cache.set(
            cache_key,
            normalized_result,
            timeout=int(cache_timeout if cache_timeout is not None else 60 * 60 * 24 * 30),
        )
        return normalized_result
    except MarketResearchProviderError:
        raise
    except Exception as exc:
        raise MarketResearchProviderError(f"Ürün görseli analiz edilemedi: {exc}") from exc


def _research_query(research, vision_result=None):
    vision_result = vision_result or {}
    parts = _prompt_parts(research.prompt)
    query_parts = [
        research.title,
        research.prompt,
        vision_result.get("product_name"),
        vision_result.get("category"),
        vision_result.get("brand"),
        *vision_result.get("attributes", []),
        *vision_result.get("search_terms", []),
    ]
    if research.product_id:
        query_parts.extend([
            research.product.name,
            research.product.brand,
            research.product.category_name,
            research.product.barcode,
            research.product.sku,
        ])
    query = " ".join([str(part).strip() for part in query_parts if str(part or "").strip()])
    if query:
        return query, parts
    raise MarketResearchProviderError("Urun arastirmasi icin baslik, urun veya ozellik girilmedi.")


def build_marketplace_research_result(research):
    # Takip kontrollerinde ilk araştırmada üretilen ürün kimliğini tekrar kullan.
    # Böylece aynı görsel her periyotta yeniden AI Vision'a gönderilmez ve ürün
    # kimliği kontroller arasında daha kararlı kalır.
    parsed_product = (research.parsed_intent or {}).get("detected_product") or {}
    if parsed_product:
        vision_result = {
            "product_name": parsed_product.get("product_name") or research.detected_product_name,
            "category": parsed_product.get("category") or research.detected_category,
            "brand": parsed_product.get("brand") or "",
            "attributes": parsed_product.get("attributes") or research.detected_attributes or [],
            "search_terms": parsed_product.get("search_terms") or [],
        }
    else:
        vision_result = analyze_product_image(research)
    query, parts = _research_query(research, vision_result)
    search_query = f"{query} Türkiye güncel fiyat TL satın al"
    provider_errors = []
    try:
        items = search_market(search_query, max_results=20, include_tavily=False)
    except MarketResearchProviderError as exc:
        provider_errors.append(str(exc))
        items = []
    if not items:
        detail = f" Sağlayıcı: {'; '.join(provider_errors)}" if provider_errors else ""
        raise MarketResearchProviderError(f"Canlı web araştırmasında fiyatı doğrulanabilen ürün bulunamadı.{detail}")

    price_summary = summarize_price_items(items)
    if not price_summary:
        raise MarketResearchProviderError("Canli arama sonucunda okunabilir fiyat bilgisi bulunamadi.")

    min_price = price_summary["min_price"]
    max_price = price_summary["max_price"]
    average_price = price_summary["average_price"]
    recommended_price = price_summary["recommended_price"]
    spread = max(Decimal("1.00"), (max_price - min_price) / Decimal("3"))

    detected_name = vision_result.get("product_name") or research.title or (research.product.name if research.product_id else "") or (parts[0] if parts else "Ürün")
    detected_category = vision_result.get("category") or (parts[1] if len(parts) > 1 else (research.product.category_name if research.product_id else "Genel"))
    detected_attributes = list(dict.fromkeys([*parts, *vision_result.get("attributes", [])]))
    source_count = len({item.get("platform") for item in items if item.get("platform")})
    sales_items = [item for item in items if int(item.get("sold_count") or 0) > 0]
    published_sales_count = sum(int(item.get("sold_count") or 0) for item in sales_items)
    sales_coverage = round((len(sales_items) / len(items)) * 100) if items else 0
    price_ratio = (max_price / min_price) if min_price else Decimal("99")
    confidence = min(
        95,
        35
        + min(len(items), 10) * 3
        + min(source_count, 4) * 8
        + min(len(sales_items), 3) * 4
        + (10 if len(items) >= 5 and price_ratio <= Decimal("2.5") else 0),
    )
    market_stats = {
        "active_model_count": len(items),
        "source_count": source_count,
        "published_sales_count": published_sales_count,
        "sales_observation_count": len(sales_items),
        "sales_coverage_pct": sales_coverage,
        "confidence_score": confidence,
        "price_consistency": "Yüksek" if price_ratio <= Decimal("1.6") else ("Orta" if price_ratio <= Decimal("2.5") else "Düşük"),
        "structured_price_count": sum(1 for item in items if item.get("price_source") == "structured_extracted_price"),
        "tavily_evidence_count": 0,
        "price_sample_source": price_summary.get("sample_source", "combined"),
        "sales_note": (
            "Satış adedi, kaynak sayfalarda açıkça yayınlanan satış sinyallerinin toplamıdır."
            if sales_items
            else "İncelenen kaynaklar satış adedi yayınlamadığı için doğrulanmış adet verisi bulunamadı."
        ),
    }

    price_bands = [
        {
            "label": f"{int(min_price)}-{int(min_price + spread)} TL",
            "competition": "Yuksek rekabet",
            "note": "Canli arama sonucunda alt fiyat bandi yogun rekabet sinyali olarak degerlendirildi.",
            "density": 68,
        },
        {
            "label": f"{int(average_price - spread / 2)}-{int(average_price + spread / 2)} TL",
            "competition": "Dengeli rekabet",
            "note": "Ortalama piyasa fiyati etrafinda dengeli konumlandirma alani.",
            "density": 46,
        },
        {
            "label": f"{int(max_price - spread)}-{int(max_price + spread)} TL",
            "competition": "Dusuk rekabet",
            "note": "Ust fiyat bandi daha guclu gorsel, yorum ve marka guveni ister.",
            "density": 22,
        },
    ]

    summary = (
        f"{source_count} farklı dijital kaynakta {len(items)} benzersiz satış modeli doğrulandı. "
        f"En düşük fiyat {min_price} TL, en yüksek fiyat {max_price} TL ve ortalama fiyat {average_price} TL. "
        f"Önerilen satış fiyatı {recommended_price} TL. "
        + (
            f"Kaynakların açıkça yayınladığı doğrulanabilir satış toplamı {published_sales_count} adet."
            if sales_items
            else "Kaynaklar doğrulanabilir satış adedi yayınlamadı."
        )
    )

    return {
        "detected_product_name": detected_name,
        "detected_category": detected_category,
        "detected_attributes": detected_attributes,
        "items": items,
        "price_bands": price_bands,
        "min_price": min_price,
        "max_price": max_price,
        "average_price": average_price,
        "recommended_price": recommended_price,
        "recommendation_summary": summary,
        "confidence_score": Decimal(str(confidence)),
        "raw_result": {
            "mode": "live_market_research",
            "query": query,
            "vision_input": bool(research.product_image),
            "vision_result": vision_result,
            "prompt_attributes": parts,
            "provider_note": "Görsel OpenAI Vision ile sınıflandırıldı; ürün ve fiyatlar SerpAPI Google Shopping yapılandırılmış verisinden alındı.",
            "market_stats": market_stats,
            "search_query_count": 1,
            "provider_errors": provider_errors,
        },
    }


def competition_counts(items):
    counts = {"high": 0, "medium": 0, "low": 0}
    for item in items:
        level = item.get("competition_level", "")
        if "Yuksek" in level or "Yüksek" in level:
            counts["high"] += 1
        elif "Orta" in level:
            counts["medium"] += 1
        else:
            counts["low"] += 1
    return counts


def _price_change(previous_price, current_price):
    current_price = _money(current_price)
    if previous_price is None:
        return None, Decimal("0.00"), Decimal("0.00"), MarketplaceProductResearchMetricHistory.CHANGE_STABLE

    previous_price = _money(previous_price)
    change = _money(current_price - previous_price)
    change_percent = _money((change / previous_price) * Decimal("100")) if previous_price else Decimal("0.00")
    if change > 0:
        direction = MarketplaceProductResearchMetricHistory.CHANGE_UP
    elif change < 0:
        direction = MarketplaceProductResearchMetricHistory.CHANGE_DOWN
    else:
        direction = MarketplaceProductResearchMetricHistory.CHANGE_STABLE
    return previous_price, change, change_percent, direction


def _notify_research_price_change(research, history):
    if history.change_direction == MarketplaceProductResearchMetricHistory.CHANGE_STABLE:
        return None

    direction_label = "yukseldi" if history.change_direction == MarketplaceProductResearchMetricHistory.CHANGE_UP else "dustu"
    level = "success" if history.change_direction == MarketplaceProductResearchMetricHistory.CHANGE_UP else "warning"
    icon = "fa-arrow-trend-up" if history.change_direction == MarketplaceProductResearchMetricHistory.CHANGE_UP else "fa-arrow-trend-down"
    product_name = research.detected_product_name or research.title or "Takip edilen urun"
    return notify_user(
        user=research.user,
        title=f"Fiyat takibi: {product_name}",
        message=(
            f"Onerilen fiyat {history.previous_recommended_price} TL seviyesinden "
            f"{history.recommended_price} TL seviyesine {direction_label}. "
            f"Degisim: {history.recommended_price_change} TL (%{history.recommended_price_change_percent})."
        ),
        level=level,
        icon=icon,
        link="/pazaryeri/fiyat-takibi/",
    )


def apply_research_result(research, result):
    research.detected_product_name = result["detected_product_name"]
    research.detected_category = result["detected_category"]
    research.detected_attributes = result["detected_attributes"]
    research.result_items = result["items"]
    research.price_bands = result["price_bands"]
    research.min_price = result["min_price"]
    research.max_price = result["max_price"]
    research.average_price = result["average_price"]
    research.recommended_price = result["recommended_price"]
    research.recommendation_summary = result["recommendation_summary"]
    research.confidence_score = result["confidence_score"]
    research.raw_result = result["raw_result"]
    research.source = "live_market"
    research.status = MarketplaceProductResearch.STATUS_COMPLETED
    if research.track_price:
        now = timezone.now()
        research.last_tracked_at = now
        research.next_tracking_at = now + timedelta(hours=research.tracking_interval_hours or 24)
    research.save()
    history = record_research_metric_history(research, result)
    if research.track_price:
        _notify_research_price_change(research, history)
    return research


def mark_research_failed(research, exc):
    research.status = MarketplaceProductResearch.STATUS_FAILED
    research.source = "live_market"
    research.raw_result = {"mode": "live_market_research", "error": str(exc)}
    research.recommendation_summary = str(exc)
    research.save(update_fields=["status", "source", "raw_result", "recommendation_summary", "updated_at"])
    return research


def record_research_metric_history(research, result=None, checked_at=None):
    result = result or {
        "items": research.result_items,
        "price_bands": research.price_bands,
        "min_price": research.min_price,
        "max_price": research.max_price,
        "average_price": research.average_price,
        "recommended_price": research.recommended_price,
        "raw_result": research.raw_result,
    }
    counts = competition_counts(result["items"])
    previous_history = (
        MarketplaceProductResearchMetricHistory.objects.filter(research=research)
        .order_by("-checked_at", "-id")
        .first()
    )
    previous_price, price_change, price_change_percent, change_direction = _price_change(
        previous_history.recommended_price if previous_history else None,
        result["recommended_price"],
    )
    return MarketplaceProductResearchMetricHistory.objects.create(
        research=research,
        user=research.user,
        organization=research.organization,
        subscription=research.subscription,
        product=research.product,
        checked_at=checked_at or timezone.now(),
        min_price=result["min_price"],
        max_price=result["max_price"],
        average_price=result["average_price"],
        recommended_price=result["recommended_price"],
        previous_recommended_price=previous_price,
        recommended_price_change=price_change,
        recommended_price_change_percent=price_change_percent,
        change_direction=change_direction,
        result_count=len(result["items"]),
        high_competition_count=counts["high"],
        medium_competition_count=counts["medium"],
        low_competition_count=counts["low"],
        result_items=result["items"],
        price_bands=result["price_bands"],
        raw_result=result["raw_result"],
    )


def refresh_tracked_research(research):
    usage_result = consume_usage(
        user=research.user,
        organization=research.organization,
        subscription=research.subscription,
        operation=FeatureUsageLedger.OP_MARKETPLACE_PRICE_CHECK,
        reference=f"marketplace.price_check.research:{research.id}",
        note="Fiyat inceleme API otomatik yenileme",
    )
    if not usage_result.allowed:
        research.next_tracking_at = timezone.now() + timedelta(hours=research.tracking_interval_hours or 24)
        research.save(update_fields=["next_tracking_at", "updated_at"])
        return research

    try:
        result = build_marketplace_research_result(research)
    except MarketResearchProviderError as exc:
        record_usage_failure(
            user=research.user,
            organization=research.organization,
            subscription=research.subscription,
            operation=FeatureUsageLedger.OP_MARKETPLACE_PRICE_CHECK,
            reference=f"marketplace.price_check.research:{research.id}",
            note=str(exc),
            usage_ledger=usage_result.ledger,
        )
        retry_at = timezone.now() + timedelta(hours=min(1, research.tracking_interval_hours or 24))
        raw_result = dict(research.raw_result or {})
        raw_result["tracking_last_error"] = str(exc)
        raw_result["tracking_last_error_at"] = timezone.now().isoformat()
        research.raw_result = raw_result
        research.next_tracking_at = retry_at
        research.save(update_fields=["raw_result", "next_tracking_at", "updated_at"])
        return research
    return apply_research_result(research, result)


def refresh_due_tracked_researches(limit=50):
    from core.services.agency_permission_matrix import get_user_entitlement_plan
    now = timezone.now()
    researches = MarketplaceProductResearch.objects.filter(
        track_price=True,
        status__in=[
            MarketplaceProductResearch.STATUS_COMPLETED,
            MarketplaceProductResearch.STATUS_PARTIAL,
        ],
        next_tracking_at__lte=now,
    ).select_related("user", "organization", "subscription", "product").order_by("next_tracking_at")[:limit]
    refreshed = 0
    for research in researches:
        plan = get_user_entitlement_plan(research.user)
        if not plan or (plan.name != "trial_14" and int(plan.marketplace_price_check_per_month or 0) <= 0):
            continue
        refresh_tracked_research(research)
        refreshed += 1
    return refreshed
