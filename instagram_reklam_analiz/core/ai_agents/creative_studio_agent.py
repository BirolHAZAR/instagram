import json
import logging
import os
import base64
import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from django.conf import settings
from openai import OpenAI

from core.services.openai_usage import record_openai_token_usage
from core.services.ai_agent_ecosystem import SIXTEEN_AGENT_NAMES, run_sixteen_agent_orchestration
from core.services.cache_service import CacheService

logger = logging.getLogger(__name__)


class ContentTone(str, Enum):
    PROFESSIONAL = "professional"
    FRIENDLY = "friendly"
    URGENT = "urgent"
    LUXURY = "luxury"
    HUMOROUS = "humorous"
    EMOTIONAL = "emotional"
    EDUCATIONAL = "educational"


@dataclass
class GeneratedVariant:
    variant_number: int
    headline: str
    primary_text: str
    description: str
    cta: str
    hashtags: List[str]
    visual_brief: str
    visual_prompt: str
    video_brief: str
    video_prompt: str
    shot_list: List[str]
    landing_page_hook: str
    ai_score: float
    predicted_engagement: float
    predicted_ctr: float
    competitive_advantage: str
    target_emotion: str


class CreativeStudioAgent:
    def __init__(self, model: Optional[str] = None, user=None, organization=None):
        self.model = model or getattr(settings, "OPENAI_CREATIVE_WORK_MODEL", "gpt-5.6-terra")
        self.analysis_model = getattr(settings, "OPENAI_CREATIVE_ANALYSIS_MODEL", "gpt-5.6-sol")
        self.qa_model = getattr(settings, "OPENAI_CREATIVE_QA_MODEL", "gpt-5.6-sol")
        self.user = user
        self.organization = organization
        self.api_key = getattr(settings, "OPENAI_API_KEY", "") or os.getenv("OPENAI_API_KEY") or ""
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY tanimli degil; Creative Studio sahte icerik uretmez.")
        self.client = OpenAI(api_key=self.api_key)
        self.last_ecosystem = {}
        self.last_ecosystem_cache_hit = False
        self.last_quality_review = {}
        self.tone_directives = {
            ContentTone.PROFESSIONAL: "Profesyonel, kurumsal ve guvenilir bir dil kullan.",
            ContentTone.FRIENDLY: "Samimi, sicak ve arkadasca bir dil kullan.",
            ContentTone.URGENT: "Harekete gecirici, aciliyet hissi veren bir dil kullan.",
            ContentTone.LUXURY: "Luks, prestijli ve premium hissiyat veren bir dil kullan.",
            ContentTone.HUMOROUS: "Eglenceli ve markaya uygun mizahi bir dil kullan.",
            ContentTone.EMOTIONAL: "Duygusal bag kuran ve hikayesel bir dil kullan.",
            ContentTone.EDUCATIONAL: "Bilgilendirici ve deger katan bir dil kullan.",
        }

    def generate_from_competitor_ad(
        self,
        competitor_ad,
        num_variants: int = 3,
        tone: ContentTone = ContentTone.PROFESSIONAL,
        target_audience: Optional[str] = None,
        product_description: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        language: str = "tr",
    ) -> List[GeneratedVariant]:
        competitor_insights = self._analyze_competitor_ad(competitor_ad)
        ecosystem = self._run_creative_ecosystem(
            competitor_ad=competitor_ad, competitor_insights=competitor_insights,
            target_audience=target_audience, product_description=product_description,
            keywords=keywords, tone=tone, language=language,
        )
        return [
            self._generate_single_variant(
                competitor_ad=competitor_ad,
                competitor_insights=competitor_insights,
                variant_number=i,
                tone=tone,
                target_audience=target_audience,
                product_description=product_description,
                keywords=keywords,
                language=language,
                ecosystem_context=ecosystem,
            )
            for i in range(1, num_variants + 1)
        ]

    def generate_from_scratch(
        self,
        num_variants: int = 3,
        tone: ContentTone = ContentTone.PROFESSIONAL,
        target_audience: Optional[str] = None,
        product_description: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        campaign_objective: str = "CONVERSIONS",
        language: str = "tr",
    ) -> List[GeneratedVariant]:
        ecosystem = self._run_creative_ecosystem(
            target_audience=target_audience, product_description=product_description,
            keywords=keywords, tone=tone, language=language,
        )
        return [
            self._generate_single_variant(
                competitor_ad=None,
                competitor_insights=None,
                variant_number=i,
                tone=tone,
                target_audience=target_audience,
                product_description=product_description,
                keywords=keywords,
                campaign_objective=campaign_objective,
                language=language,
                ecosystem_context=ecosystem,
            )
            for i in range(1, num_variants + 1)
        ]

    def _run_creative_ecosystem(
        self, competitor_ad=None, competitor_insights=None, target_audience=None,
        product_description=None, keywords=None, tone=ContentTone.PROFESSIONAL,
        language="tr",
    ) -> Dict:
        self.last_ecosystem_cache_hit = False
        source = {
            "competitor_title": getattr(competitor_ad, "title", "") if competitor_ad else "",
            "competitor_description": getattr(competitor_ad, "description", "") if competitor_ad else "",
            "competitor_insights": competitor_insights or {},
            "product_description": product_description or "",
            "master_prompt_rule": (
                "product_description AI görsel analizinden gelen ana prompttur ve bağlayıcıdır. Ürün kategorisini, görünen özellikleri, "
                "malzemeyi, rengi, oranları, ambalajı, logo/marka yerleşimini ve kullanım biçimini değiştirme. Her varyantta ürün aynı kalsın; "
                "yalnızca yaratıcı açı, sahne, kompozisyon, ışık ve iletişim yaklaşımı belirgin biçimde farklılaşsın. Ana prompt insan, manken "
                "veya mekân istemiyorsa bunları ekleme."
            ),
            "target_audience": target_audience or "",
            "keywords": keywords or [],
            "tone": tone.value,
            "language": language,
        }
        cache_payload = json.dumps(source, ensure_ascii=False, sort_keys=True, default=str)
        cache_digest = hashlib.sha256(cache_payload.encode("utf-8")).hexdigest()
        cache_owner = getattr(self.user, "id", None) or "system"
        demo_cache_disabled = getattr(self.user, "username", "") == "demo"
        if not demo_cache_disabled:
            cached = CacheService.get("creative_studio_ecosystem", cache_owner, cache_digest)
            if isinstance(cached, dict) and len(cached.get("agents") or []) == len(SIXTEEN_AGENT_NAMES):
                self.last_ecosystem = cached
                self.last_ecosystem_cache_hit = True
                return cached

        data = run_sixteen_agent_orchestration(
            client=self.client,
            model=self.model,
            task="Reklam için özgün metin ve görsel alternatif stratejisi oluştur.",
            context=source,
            modalities=["text", "image"],
            reference="creative_studio.ecosystem",
            user=self.user,
            organization=self.organization,
            tariff_key="creative-studio-content",
            max_tokens_per_agent=320,
        )
        agents = data.get("agents") or []
        if len(agents) != len(SIXTEEN_AGENT_NAMES):
            raise RuntimeError(f"16 ajan analizi eksik döndü: {len(agents)}/16")
        self.last_ecosystem = data
        if not demo_cache_disabled:
            CacheService.set(
                "creative_studio_ecosystem",
                cache_owner,
                cache_digest,
                value=data,
                timeout=30 * 60,
            )
        return data

    def generate_professional_prompt_from_references(
        self,
        references,
        *,
        user_context: str = "",
        platform: str = "instagram",
    ) -> str:
        if not references:
            raise ValueError("Profesyonel prompt oluşturmak için en az bir referans görsel gereklidir.")

        content = [{
            "type": "input_text",
            "text": (
                "Yüklenen referansları kıdemli bir reklam kreatif direktörü, ürün tasarımcısı, kategori uzmanı ve ürün fotoğrafçısı gibi analiz et. "
                "Önce bunun hangi ürün kategorisi olduğunu yalnızca görsel kanıtlardan belirle; tekstil, kozmetik veya başka bir kategori olduğunu varsayma. "
                "Ürünün türünü, kullanım amacını, biçimini, ölçü/oran ilişkisini, ambalajını, marka ve logo yerleşimini, renklerini, malzemelerini, "
                "yüzey dokusunu, parçalarını, fonksiyonel ayrıntılarını, varyantlarını ve ayırt edici bütün fiziksel özelliklerini dikkatle çıkar. "
                "Görseller farklı açılardaysa aynı ürüne ait ayrıntıları birleştir; çelişen veya görünmeyen bir özelliği uydurma. "
                "Ardından bu ürün kategorisinin bugünkü en güçlü premium reklam ve sosyal medya görsel trendini seç. Trend seçimini ürünün gerçek "
                "özelliklerine, hedef kullanımına, fiyat/konumlandırma sinyaline ve hedef platforma göre gerekçeli biçimde görsel konsepte yansıt. "
                "Canlı manken, el modeli, yaşam alanı, dış mekân, mimari mekân, stüdyo seti, makro ürün çekimi, flat-lay, levitasyon, teknik kesit "
                "veya kullanım anı seçeneklerinden yalnızca ürünü daha doğru ve ikna edici gösterecek olanı kullan; her ürüne otomatik olarak manken "
                "ya da mekân ekleme. İnsan kullanılacaksa anatomik doğruluk, doğal temas, gerçekçi ölçek ve ürünün kullanım biçimi açıkça tanımlansın. "
                "Ürünün kimliğini, ambalajını, logosunu, rengini, malzemesini, biçimini ve ayırt edici fiziksel ayrıntılarını değiştirmeden, "
                "görsel üretim modeline doğrudan verilecek tek ve ayrıntılı, ultra profesyonel ana prompt yaz. "
                f"Hedef platform: {platform}. Kullanıcının ek bağlamı: {user_context or 'Yok; görselden doğru bağlamı çıkar.'}\n\n"
                "Nihai prompt; tespit edilen ürün özelliklerini, korunması zorunlu ayrıntıları, hedef kitleyi, kategoriye uygun güncel trendi, "
                "ürüne özel ana yaratıcı fikri, kullanılacak veya özellikle kullanılmayacak insan/manken/mekân kararını, kullanım senaryosunu, "
                "kompozisyon ve kadrajı, ürünün sahnedeki ölçeğini ve pozisyonunu, arka plan/set tasarımını, ışık şemasını, kamera açısı ve lensi, "
                "alan derinliğini, renk paletini, doku ve malzeme gerçekçiliğini, gölge/yansıma davranışını, premium post-prodüksiyonu, "
                "1:1 sosyal medya formatını, metin için güvenli boş alanı ve birbirinden belirgin varyasyon yönlerini açıkça tanımlasın. "
                "Okunaksız yazı, bozuk logo, ek ürün, deforme nesne, filigran, yapay plastik görünüm ve telifli karakterleri özellikle dışlasın. "
                "Görselde kesin olarak görülmeyen teknik özellik, içerik, performans, sağlık veya satış iddiası uydurma. "
                "Yanıtı yalnızca geçerli JSON olarak döndür. Şema: "
                '{"prompt":"görsel üretim sistemine doğrudan verilecek ayrıntılı nihai Türkçe prompt",'
                '"keywords":["ürün kategorisi","ayırt edici özellik","malzeme/doku","kullanım amacı","hedef kitle","trend/konsept"]}. '
                "keywords alanında görselde doğrulanabilen ve üretimi yönlendiren 6-12 kısa, tekrarsız anahtar kelime kullan; görünmeyen özellik veya iddia ekleme."
            ),
        }]
        for image_index, (_filename, image_bytes, content_type) in enumerate(list(references)[:10]):
            mime_type = content_type if str(content_type).startswith("image/") else "image/jpeg"
            encoded = base64.b64encode(image_bytes).decode("ascii")
            content.append({
                "type": "input_image",
                "image_url": f"data:{mime_type};base64,{encoded}",
                "detail": "high" if image_index < 4 else "low",
            })
        content[0]["text"] += (
            "\n\nAyrıca ChatGPT düzeyinde yaratıcı danışmanlık sun: birbirinden belirgin üç profesyonel kampanya yönü öner. "
            "Her yön için kısa başlık, ürüne neden uygun olduğu, ayrıntılı konsept ve master prompta eklenebilecek prompt_addition üret. "
            "Nihai JSON şu ek alanları da içersin: analysis_summary ve creative_directions. "
            "creative_directions şeması: [{\"title\":\"...\",\"why\":\"...\",\"concept\":\"...\",\"prompt_addition\":\"...\"}]."
        )

        from core.services.ai_gateway import create_response
        response = create_response(
            client=self.client,
            tariff_key="creative-studio-prompt",
            user=self.user,
            organization=self.organization,
            reference="creative_studio.reference_prompt",
            model=self.analysis_model,
            input=[
                {
                    "role": "developer",
                    "content": [{
                        "type": "input_text",
                        "text": (
                        "Sen dünya standartlarında reklam kreatif direktörü, ürün tasarımcısı, kategori trend uzmanı, ürün fotoğrafçısı ve "
                        "görsel üretim prompt mühendisisin. Her ürünün kategorisini görselden yeniden tespit eder, tekstil veya manken varsayımı "
                        "yapmaz, ürüne en uygun güncel kreatif yaklaşımı seçer ve referans ürünü birebir koruyan uygulanabilir promptlar yazarsın. "
                        "Yalnızca istenen şemada geçerli JSON döndürürsün."
                        ),
                    }],
                },
                {"role": "user", "content": content},
            ],
            reasoning={"effort": "low"},
            text={
                "format": {
                    "type": "json_schema",
                    "name": "creative_product_analysis",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "prompt": {"type": "string"},
                            "keywords": {"type": "array", "items": {"type": "string"}},
                            "analysis_summary": {"type": "string"},
                            "creative_directions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "title": {"type": "string"},
                                        "why": {"type": "string"},
                                        "concept": {"type": "string"},
                                        "prompt_addition": {"type": "string"},
                                    },
                                    "required": ["title", "why", "concept", "prompt_addition"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["prompt", "keywords", "analysis_summary", "creative_directions"],
                        "additionalProperties": False,
                    },
                },
            },
            max_output_tokens=4000,
        )
        if getattr(response, "status", "") == "incomplete":
            raise RuntimeError("Sol ürün analizi çıktı sınırına ulaştı; analiz tamamlanamadı.")
        payload = self._json_from_response(response.output_text)
        prompt = str(payload.get("prompt") or "").strip()
        keywords = [
            str(item).strip()
            for item in (payload.get("keywords") or [])
            if str(item).strip()
        ][:12]
        if not prompt:
            raise RuntimeError("Görsel analizi profesyonel prompt üretemedi.")
        directions = [
            {
                "title": str(item.get("title") or "").strip()[:100],
                "why": str(item.get("why") or "").strip()[:500],
                "concept": str(item.get("concept") or "").strip()[:1000],
                "prompt_addition": str(item.get("prompt_addition") or "").strip()[:1800],
            }
            for item in (payload.get("creative_directions") or [])
            if isinstance(item, dict) and str(item.get("title") or "").strip()
        ][:3]
        return {
            "prompt": prompt,
            "keywords": keywords,
            "analysis_summary": str(payload.get("analysis_summary") or "").strip()[:1200],
            "creative_directions": directions,
        }

    def review_variants(self, variants, *, product_prompt: str, carousel_mode: bool = False):
        """One Sol pass reviews all Terra outputs; no per-variant review calls."""
        if not variants:
            return variants
        from core.services.ai_gateway import create_response

        review_payload = {
            "product_master_prompt": product_prompt,
            "format": "carousel" if carousel_mode else "single_image_variants",
            "variants": [
                {
                    "variant_number": row.variant_number,
                    "headline": row.headline,
                    "primary_text": row.primary_text,
                    "description": row.description,
                    "cta": row.cta,
                    "hashtags": row.hashtags,
                    "visual_prompt": row.visual_prompt,
                }
                for row in variants
            ],
            "success_criteria": [
                "Ürün kimliği ve görselde doğrulanan fiziksel özellikler eksiksiz korunmalı.",
                "Görsel prompt uygulanabilir, ticari, foto-gerçekçi ve kategoriye özgü olmalı.",
                "Başlık, metin, CTA ve hashtagler ürünle tutarlı ve yayınlanmaya hazır olmalı.",
                "Uydurma teknik, sağlık, performans veya satış iddiası bulunmamalı.",
                "Varyantlar birbirinden belirgin olmalı; carousel ise tek sanat yönetiminde ilerlemeli.",
            ],
            "output_schema": {
                "overall_score": 0,
                "review_summary": "string",
                "variants": [{
                    "variant_number": 1,
                    "headline": "string",
                    "primary_text": "string",
                    "description": "string",
                    "cta": "string",
                    "hashtags": ["string"],
                    "visual_prompt": "string",
                }],
            },
        }
        response = create_response(
            client=self.client,
            tariff_key="creative-studio-final-review",
            user=self.user,
            organization=self.organization,
            reference="creative_studio.final_quality_review",
            model=self.qa_model,
            input=[
                {
                    "role": "developer",
                    "content": [{
                        "type": "input_text",
                        "text": (
                            "Kıdemli global Creative Director ve marka güvenliği denetçisisin. "
                            "Terra tarafından hazırlanan bütün varyantları tek geçişte denetle ve yalnızca gerekli düzeltmeleri yap. "
                            "Ürün gerçekliğini bozma, metinleri boş bırakma, gereksiz uzatma yapma. Yalnızca geçerli JSON döndür."
                        ),
                    }],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": json.dumps(review_payload, ensure_ascii=False)}],
                },
            ],
            reasoning={"effort": "low"},
            text={
                "format": {
                    "type": "json_schema",
                    "name": "creative_final_review",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "overall_score": {"type": "number"},
                            "review_summary": {"type": "string"},
                            "variants": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "variant_number": {"type": "integer"},
                                        "headline": {"type": "string"},
                                        "primary_text": {"type": "string"},
                                        "description": {"type": "string"},
                                        "cta": {"type": "string"},
                                        "hashtags": {"type": "array", "items": {"type": "string"}},
                                        "visual_prompt": {"type": "string"},
                                    },
                                    "required": [
                                        "variant_number", "headline", "primary_text", "description",
                                        "cta", "hashtags", "visual_prompt",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["overall_score", "review_summary", "variants"],
                        "additionalProperties": False,
                    },
                },
            },
            max_output_tokens=2200,
        )
        if getattr(response, "status", "") == "incomplete":
            raise RuntimeError("Sol final kalite kontrolü çıktı sınırına ulaştı.")
        payload = self._json_from_response(response.output_text)
        reviewed_by_number = {
            int(item.get("variant_number") or 0): item
            for item in (payload.get("variants") or [])
            if isinstance(item, dict)
        }
        for row in variants:
            reviewed = reviewed_by_number.get(int(row.variant_number))
            if not reviewed:
                continue
            for field_name, limit in (
                ("headline", 40), ("primary_text", 300), ("description", 1000),
                ("cta", 40), ("visual_prompt", 5000),
            ):
                value = str(reviewed.get(field_name) or "").strip()
                if value:
                    setattr(row, field_name, value[:limit])
            reviewed_hashtags = reviewed.get("hashtags")
            if isinstance(reviewed_hashtags, list) and reviewed_hashtags:
                row.hashtags = [str(item).strip().lstrip("#") for item in reviewed_hashtags[:10] if str(item).strip()]
        self.last_quality_review = {
            "score": max(0, min(float(payload.get("overall_score") or 0), 100)),
            "summary": str(payload.get("review_summary") or "").strip()[:800],
            "model": self.qa_model,
        }
        return variants

    def generate_visual(self, prompt: str, reference=None) -> bytes:
        image_model = getattr(settings, "OPENAI_IMAGE_MODEL", "gpt-image-2")
        if reference:
            references = reference if isinstance(reference, list) else [reference]
            images = [(filename, content, content_type) for filename, content, content_type in references]
            edit_kwargs = {
                "model": image_model,
                "image": images,
                "prompt": (
                    "Use all uploaded images as multi-angle references for the exact same real product. First identify the product category and "
                    "all visible physical, material, functional, packaging, color, logo, proportion, texture, and construction details. Preserve "
                    "those details with high fidelity. Do not assume the product is apparel and do not add a model, person, hand, location, or "
                    "lifestyle scene unless the supplied creative prompt explicitly requires it and it is appropriate for the detected product. "
                    "Never invent unseen technical features, claims, accessories, text, logos, or a different product. Create a current premium "
                    f"commercial visual with photorealistic materials and anatomically correct human interaction when applicable. {prompt}"
                ),
                "size": "1024x1024",
                "quality": "medium",
                "n": 1,
            }
            # GPT Image 2 preserves references natively and rejects input_fidelity.
            if image_model != "gpt-image-2":
                edit_kwargs["input_fidelity"] = "high"
            result = self.client.images.edit(**edit_kwargs)
        else:
            result = self.client.images.generate(
                model=image_model,
                prompt=prompt,
                size="1024x1024",
                quality="medium",
                n=1,
            )
        item = result.data[0]
        if getattr(item, "b64_json", None):
            return base64.b64decode(item.b64_json)
        raise RuntimeError("Görsel modeli görüntü verisi döndürmedi.")

    def generate_video(self, prompt: str, reference=None) -> bytes:
        input_reference = None
        if reference:
            if isinstance(reference, list):
                reference = reference[0]
            filename, content, content_type = reference
            input_reference = (filename, content, content_type)
        video_kwargs = {
            "model": getattr(settings, "OPENAI_VIDEO_MODEL", "sora-2"),
            "prompt": f"Create an original, high-end advertising alternative inspired by the reference composition and mood, without copying text, logos, or protected characters. {prompt}",
            "seconds": "8",
            "size": "720x1280",
        }
        if input_reference:
            video_kwargs["input_reference"] = input_reference
        try:
            video = self.client.videos.create_and_poll(**video_kwargs)
        except Exception:
            if not input_reference:
                raise
            # Some Sora accounts/models can create videos but reject or fail
            # during the separate reference-media upload. Preserve production
            # continuity by retrying the same creative brief without the file.
            video_kwargs.pop("input_reference", None)
            video_kwargs["prompt"] = (
                "Create the strongest original vertical advertising video from this creative brief. "
                + prompt
            )
            video = self.client.videos.create_and_poll(**video_kwargs)
        if getattr(video, "status", "") != "completed":
            raise RuntimeError("Video modeli üretimi tamamlamadı.")
        response = self.client.videos.download_content(video.id)
        content = getattr(response, "content", None)
        if content:
            return content
        if hasattr(response, "read"):
            return response.read()
        raise RuntimeError("Video modeli video verisi döndürmedi.")

    def _json_from_response(self, content: str) -> Dict:
        content = (content or "").strip()
        if "```json" in content:
            content = content.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in content:
            content = content.split("```", 1)[1].split("```", 1)[0]
        try:
            return json.loads(content.strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError("AI çıktısı tamamlanmadan kesildi veya geçerli JSON üretilemedi.") from exc

    def _analyze_competitor_ad(self, ad) -> Dict:
        title = getattr(ad, "title", None) or getattr(ad, "headline", None) or getattr(ad, "name", "")
        description = getattr(ad, "description", None) or getattr(ad, "primary_text", None) or ""
        prompt = {
            "task": "Rakip reklamini analiz et, kopyalama yapma.",
            "title": title,
            "description": description,
            "schema": {
                "strength": "string",
                "emotional_trigger": "string",
                "target_segment": "string",
                "weakness": "string",
                "improvement_opportunity": "string",
                "estimated_budget_range": "string",
                "target_audience_guess": "string",
            },
        }
        from core.services.ai_gateway import create_chat_completion
        response = create_chat_completion(
            client=self.client, tariff_key="creative-studio-content",
            user=self.user, organization=self.organization,
            reference="creative_studio.competitor_analysis",
            model=self.model,
            messages=[
                {"role": "system", "content": "Sen kidemli reklam kreatif analiz uzmanisin. Sadece JSON dondur."},
                {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
            ],
            temperature=0.35,
            max_tokens=900,
        )
        return self._json_from_response(response.choices[0].message.content)

    def _generate_single_variant(
        self,
        competitor_ad=None,
        competitor_insights: Optional[Dict] = None,
        variant_number: int = 1,
        tone: ContentTone = ContentTone.PROFESSIONAL,
        target_audience: Optional[str] = None,
        product_description: Optional[str] = None,
        keywords: Optional[List[str]] = None,
        campaign_objective: str = "CONVERSIONS",
        language: str = "tr",
        ecosystem_context: Optional[Dict] = None,
    ) -> GeneratedVariant:
        competitor_title = ""
        if competitor_ad:
            competitor_title = getattr(competitor_ad, "title", None) or getattr(competitor_ad, "headline", None) or getattr(competitor_ad, "name", "")
        payload = {
            "language": "Turkce" if language == "tr" else "English",
            "tone": self.tone_directives.get(tone, self.tone_directives[ContentTone.PROFESSIONAL]),
            "campaign_objective": campaign_objective,
            "variant_number": variant_number,
            "target_audience": target_audience or "",
            "product_description": product_description or "",
            "master_prompt_rule": (
                "product_description bağlayıcı ana görsel prompttur. Ürünün tespit edilen türünü, görünen özelliklerini, malzemesini, rengini, "
                "oranlarını, ambalajını, marka/logo yerleşimini ve kullanım biçimini koru. Varyantlarda ürün aynı kalmalı; yalnızca yaratıcı açı, "
                "sahne, kompozisyon, ışık ve iletişim yaklaşımı farklılaşmalı. Ana prompt insan, manken veya mekân istemiyorsa bunları ekleme."
            ),
            "keywords": keywords or [],
            "competitor_context": {
                "ad": competitor_title,
                "insights": competitor_insights or {},
                "instruction": "Rakip reklamdan fikir al ama kopyalama. Daha ozgun ve daha ikna edici aci uret.",
            },
            "sixteen_agent_ecosystem": (
                (ecosystem_context or {}).get("strategy", {})
                if isinstance(ecosystem_context, dict)
                else {}
            ),
            "variant_diversity_rule": f"Bu {variant_number}. varyanttır. strategy.variant_angles içindeki farklı bir açıyı kullan; diğer varyantlarla aynı hook, CTA ve görsel kompozisyonu tekrar etme.",
            "post_content_rule": (
                "Bu çıktı yalnızca görsel promptu değildir; yayınlanmaya hazır eksiksiz bir sosyal medya postudur. headline, primary_text, "
                "description, cta ve hashtags alanlarının hiçbiri boş olamaz. Metinler referans görselden tespit edilen gerçek ürün özellikleri, "
                "hedef kitle, seçilen güncel kreatif trend ve bu varyantın özgün iletişim açısıyla tutarlı olmalı. Görselde doğrulanmayan özellik "
                "veya iddia ekleme. Başlık güçlü ve kısa; ana metin doğal, ikna edici ve ürüne özel; açıklama destekleyici; CTA eylem odaklı; "
                "hashtagler 5-10 adet, ilgili ve tekrarsız olsun."
            ),
            "required_schema": {
                "headline": "max 40 chars",
                "primary_text": "max 300 chars",
                "description": "max 1000 chars",
                "cta": "string",
                "hashtags": ["string"],
                "visual_brief": "string",
                "visual_prompt": "Detailed English image prompt for a distinct premium 1:1 social post variation",
                "landing_page_hook": "string",
                "ai_score": 0,
                "predicted_engagement": 0,
                "predicted_ctr": 0,
                "competitive_advantage": "string",
                "target_emotion": "string",
            },
        }
        from core.services.ai_gateway import create_chat_completion
        response = create_chat_completion(
            client=self.client, tariff_key="creative-studio-content",
            user=self.user, organization=self.organization,
            reference="creative_studio.variant",
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Sen Instagram ve Meta için ürün görseli, reklam metni ve dönüşüm odaklı sosyal medya postu üreten kıdemli Creative "
                        "Director ve Copywriter'sın. Görsel promptuyla birlikte başlık, ana metin, açıklama, CTA ve hashtagleri eksiksiz üret. "
                        "Zorunlu alanları boş bırakma ve yalnızca geçerli JSON döndür."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0.75,
            reasoning_effort="low",
            max_tokens=3000,
            response_format={"type": "json_object"},
        )
        data = self._json_from_response(response.choices[0].message.content)
        def clean_text(value, limit):
            return str(value or "").strip()[:limit]

        landing_page_hook = clean_text(data.get("landing_page_hook"), 220)
        visual_brief = clean_text(data.get("visual_brief"), 1200)
        headline = clean_text(data.get("headline"), 40) or clean_text(landing_page_hook, 40) or "Ürünü Yeni Bir Bakışla Keşfedin"
        primary_text = clean_text(data.get("primary_text"), 300) or clean_text(data.get("description"), 300) or clean_text(visual_brief, 300)
        if not primary_text:
            primary_text = "Ürünün özgün detaylarını ve kullanım deneyimini keşfedin."
        description = clean_text(data.get("description"), 1000) or clean_text(primary_text, 1000)
        cta = clean_text(data.get("cta"), 40) or "Şimdi Keşfet"
        hashtag_rows = data.get("hashtags") if isinstance(data.get("hashtags"), list) else []
        if not hashtag_rows:
            hashtag_rows = keywords or ["ürün", "yenilik", "tasarım", "keşfet"]
        hashtags = []
        for item in hashtag_rows:
            tag = "".join(char for char in str(item).strip().replace(" ", "") if char.isalnum() or char == "_")
            if tag:
                normalized = f"#{tag.lstrip('#')}"
                if normalized.lower() not in {row.lower() for row in hashtags}:
                    hashtags.append(normalized)
            if len(hashtags) >= 10:
                break
        visual_prompt = clean_text(data.get("visual_prompt"), 5000) or clean_text(product_description, 5000)
        return GeneratedVariant(
            variant_number=variant_number,
            headline=headline,
            primary_text=primary_text,
            description=description,
            cta=cta,
            hashtags=hashtags,
            visual_brief=visual_brief or description,
            visual_prompt=visual_prompt,
            video_brief="",
            video_prompt="",
            shot_list=[],
            landing_page_hook=landing_page_hook or headline,
            ai_score=float(data.get("ai_score", 0) or 0),
            predicted_engagement=float(data.get("predicted_engagement", 0) or 0),
            predicted_ctr=float(data.get("predicted_ctr", 0) or 0),
            competitive_advantage=data.get("competitive_advantage", ""),
            target_emotion=data.get("target_emotion", ""),
        )
