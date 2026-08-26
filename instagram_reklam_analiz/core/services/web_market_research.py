import copy
import hashlib
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import cache

from core.services.tavily_usage import mark_tavily_request_result, reserve_tavily_request


PRICE_RE = re.compile(
    r"(?:(?:TRY|TL|₺)\s*([0-9][0-9\.\s]*(?:,[0-9]{1,2})?)|"
    r"([0-9][0-9\.\s]*(?:,[0-9]{1,2})?)\s*(?:TRY|TL|₺))",
    re.IGNORECASE,
)
SALES_RE = re.compile(
    r"(?P<count>[0-9][0-9\.\s]*(?:,[0-9]+)?)\s*(?P<suffix>bin|b|k)?\s*\+?\s*"
    r"(?:adet\s+)?(?:kişi\s+)?(?:tarafından\s+)?(?:satıldı|satış|satis|satın\s+aldı|satın\s+alındı)",
    re.IGNORECASE,
)


class MarketResearchProviderError(RuntimeError):
    pass


def _clean_text(value):
    return " ".join(str(value or "").split())


def _decimal_from_price(text):
    if not text:
        return None
    match = PRICE_RE.search(str(text))
    if not match:
        return None
    raw_match = match.group(1) or match.group(2)
    raw = raw_match.replace(" ", "").replace(".", "").replace(",", ".")
    try:
        value = Decimal(raw).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return value if value > 0 else None


def _prices_from_text(text):
    prices = []
    for match in PRICE_RE.finditer(str(text or "")):
        raw_match = match.group(1) or match.group(2)
        raw = raw_match.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            value = Decimal(raw).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            continue
        if value > 0:
            prices.append(value)
    return prices


def _representative_price(text):
    minimum = Decimal(str(getattr(settings, "MARKET_RESEARCH_MIN_PRICE", 10) or 10))
    maximum = Decimal(str(getattr(settings, "MARKET_RESEARCH_MAX_PRICE", 1000000) or 1000000))
    prices = sorted(price for price in _prices_from_text(text) if minimum <= price <= maximum)
    return prices[len(prices) // 2] if prices else None


def extract_sales_signal(text):
    """Yalnızca açıkça yayınlanmış satış/satın alma adetlerini döndürür."""
    signals = []
    source = str(text or "")
    for match in SALES_RE.finditer(source):
        raw = match.group("count").replace(" ", "").replace(".", "").replace(",", ".")
        try:
            count_value = Decimal(raw)
        except (InvalidOperation, ValueError):
            continue
        if (match.group("suffix") or "").lower() in {"bin", "b", "k"}:
            count_value *= 1000
        count = int(count_value)
        if not 0 < count <= 100_000_000:
            continue
        start = max(0, match.start() - 55)
        end = min(len(source), match.end() + 55)
        signals.append((count, _clean_text(source[start:end])))
    if not signals:
        return 0, ""
    return max(signals, key=lambda value: value[0])


def _coerce_price(value):
    if value in (None, ""):
        return None
    try:
        price = Decimal(str(value)).quantize(Decimal("0.01"))
        return price if price > 0 else None
    except (InvalidOperation, ValueError):
        return _decimal_from_price(value)


def _domain(url):
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _tokens(value):
    normalized = unicodedata.normalize("NFKD", _clean_text(value).lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return {
        token for token in re.findall(r"[a-z0-9]{2,}", normalized)
        if token not in {"fiyat", "urun", "satin", "benzer"}
    }


def enrich_market_items(items, query):
    """Fiyatı bulunan sonuçlara benzerlik ve rekabet sinyali ekler."""
    query_tokens = _tokens(query)
    priced_items = []
    for source_item in items:
        item = dict(source_item)
        price = _coerce_price(item.get("price")) or _decimal_from_price(
            f"{item.get('title', '')} {item.get('snippet', '')}"
        )
        if not price:
            continue
        item_tokens = _tokens(f"{item.get('title', '')} {item.get('snippet', '')}")
        coverage = len(query_tokens & item_tokens) / max(1, len(query_tokens))
        item["price"] = str(price)
        item["currency"] = "TRY"
        item["similarity"] = min(98, max(35, round(35 + coverage * 63)))
        priced_items.append(item)

    if not priced_items:
        return []

    prices = sorted(Decimal(item["price"]) for item in priced_items)
    median = prices[len(prices) // 2]
    for item in priced_items:
        ratio = Decimal(item["price"]) / median if median else Decimal("1")
        if ratio <= Decimal("0.85"):
            item["competition_level"] = "Yüksek rekabet"
        elif ratio >= Decimal("1.15"):
            item["competition_level"] = "Düşük rekabet"
        else:
            item["competition_level"] = "Orta rekabet"
    return priced_items


def consolidate_market_items(items, query, max_results=20):
    """Çoklu sorgu sonuçlarını tekilleştirir ve belirgin fiyat aykırılarını dışlar."""
    unique = {}
    for item in enrich_market_items(items, query):
        url = str(item.get("url") or "").split("?", 1)[0].rstrip("/").lower()
        title_key = " ".join(sorted(_tokens(item.get("title"))))
        product_id = str(item.get("product_id") or "").strip()
        key = f"product:{product_id}" if product_id else (url or title_key)
        if not key:
            continue
        current = unique.get(key)
        item_rank = (float(item.get("source_reliability") or 0), int(item.get("similarity") or 0))
        current_rank = (
            float(current.get("source_reliability") or 0),
            int(current.get("similarity") or 0),
        ) if current else (-1, -1)
        if current is None or item_rank > current_rank:
            unique[key] = item

    consolidated = list(unique.values())
    if len(consolidated) >= 4:
        structured_prices = sorted(
            Decimal(item["price"])
            for item in consolidated
            if item.get("price_source") == "structured_extracted_price"
        )
        prices = structured_prices if len(structured_prices) >= 3 else sorted(
            Decimal(item["price"]) for item in consolidated
        )
        median = prices[len(prices) // 2]
        lower = median * Decimal("0.35")
        upper = median * Decimal("2.85")
        consolidated = [item for item in consolidated if lower <= Decimal(item["price"]) <= upper]
    consolidated.sort(
        key=lambda item: (
            float(item.get("source_reliability") or 0),
            int(item.get("similarity") or 0),
            int(item.get("sold_count") or 0),
        ),
        reverse=True,
    )
    primary = [item for item in consolidated if item.get("data_provider") == "serpapi_google_shopping"]
    secondary = [item for item in consolidated if item.get("data_provider") != "serpapi_google_shopping"]
    if primary and secondary and max_results >= 4:
        secondary_slots = max(1, max_results // 4)
        return [*primary[: max_results - secondary_slots], *secondary[:secondary_slots]]
    return consolidated[:max_results]


def _tavily_search(query, max_results):
    api_key = getattr(settings, "TAVILY_API_KEY", "") or ""
    if not api_key:
        return None
    reservation = reserve_tavily_request(query=query, reference="web_market_research.search")
    if not reservation.allowed:
        raise MarketResearchProviderError(reservation.reason)
    response = None
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "advanced",
                "include_answer": False,
                "include_raw_content": "markdown",
                "max_results": max_results,
            },
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:
        mark_tavily_request_result(
            reservation,
            response_status=getattr(response, "status_code", None),
            error_message=str(exc),
        )
        raise
    mark_tavily_request_result(reservation, response_status=response.status_code)
    payload = response.json()
    items = []
    for item in payload.get("results", []):
        title = _clean_text(item.get("title"))
        content = _clean_text(item.get("content"))
        raw_content = _clean_text(item.get("raw_content"))
        url = item.get("url") or ""
        price = _representative_price(f"{title} {content} {raw_content}")
        sold_count, sales_evidence = extract_sales_signal(f"{title} {content} {raw_content}")
        items.append({
            "platform": _domain(url) or "Web",
            "title": title,
            "seller": _domain(url) or "",
            "price": str(price) if price else "",
            "currency": "TRY" if price else "",
            "similarity": "",
            "competition_level": "",
            "url": url,
            "image_url": "",
            "snippet": (content or raw_content)[:1500],
            "sold_count": sold_count,
            "sales_evidence": sales_evidence,
            "sales_data_type": "published" if sold_count else "unavailable",
            "data_provider": "tavily",
            "price_source": "page_content",
            "source_reliability": 0.65,
        })
    return items


def _serpapi_search(query, max_results):
    api_key = getattr(settings, "SERPAPI_API_KEY", "") or ""
    if not api_key:
        return None
    params = {
        "engine": "google_shopping",
        "q": query,
        "gl": "tr",
        "hl": "tr",
        "location": getattr(settings, "SERPAPI_LOCATION", "Istanbul, Turkey"),
        "api_key": api_key,
    }
    source_items = []
    page_count = max(1, min(3, (int(max_results) + 19) // 20))
    last_error = None
    for page_number in range(page_count):
        page_params = {**params, "start": page_number * 20}
        response = None
        for _attempt in range(2):
            try:
                response = requests.get(
                    "https://serpapi.com/search.json",
                    params=page_params,
                    timeout=int(getattr(settings, "SERPAPI_TIMEOUT", 35) or 35),
                )
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                last_error = exc
        if response is None or not response.ok:
            if not source_items:
                raise MarketResearchProviderError(f"SerpAPI bağlantısı başarısız: {last_error}")
            break
        payload = response.json()
        if payload.get("error"):
            if not source_items:
                raise MarketResearchProviderError(str(payload["error"]))
            break
        page_items = payload.get("shopping_results") or []
        source_items.extend(page_items)
        if len(page_items) < 20:
            break
    items = []
    for item in source_items[:max_results]:
        title = _clean_text(item.get("title"))
        snippet = _clean_text(item.get("snippet") or item.get("description"))
        # Prefer the seller page; product_link can point to an intermediary Google Shopping page.
        url = item.get("link") or item.get("product_link") or ""
        price = _coerce_price(item.get("extracted_price")) or _decimal_from_price(item.get("price"))
        sold_count, sales_evidence = extract_sales_signal(f"{title} {snippet}")
        items.append({
            "platform": item.get("source") or _domain(url) or "Google",
            "title": title,
            "seller": item.get("source") or _domain(url) or "",
            "price": str(price) if price else "",
            "currency": "TRY" if price else "",
            "similarity": "",
            "competition_level": "",
            "url": url,
            "image_url": item.get("thumbnail") or "",
            "snippet": snippet[:500],
            "sold_count": sold_count,
            "sales_evidence": sales_evidence,
            "sales_data_type": "published" if sold_count else "unavailable",
            "data_provider": "serpapi_google_shopping",
            "price_source": "structured_extracted_price",
            "source_reliability": 0.95,
            "product_id": item.get("product_id") or "",
            "serpapi_immersive_product_api": item.get("serpapi_immersive_product_api") or "",
            "rating": item.get("rating"),
            "reviews": item.get("reviews"),
            "delivery": item.get("delivery") or "",
        })
    return items


def search_market(query, max_results=None, *, include_tavily=True):
    max_results = max(1, min(int(max_results or getattr(settings, "MARKET_RESEARCH_MAX_RESULTS", 8)), 60))
    query = _clean_text(query)
    if not query:
        raise MarketResearchProviderError("Arama sorgusu bos.")
    cache_payload = (
        f"market-search-v3|{query.casefold()}|{max_results}|"
        f"{int(bool(getattr(settings, 'SERPAPI_API_KEY', '')))}|"
        f"{int(bool(include_tavily and getattr(settings, 'TAVILY_API_KEY', '')))}"
    )
    cache_key = "mpr:search:" + hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()
    cached_items = cache.get(cache_key)
    if isinstance(cached_items, list) and cached_items:
        return copy.deepcopy(cached_items)

    configured_providers = []
    if getattr(settings, "SERPAPI_API_KEY", ""):
        configured_providers.append(("serpapi", _serpapi_search))
    if include_tavily and getattr(settings, "TAVILY_API_KEY", ""):
        configured_providers.append(("tavily", _tavily_search))

    errors = []
    collected = []
    with ThreadPoolExecutor(max_workers=max(1, len(configured_providers))) as executor:
        futures = {
            executor.submit(provider, query, max_results): name
            for name, provider in configured_providers
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                items = future.result()
            except Exception as exc:
                errors.append(f"{name}: {exc}")
                continue
            if items is not None:
                collected.extend(item for item in items if item.get("title") or item.get("url"))

    if collected:
        normalized_items = consolidate_market_items(collected, query, max_results=max_results)
        if normalized_items:
            cache.set(cache_key, copy.deepcopy(normalized_items), timeout=60 * 15)
        return normalized_items

    if errors:
        raise MarketResearchProviderError("; ".join(errors))
    if include_tavily:
        raise MarketResearchProviderError("SERPAPI_API_KEY veya TAVILY_API_KEY tanımlı değil.")
    raise MarketResearchProviderError("Ürün araştırması için SERPAPI_API_KEY tanımlı değil.")


def summarize_price_items(items):
    structured_items = [
        item for item in items
        if item.get("price_source") == "structured_extracted_price" and item.get("price")
    ]
    price_items = structured_items if len(structured_items) >= 3 else items
    prices = []
    for item in price_items:
        raw_price = item.get("price")
        try:
            price = Decimal(str(raw_price)).quantize(Decimal("0.01")) if raw_price else None
        except (InvalidOperation, ValueError):
            price = _decimal_from_price(raw_price)
        if price:
            prices.append(price)
    if not prices:
        return None
    min_price = min(prices)
    max_price = max(prices)
    avg_price = (sum(prices) / len(prices)).quantize(Decimal("0.01"))
    recommended = (avg_price * Decimal("0.98")).quantize(Decimal("0.01"))
    return {
        "min_price": min_price,
        "max_price": max_price,
        "average_price": avg_price,
        "recommended_price": recommended,
        "sample_count": len(prices),
        "sample_source": "serpapi_google_shopping" if len(structured_items) >= 3 else "combined",
    }


def build_campaign_market_context(campaign, top_ads):
    terms = [campaign.name]
    for ad in (top_ads or [])[:3]:
        terms.extend([ad.get("headline"), ad.get("primary_text"), ad.get("description")])
    query = " ".join([_clean_text(term) for term in terms if _clean_text(term)])[:500]
    if not query:
        return {"enabled": False, "items": [], "note": "Arama icin kampanya veya reklam metni bulunamadi."}
    try:
        items = search_market(f"{query} rakip reklam fiyat pazar trendi", max_results=6)
    except MarketResearchProviderError as exc:
        return {"enabled": False, "items": [], "note": str(exc)}
    return {
        "enabled": True,
        "query": query,
        "items": items,
        "price_summary": summarize_price_items(items),
        "note": "Canli web arastirmasi provider uzerinden yapildi.",
    }
