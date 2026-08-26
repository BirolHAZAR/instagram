from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.services.ai_gateway import AIOperationBudget, create_chat_completion
from core.services.openai_usage import record_openai_token_usage


SIXTEEN_AGENT_NAMES = [
    "Performans Ajanı", "Bütçe Ajanı", "Kreatif Ajanı", "Reklam Metni Ajanı",
    "Görsel/Video Ajanı", "Hedef Kitle Ajanı", "Dönüşüm Ajanı", "Funnel Ajanı",
    "Maliyet Ajanı", "ROAS Ajanı", "Anomali Ajanı", "Risk Ajanı",
    "Tahmin Ajanı", "Platform Ajanı", "Rekabet Ajanı", "Görev Ajanı",
]

AGENT_FOCUS = {
    "Performans Ajanı": "KPI, trend, performans kirilimi ve kanita dayali ana bulgular",
    "Bütçe Ajanı": "butce dagilimi, marjinal getiri, artirma/azaltma karari",
    "Kreatif Ajanı": "kreatif yorgunluk, format, hook ve varyasyon stratejisi",
    "Reklam Metni Ajanı": "baslik, ana metin, teklif, CTA ve mesaj uyumu",
    "Görsel/Video Ajanı": "ilk kare, kompozisyon, okunabilirlik, tempo ve platform formati",
    "Hedef Kitle Ajanı": "segment, hedefleme, frekans ve kitle doygunlugu",
    "Dönüşüm Ajanı": "donusum kalitesi, tracking ve optimizasyon olayi",
    "Funnel Ajanı": "funnel asamalari ve darboğazlar",
    "Maliyet Ajanı": "CPC, CPM, CPA ve maliyet riski",
    "ROAS Ajanı": "gelir, ROAS, karlilik ve olcekleme esigi",
    "Anomali Ajanı": "beklenmeyen sapma ve veri anomalileri",
    "Risk Ajanı": "butce, marka, veri ve karar riskleri",
    "Tahmin Ajanı": "kisa vadeli olasi etki ve olcum plani",
    "Platform Ajanı": "platforma ozel format, teslimat ve optimizasyon sinyalleri",
    "Rekabet Ajanı": "rakip baskisi, farklilasma ve pazar boslugu",
    "Görev Ajanı": "bulgulari oncelikli, olculebilir aksiyonlara donusturme",
}


def run_sixteen_agent_orchestration(
    *, client, model, task, context, modalities=None, reference="ai_ecosystem",
    user=None, organization=None, max_workers=4, max_tokens_per_agent=350,
    tariff_key, usage_kind="customer_usage",
):
    """Run four independent calls, each returning four specialist agent results."""
    if usage_kind == "customer_usage" and user is None:
        usage_kind = "system_job"
    elif usage_kind == "customer_usage" and (
        getattr(user, "is_staff", False) or getattr(user, "is_superuser", False
    )):
        usage_kind = "admin_test"
    requested_modalities = modalities or ["text"]
    creative_url = (
        context.get("creative", {}).get("image_url")
        if isinstance(context, dict) and isinstance(context.get("creative"), dict)
        else None
    )

    budget = AIOperationBudget.from_tariff(tariff_key)
    groups = [SIXTEEN_AGENT_NAMES[index:index + 4] for index in range(0, 16, 4)]

    def call_group(group_index, names):
        prompt = {
            "task": task,
            "agents": [{"name": name, "specialty": AGENT_FOCUS.get(name, name)} for name in names],
            "context": context,
            "rules": [
                "Her ajan yalnizca kendi uzmanlik alaninda bagimsiz karar versin.",
                "Verilen metrik veya bulguya dayanmayan kesin iddia kurma.",
                "Her ajan icin tek bulgu ve tek uygulanabilir oneriyi JSON olarak dondur.",
            ],
            "schema": {"agents": [{"name": "string", "finding": "string", "recommendation": "string", "confidence": 0.0, "risk": "string"}]},
        }
        content = json.dumps(prompt, ensure_ascii=False, default=str)
        if (
            "Görsel/Video Ajanı" in names and "image" in requested_modalities and creative_url
            and str(creative_url).startswith(("http://", "https://", "data:image/"))
        ):
            content = [
                {"type": "text", "text": content},
                {"type": "image_url", "image_url": {"url": creative_url, "detail": "high"}},
            ]
        response = create_chat_completion(
            client=client,
            tariff_key=tariff_key,
            budget=budget,
            user=user,
            organization=organization,
            usage_kind=usage_kind,
            reference=f"{reference}.group.{group_index + 1}",
            record_usage=False,
            model=model,
            messages=[
                {"role": "system", "content": "Dort bagimsiz uzman ajani yonet. Her ajanin sonucunu ayri uret ve sadece gecerli JSON dondur."},
                {"role": "user", "content": content},
            ],
            temperature=0.2,
            reasoning_effort="low",
            max_tokens=max_tokens_per_agent * len(names),
            response_format={"type": "json_object"},
        )
        return group_index, names, response

    completed = []
    with ThreadPoolExecutor(max_workers=max(1, min(int(max_workers), 8))) as executor:
        futures = [executor.submit(call_group, index, names) for index, names in enumerate(groups)]
        for future in as_completed(futures):
            group_index, names, response = future.result()
            record_openai_token_usage(
                response, user=user, organization=organization,
                reference=f"{reference}.group.{group_index + 1}",
                operation_key=tariff_key, usage_kind=usage_kind, request_id=budget.request_id,
                note=f"Dortlu uzman ajan grubu: {', '.join(names)}",
            )
            payload = json.loads(response.choices[0].message.content or "{}")
            rows = payload.get("agents") or []
            by_name = {str(row.get("name") or ""): row for row in rows if isinstance(row, dict)}
            for offset, name in enumerate(names):
                row = by_name.get(name) or (rows[offset] if offset < len(rows) else {})
                finding = str(row.get("finding") or row.get("reason") or row.get("status") or "").strip()
                recommendation = str(row.get("recommendation") or row.get("action") or "").strip()
                # Model bazen 16 uzmani eksiksiz dondurup iki metin alanindan
                # yalnizca birini dolduruyor. Ayni islem icinde dolu metni yedek
                # kullanmak ek retry/OpenAI cagrisi ve token maliyeti olusturmaz.
                if not finding and recommendation:
                    finding = recommendation
                if not recommendation and finding:
                    recommendation = finding
                completed.append((group_index * 4 + offset, {
                    "name": name,
                    "finding": finding,
                    "recommendation": recommendation,
                    "confidence": max(0, min(float(row.get("confidence") or 0), 1)),
                    "risk": str(row.get("risk") or "").strip(),
                }))

    completed.sort(key=lambda row: row[0])
    agents = [row[1] for row in completed]
    # Bir uzmanın kanıtlı ek bulgu üretememesi tüm 16 ajanlık çalışmayı ve
    # kullanıcının ödediği çağrıyı geçersiz kılmamalı; UI boş maddeleri göstermez.
    if len(agents) != 16:
        raise RuntimeError(f"Gercek AI ekosistemi eksik ajan sonucu dondurdu: {len(agents)}/16")
    recommendations = [row["recommendation"] for row in agents]
    risks = [row["risk"] for row in agents if row["risk"]]
    return {
        "agents": agents,
        "strategy": {
            "positioning": agents[14]["recommendation"],
            "audience_insight": agents[5]["finding"],
            "message_pillars": recommendations[2:5],
            "visual_direction": agents[4]["recommendation"],
            "video_direction": agents[4]["recommendation"],
            "conversion_hypothesis": agents[6]["recommendation"],
            "risks": risks[:8],
            "variant_angles": recommendations[:6],
        },
    }


def _metric(metrics, key, default=0):
    try:
        return float(metrics.get(key) or default)
    except Exception:
        return float(default)


def _agent(name, status, reason, confidence=0.7, category="analysis"):
    return {
        "name": name,
        "status": status,
        "reason": reason,
        "confidence": round(float(confidence), 2),
        "category": category,
    }


def build_campaign_agent_ecosystem(metrics, detail=None, rule_events=None, recommendations=None):
    """Return a compact 16-agent signal set for campaign AI reports.

    This is a deterministic orchestration layer. Professional LLM prompts can be
    wired behind the same agent names after user approval, without changing the
    storage/UI contract.
    """
    detail = detail or {}
    rule_events = rule_events or []
    recommendations = recommendations or []

    roas = _metric(metrics, "roas")
    ctr = _metric(metrics, "ctr")
    cpc = _metric(metrics, "cpc")
    cpm = _metric(metrics, "cpm")
    spend = _metric(metrics, "spend")
    conversions = _metric(metrics, "conversions")
    revenue = _metric(metrics, "revenue")
    frequency = _metric(metrics, "frequency")
    impressions = _metric(metrics, "impressions")

    top_ad = (detail.get("top_ads") or [{"name": "-"}])[0].get("name", "-")
    creative_count = int(detail.get("creative_count") or 0)
    ad_count = int(detail.get("ad_count") or 0)
    rule_count = len(rule_events)
    rec_count = len(recommendations)

    return [
        _agent("Performans Ajanı", "Güçlü" if roas >= 2 else "İzle", f"ROAS {roas:.2f} ve dönüşüm {conversions:.0f} sinyali okundu.", 0.86 if roas >= 2 else 0.66),
        _agent("Bütçe Ajanı", "Artırılabilir" if roas >= 3 and conversions > 0 else ("Kısıtla" if spend > 0 and roas < 1 else "İzle"), f"Harcama {spend:.2f}, gelir {revenue:.2f}.", 0.82, "recommendation"),
        _agent("Kreatif Ajanı", "Yenile" if frequency >= 3 or ctr < 1 else "Koruyarak test et", f"Kreatif sayısı {creative_count}, en iyi reklam: {top_ad}.", 0.74),
        _agent("Reklam Metni Ajanı", "CTA kontrolü" if ctr < 1.5 else "Mesaj uyumu iyi", f"CTR {ctr:.2f} seviyesinde; başlık ve CTA etkisi izleniyor.", 0.68),
        _agent("Görsel/Video Ajanı", "İlk kare testi" if ctr < 1 else "Varyasyon üret", f"{ad_count} reklam ve {creative_count} kreatif sinyali incelendi.", 0.7),
        _agent("Hedef Kitle Ajanı", "Daralt/ayır" if cpc > 0 and ctr < 1.5 else "Segmentleri izle", f"CPC {cpc:.2f}, CTR {ctr:.2f}.", 0.69),
        _agent("Dönüşüm Ajanı", "Tracking kontrolü" if spend > 0 and conversions == 0 else "Dönüşüm okunuyor", f"Dönüşüm {conversions:.0f}, gelir {revenue:.2f}.", 0.85 if conversions > 0 else 0.76),
        _agent("Funnel Ajanı", "Darboğaz var" if impressions > 0 and conversions == 0 else "Akış izleniyor", f"Gösterim {impressions:.0f}, dönüşüm {conversions:.0f}.", 0.71),
        _agent("Maliyet Ajanı", "Maliyet baskısı" if cpc > 10 or cpm > 250 else "Maliyet normal", f"CPC {cpc:.2f}, CPM {cpm:.2f}.", 0.72),
        _agent("ROAS Ajanı", "Ölçekleme adayı" if roas >= 3 else ("Riskli" if spend > 0 and roas < 1 else "Nötr"), f"ROAS {roas:.2f}.", 0.84),
        _agent("Anomali Ajanı", "Kural sinyali var" if rule_count else "Kritik anomali yok", f"{rule_count} kural olayı eşleşti.", 0.8 if rule_count else 0.62),
        _agent("Risk Ajanı", "Yüksek risk" if spend > 0 and conversions == 0 else "Kontrollü", f"Harcama/dönüşüm dengesi kontrol edildi.", 0.77),
        _agent("Tahmin Ajanı", "Ölçüm bekle" if conversions == 0 else "Etki ölçülebilir", "Sonraki 3-7 gün için metrik takibi gerekli.", 0.64),
        _agent("Platform Ajanı", "Platform benchmark", f"Platform: {detail.get('platform') or '-'}, hesap: {detail.get('account_name') or '-'}", 0.66),
        _agent("Rekabet Ajanı", "Benchmark bekliyor", "Rakip sinyali varsa öneri önceliğine eklenir.", 0.58),
        _agent("Görev Ajanı", "Aksiyon hazır" if rec_count else "Analiz hazır", f"{rec_count} öneri/görev maddesi üretildi.", 0.75, "recommendation"),
    ]
