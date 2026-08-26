# core/views/creative_studio.py
import json
import logging
import hashlib
from urllib.parse import urljoin

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.ai_agents.error_manager import capture_errors
from core.ai_agents.creative_studio_agent import CreativeStudioAgent, ContentTone
from core.models import Ad, CreativeProject, CreativeTemplate, FeatureUsageLedger, GeneratedContent, InstagramAccount, InstagramPostQueue, PlatformAccount, SocialPost
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.services.ai_credit_purchase import insufficient_credit_payload
from core.services.organic_publish import publish_post
from core.services.organic_platforms import ORGANIC_PUBLISH_PLATFORM_CODES, get_organic_publish_platform, organic_publish_platform_rows
from core.services.agency_scope import get_agency_scope, platform_accounts_for_request
from core.services.cache_service import CacheService

logger = logging.getLogger(__name__)


def _public_media_url(value):
    """Return the externally reachable URL Meta and other platforms can fetch."""
    media_url = str(value or "").strip()
    if not media_url:
        return ""
    if media_url.startswith(("http://", "https://")):
        return media_url
    public_base = (
        getattr(settings, "PUBLIC_MEDIA_BASE_URL", "")
        or getattr(settings, "SITE_URL", "")
    ).rstrip("/") + "/"
    return urljoin(public_base, media_url.lstrip("/"))


@login_required
@capture_errors
def creative_studio(request):
    agency_scope = get_agency_scope(request)
    context = {
        "page_title": "Creative Studio - AI İçerik Üretici",
        "my_projects": CreativeProject.objects.filter(user=request.user).order_by("-created_at")[:20],
        "templates": CreativeTemplate.objects.filter(Q(user=request.user) | Q(is_public=True))[:20],
        "publish_platforms": organic_publish_platform_rows(),
        "agency_scope": agency_scope,
    }
    return render(request, "creative_studio/dashboard.html", context)


def _tone(value):
    tone_map = {
        "professional": ContentTone.PROFESSIONAL,
        "friendly": ContentTone.FRIENDLY,
        "urgent": ContentTone.URGENT,
        "luxury": ContentTone.LUXURY,
        "humorous": ContentTone.HUMOROUS,
        "emotional": ContentTone.EMOTIONAL,
        "educational": ContentTone.EDUCATIONAL,
    }
    return tone_map.get(value or "professional", ContentTone.PROFESSIONAL)


def _read_reference_images(request):
    reference_files = request.FILES.getlist("reference_media")
    if not reference_files:
        raise ValueError("AI promptu için en az bir ürün görseli yükleyin.")
    if len(reference_files) > 10:
        raise ValueError("En fazla 10 ürün görseli ekleyebilirsiniz.")

    references = []
    total_reference_size = 0
    for reference_file in reference_files:
        content_type = getattr(reference_file, "content_type", "") or ""
        if not content_type.startswith("image/"):
            raise ValueError("Yalnızca görsel dosyaları yükleyebilirsiniz.")
        total_reference_size += reference_file.size
        if reference_file.size > 15 * 1024 * 1024 or total_reference_size > 50 * 1024 * 1024:
            raise ValueError("Her görsel en fazla 15 MB, toplam dosya boyutu en fazla 50 MB olabilir.")
        references.append((reference_file.name, reference_file.read(), content_type))
    return references


@csrf_exempt
@login_required
@require_POST
@capture_errors
def generate_reference_prompt_api(request):
    organization = None
    charged = False
    try:
        references = _read_reference_images(request)
        platform = str(request.POST.get("platform") or "instagram").strip()
        user_context = str(request.POST.get("context") or "").strip()
        signature = hashlib.sha256()
        signature.update(b"creative-prompt-v2-keywords")
        signature.update(platform.encode("utf-8"))
        signature.update(user_context.encode("utf-8"))
        for filename, content, content_type in references:
            signature.update(filename.encode("utf-8", errors="ignore"))
            signature.update(content_type.encode("utf-8", errors="ignore"))
            signature.update(content)
        prompt_cache_key = signature.hexdigest()
        demo_cache_disabled = request.user.username == "demo"
        cached_prompt = None if demo_cache_disabled else CacheService.get(
            "creative_reference_prompt",
            request.user.id,
            prompt_cache_key,
        )
        if cached_prompt:
            cached_payload = (
                cached_prompt
                if isinstance(cached_prompt, dict)
                else {"prompt": str(cached_prompt), "keywords": []}
            )
            return JsonResponse({
                "success": True,
                "prompt": cached_payload.get("prompt", ""),
                "keywords": cached_payload.get("keywords", []),
                "analysis_summary": cached_payload.get("analysis_summary", ""),
                "creative_directions": cached_payload.get("creative_directions", []),
                "cached": True,
            })

        agency_scope = get_agency_scope(request)
        organization = agency_scope.selected_client.organization if agency_scope.selected_client else None
        credit_result = consume_openai_operation(
            user=request.user,
            organization=organization,
            operation=FeatureUsageLedger.OP_OPENAI_RECOMMENDATION,
            tariff_key="creative-studio-prompt",
            reference="core.views.creative_studio.generate_reference_prompt_api",
            reason="Creative Studio görsel analizi ve profesyonel prompt üretimi",
        )
        if not credit_result.allowed:
            return JsonResponse(insufficient_credit_payload(
                message=credit_result.reason,
                required_credits=credit_result.used,
                available_credits=credit_result.limit,
            ), status=402)
        charged = True
        agent = CreativeStudioAgent(user=request.user, organization=organization)
        prompt_payload = agent.generate_professional_prompt_from_references(
            references,
            user_context=user_context,
            platform=platform,
        )
        if not demo_cache_disabled:
            CacheService.set(
                "creative_reference_prompt",
                request.user.id,
                prompt_cache_key,
                value=prompt_payload,
                timeout=60 * 60,
            )
        return JsonResponse({
            "success": True,
            "prompt": prompt_payload["prompt"],
            "keywords": prompt_payload.get("keywords", []),
            "analysis_summary": prompt_payload.get("analysis_summary", ""),
            "creative_directions": prompt_payload.get("creative_directions", []),
            "cached": False,
        })
    except ValueError as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("Creative Studio referans görsel prompt üretim hatası")
        if charged:
            refund_ai_tariff_credits(
                user=request.user,
                organization=organization,
                tariff_key="creative-studio-prompt",
                reason=str(exc),
                reference="core.views.creative_studio.generate_reference_prompt_api",
            )
        return JsonResponse({
            "success": False,
            "message": "Görsel analizi şu anda tamamlanamadı. Lütfen tekrar deneyin.",
        }, status=500)


@csrf_exempt
@login_required
@require_POST
@capture_errors
def generate_content_api(request):
    charged_tariff_key = ""
    try:
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            data = request.POST
        else:
            data = json.loads(request.body or "{}")
        reference_files = request.FILES.getlist("reference_media")
        if len(reference_files) > 10:
            return JsonResponse({"success": False, "message": "En fazla 10 ürün görseli ekleyebilirsiniz."}, status=400)
        reference = []
        total_reference_size = 0
        for reference_file in reference_files:
            content_type = getattr(reference_file, "content_type", "") or ""
            if not content_type.startswith("image/"):
                return JsonResponse({"success": False, "message": "Ürün referansı olarak yalnızca görsel dosyaları yükleyebilirsiniz."}, status=400)
            total_reference_size += reference_file.size
            if reference_file.size > 15 * 1024 * 1024 or total_reference_size > 50 * 1024 * 1024:
                return JsonResponse({"success": False, "message": "Her görsel en fazla 15 MB, toplam dosya boyutu en fazla 50 MB olabilir."}, status=400)
            reference.append((reference_file.name, reference_file.read(), content_type))
        if not reference:
            return JsonResponse({
                "success": False,
                "message": "İçerik üretmeden önce ürün görseli yükleyip AI ile profesyonel prompt oluşturun.",
            }, status=400)
        keywords = json.loads(data.get("keywords", "[]")) if isinstance(data.get("keywords", []), str) else data.get("keywords", [])
        source_type = data.get("source_type", "scratch")
        tone = _tone(data.get("tone"))
        target_audience = str(data.get("target_audience") or "").strip() or (
            "Ürün/hizmet açıklaması ve referans görsellerinden en uygun hedef kitleyi otomatik belirle; "
            "yaş, ihtiyaç, motivasyon ve satın alma niyetini çıkar. Anlatım tonunu da bu kitleye ve kampanya amacına göre seç."
        )
        product_prompt = str(data.get("product_description") or "").strip()
        if not product_prompt:
            return JsonResponse({
                "success": False,
                "message": "Önce yüklediğiniz görsellerden AI profesyonel promptunu oluşturun.",
            }, status=400)
        product_prompt = (
            product_prompt
            + "\n\nÜretim talimatı: Bu prompt ve ürün görsellerine göre en uygun hedef kitleyi ve iletişim tonunu otomatik seç. "
              "Ton seçiminde sabit bir şablona bağlı kalma; ürün, teklif, platform ve satın alma motivasyonuna göre karar ver."
        ).strip()
        carousel_mode = len(reference) > 1
        requested_variants = int(data.get("num_variants", 4) or 4)
        num_variants = 1 if carousel_mode else (
            requested_variants if requested_variants in {3, 4, 6} else 4
        )
        generate_visuals = True

        charged_tariff_key = "creative-studio-image" if generate_visuals else "creative-studio-content"
        agency_scope = get_agency_scope(request)
        organization = agency_scope.selected_client.organization if agency_scope.selected_client else None
        credit_result = consume_openai_operation(
            user=request.user,
            organization=organization,
            operation=FeatureUsageLedger.OP_OPENAI_RECOMMENDATION,
            tariff_key=charged_tariff_key,
            reference="core.views.creative_studio.generate_content_api",
            reason="Creative Studio görselli içerik üretimi" if generate_visuals else "Creative Studio metin üretimi",
        )
        if not credit_result.allowed:
            return JsonResponse(insufficient_credit_payload(
                message=credit_result.reason,
                required_credits=credit_result.used,
                available_credits=credit_result.limit,
            ), status=402)

        source_ad = None
        if source_type in ["competitor", "competitor_ad"]:
            competitor_ad_id = data.get("competitor_ad_id") or data.get("source_ad_id")
            if not competitor_ad_id:
                return JsonResponse({"success": False, "message": "Rakip reklam ID'si gerekli."}, status=400)
            source_ad = get_object_or_404(Ad, id=competitor_ad_id, user=request.user, source_type="COMPETITOR")
            source_type = "competitor_ad"
        elif source_type in ["my_ad", "own_ad"]:
            source_ad_id = data.get("source_ad_id")
            if source_ad_id:
                source_ad = get_object_or_404(Ad, id=source_ad_id, user=request.user, source_type="OWN")
            source_type = "my_ad"

        project = CreativeProject.objects.create(
            user=request.user,
            name=data.get("project_name") or f"Proje - {timezone.now().strftime('%d.%m.%Y %H:%M')}",
            status="generating",
            source_type=source_type,
            source_ad=source_ad,
            tone=tone.value,
            target_audience=target_audience,
            product_description=product_prompt,
            keywords=keywords,
        )

        agent = CreativeStudioAgent(user=request.user, organization=organization)
        if source_ad:
            variants = agent.generate_from_competitor_ad(
                competitor_ad=source_ad,
                num_variants=num_variants,
                tone=tone,
                target_audience=target_audience,
                product_description=product_prompt,
                keywords=keywords,
            )
        else:
            variants = agent.generate_from_scratch(
                num_variants=num_variants,
                tone=tone,
                target_audience=target_audience,
                product_description=product_prompt,
                keywords=keywords,
            )
        try:
            variants = agent.review_variants(
                variants[:num_variants],
                product_prompt=product_prompt,
                carousel_mode=carousel_mode,
            )
        except Exception:
            logger.exception("Creative Studio final Sol kalite kontrolü tamamlanamadı; Terra çıktısı korunuyor")
            variants = variants[:num_variants]

        saved_variants = []
        reference_path = ""
        reference_paths = []
        if reference:
            for filename, content, content_type in reference:
                saved_reference_path = default_storage.save(
                    f"creative_studio/{request.user.id}/{project.id}/reference/{filename}",
                    ContentFile(content),
                )
                reference_paths.append({"path": saved_reference_path, "type": content_type})
        for variant in variants[:num_variants]:
            variant_data = {
                "variant_number": variant.variant_number,
                "headline": variant.headline,
                "primary_text": variant.primary_text,
                "description": variant.description,
                "cta": variant.cta,
                "hashtags": variant.hashtags,
                "visual_brief": variant.visual_brief,
                "visual_prompt": variant.visual_prompt,
                "video_brief": "",
                "video_prompt": "",
                "shot_list": [],
                "landing_page_hook": variant.landing_page_hook,
                "ai_score": variant.ai_score,
                "predicted_engagement": variant.predicted_engagement,
                "predicted_ctr": variant.predicted_ctr,
                "competitive_advantage": variant.competitive_advantage,
                "target_emotion": variant.target_emotion,
                "quality_review_score": (agent.last_quality_review or {}).get("score", 0),
                "quality_review_summary": (agent.last_quality_review or {}).get("summary", ""),
                "quality_review_model": (agent.last_quality_review or {}).get("model", ""),
                "post_type": "CAROUSEL" if carousel_mode else "IMAGE",
                "image_url": "",
                "carousel_images": [],
                "image_generation_error": "",
                "image_generation_status": "not_requested" if not generate_visuals else "pending",
                "video_url": "",
                "video_generation_error": "",
                "video_generation_status": "not_requested",
                "reference_media_paths": reference_paths,
            }
            if generate_visuals and variant.visual_prompt:
                try:
                    if carousel_mode:
                        carousel_images = []
                        carousel_errors = []
                        for slide_number, reference_item in enumerate(reference, start=1):
                            slide_prompt = (
                                f"{variant.visual_prompt}\n\n"
                                f"Carousel slide {slide_number} of {len(reference)}. Edit and enhance this specific uploaded image as a coherent "
                                "premium carousel slide. Preserve the exact product, its visible angle, identity, proportions, colors, packaging, "
                                "logo and physical details from this slide. Keep a consistent campaign art direction across all slides while giving "
                                "this slide a distinct composition. Do not add text, a different product, automatic animation, or video elements."
                            )
                            try:
                                image_bytes = agent.generate_visual(
                                    slide_prompt,
                                    reference=[reference_item],
                                )
                                image_path = default_storage.save(
                                    (
                                        f"creative_studio/{request.user.id}/{project.id}/"
                                        f"carousel-slide-{slide_number}.png"
                                    ),
                                    ContentFile(image_bytes),
                                )
                                carousel_images.append(default_storage.url(image_path))
                            except Exception as slide_exc:
                                logger.exception(
                                    "Creative Studio carousel slayt üretim hatası: %s",
                                    slide_number,
                                )
                                carousel_errors.append(str(slide_exc))
                        if len(carousel_images) < 2:
                            raise RuntimeError("Carousel için en az iki görsel üretilemedi.")
                        variant_data["carousel_images"] = carousel_images
                        variant_data["image_url"] = carousel_images[0]
                        variant_data["image_generation_status"] = "completed"
                        if carousel_errors:
                            variant_data["image_generation_error"] = (
                                f"{len(carousel_errors)} slayt tamamlanamadı; "
                                f"{len(carousel_images)} slayt kullanıma hazır."
                            )
                    else:
                        image_bytes = agent.generate_visual(
                            variant.visual_prompt,
                            reference=reference or None,
                        )
                        image_path = default_storage.save(
                            f"creative_studio/{request.user.id}/{project.id}/variant-{variant.variant_number}.png",
                            ContentFile(image_bytes),
                        )
                        variant_data["image_url"] = default_storage.url(image_path)
                        variant_data["image_generation_status"] = "completed"
                except Exception as image_exc:
                    logger.exception("Creative Studio AI görsel üretim hatası")
                    variant_data["image_generation_error"] = "AI görseli şu anda tamamlanamadı; daha sonra yeniden denenebilir."
                    variant_data["image_generation_status"] = "retryable"
            content_items = [
                ("headline", variant.headline),
                ("caption", variant.primary_text),
                ("description", variant.description),
                ("hashtag", json.dumps(variant.hashtags, ensure_ascii=False)),
                ("full_ad", json.dumps(variant_data, ensure_ascii=False)),
            ]
            for content_type, content in content_items:
                GeneratedContent.objects.create(
                    project=project,
                    content_type=content_type,
                    content=content,
                    score=variant.ai_score,
                )
            saved_variants.append(variant_data)

        project.generated_variants = saved_variants
        project.ai_model = agent.model
        project.status = "completed"
        project.save(update_fields=["generated_variants", "ai_model", "status", "updated_at"])
        media_partial = any(
            row.get("image_generation_status") == "retryable"
            for row in saved_variants
        )
        return JsonResponse({
            "success": True,
            "project_id": project.id,
            "variants": saved_variants,
            "ecosystem": agent.last_ecosystem,
            "ecosystem_cached": bool(getattr(agent, "last_ecosystem_cache_hit", False)),
            "agent_count": len((agent.last_ecosystem or {}).get("agents") or []),
            "generation_mode": "16-agent-orchestration",
            "partial_success": media_partial,
            "media_notice": "Metin ve strateji hazır. Bazı medya dosyaları daha sonra yeniden üretilebilir." if media_partial else "",
        })
    except Exception as exc:
        logger.exception("Creative Studio üretim hatası")
        project = locals().get("project")
        if project is not None and project.status == "generating":
            project.status = "draft"
            project.save(update_fields=["status", "updated_at"])
        if charged_tariff_key:
            refund_ai_tariff_credits(
                user=request.user, organization=locals().get("organization"), tariff_key=charged_tariff_key, reason=str(exc),
                reference="core.views.creative_studio.generate_content_api",
            )
        return JsonResponse({
            "success": False,
            "message": "AI üretimi şu anda tamamlanamadı. Çalışmanız korunuyor; lütfen kısa süre sonra yeniden deneyin.",
        })


@csrf_exempt
@login_required
@require_POST
@capture_errors
def regenerate_variant_media_api(request, project_id, variant_number):
    project = get_object_or_404(CreativeProject, id=project_id, user=request.user)
    variants = list(project.generated_variants or [])
    variant = next((row for row in variants if int(row.get("variant_number", 0)) == int(variant_number)), None)
    if not variant:
        return JsonResponse({"success": False, "message": "Varyant bulunamadı."})
    charged_tariff_key = ""
    try:
        data = json.loads(request.body or "{}")
        image_requested = bool(data.get("image", True) and not variant.get("image_url") and variant.get("visual_prompt"))
        video_requested = False
        if not image_requested:
            return JsonResponse({"success": False, "message": "Yeniden üretilecek medya bulunamadı."}, status=400)
        charged_tariff_key = "creative-studio-regenerate"
        agency_scope = get_agency_scope(request)
        organization = agency_scope.selected_client.organization if agency_scope.selected_client else None
        credit_result = consume_openai_operation(
            user=request.user,
            organization=organization,
            operation=FeatureUsageLedger.OP_OPENAI_RECOMMENDATION,
            tariff_key=charged_tariff_key,
            reference="core.views.creative_studio.regenerate_variant_media_api",
            reason="Creative Studio video üretimi" if video_requested else "Creative Studio görsel yeniden üretimi",
        )
        if not credit_result.allowed:
            return JsonResponse(insufficient_credit_payload(
                message=credit_result.reason,
                required_credits=credit_result.used,
                available_credits=credit_result.limit,
            ), status=402)
        agent = CreativeStudioAgent(model=project.ai_model, user=request.user, organization=organization)
        reference = []
        reference_rows = variant.get("reference_media_paths") or []
        if not reference_rows and variant.get("reference_media_path"):
            reference_rows = [{"path": variant.get("reference_media_path"), "type": variant.get("reference_media_type")}]
        for reference_row in reference_rows[:10]:
            reference_path = reference_row.get("path")
            if reference_path and default_storage.exists(reference_path):
                with default_storage.open(reference_path, "rb") as reference_stream:
                    reference.append((
                        reference_path.rsplit("/", 1)[-1],
                        reference_stream.read(),
                        reference_row.get("type") or "application/octet-stream",
                    ))
        if data.get("image", True) and not variant.get("image_url") and variant.get("visual_prompt"):
            image_path = default_storage.save(
                f"creative_studio/{request.user.id}/{project.id}/variant-{variant_number}-retry.png",
                ContentFile(agent.generate_visual(variant["visual_prompt"], reference=reference or None)),
            )
            variant["image_url"] = default_storage.url(image_path)
            variant["image_generation_status"] = "completed"
            variant["image_generation_error"] = ""
        project.generated_variants = variants
        project.save(update_fields=["generated_variants", "updated_at"])
        return JsonResponse({"success": True, "variant": variant})
    except Exception as exc:
        logger.exception("Creative Studio medya yeniden üretim hatası")
        if charged_tariff_key:
            refund_ai_tariff_credits(
                user=request.user, organization=locals().get("organization"), tariff_key=charged_tariff_key, reason=str(exc),
                reference="core.views.creative_studio.regenerate_variant_media_api",
            )
        error_text = str(exc)
        if "Connection error" in error_text or "ConnectError" in exc.__class__.__name__:
            message = "Video servisine bağlantı kurulamadı. İnternet, güvenlik duvarı veya OpenAI erişimi kontrol edilmelidir."
        else:
            message = "Video servisi üretimi tamamlayamadı. Model erişimi, referans biçimi veya kullanım limiti kontrol edilmelidir."
        message = "Görsel üretimi tamamlanamadı. Referans biçimi veya kullanım limiti kontrol edilmelidir."
        variant["image_generation_status"] = "retryable"
        variant["image_generation_error"] = message
        project.generated_variants = variants
        project.save(update_fields=["generated_variants", "updated_at"])
        return JsonResponse({"success": False, "message": message})
@csrf_exempt
@login_required
@require_POST
@capture_errors
def publish_to_instagram_queue(request):
    try:
        if request.content_type and request.content_type.startswith("multipart/form-data"):
            data = request.POST
        else:
            data = json.loads(request.body or "{}")
        project = get_object_or_404(CreativeProject, id=data.get("project_id"), user=request.user)
        platform_account_id = data.get("platform_account_id") or data.get("instagram_account_id")
        platform_account = get_object_or_404(
            platform_accounts_for_request(request, active_only=True).select_related("connection", "platform"),
            id=platform_account_id,
            platform__code__in=ORGANIC_PUBLISH_PLATFORM_CODES,
        )
        variant_number = int(data.get("variant_number", 1))
        variant = next((v for v in project.generated_variants if v.get("variant_number") == variant_number), None)
        if not variant:
            return JsonResponse({"success": False, "message": "Varyant bulunamadı"}, status=400)
        carousel_images = [
            str(url).strip()
            for url in (variant.get("carousel_images") or [])
            if str(url).strip()
        ][:10]
        post_type = "CAROUSEL" if len(carousel_images) >= 2 else "IMAGE"
        publish_platform = get_organic_publish_platform(platform_account.platform.code)
        if not publish_platform or post_type not in publish_platform["post_types"]:
            return JsonResponse({"success": False, "message": f"{platform_account.platform.name} bu içerik tipinin canlı yayınını desteklemiyor."}, status=400)
        media_file = request.FILES.get("media_file")
        image_url = ""
        media_file_name = ""
        if post_type == "CAROUSEL":
            carousel_images = [_public_media_url(url) for url in carousel_images]
            image_url = carousel_images[0]
            media_file_name = f"ai-carousel-{variant_number}.png"
        elif post_type == "IMAGE" and media_file:
            if not getattr(media_file, "content_type", "").startswith("image/"):
                return JsonResponse({"success": False, "message": "Canlı yayın için JPG, PNG veya WEBP görseli yüklemelisiniz."}, status=400)
            media_file_name = media_file.name
            saved_path = default_storage.save(
                f"organic_content/{request.user.id}/{timezone.now():%Y/%m/%d}/{media_file.name}",
                media_file,
            )
            image_url = _public_media_url(default_storage.url(saved_path))
        elif post_type == "IMAGE" and variant.get("image_url"):
            image_url = _public_media_url(variant["image_url"])
            media_file_name = f"ai-variant-{variant_number}.png"
        elif post_type == "IMAGE":
            return JsonResponse({"success": False, "message": "AI görseli üretilemedi; yayın için görsel dosya yüklemelisiniz."}, status=400)
        hashtags = variant.get("hashtags", [])
        hashtag_text = " ".join(
            str(tag) if str(tag).startswith("#") else f"#{tag}"
            for tag in hashtags
            if str(tag).strip()
        )
        caption = f"{variant.get('headline','')}\n\n{variant.get('primary_text','')}\n\n{variant.get('description','')}\n\nCTA: {variant.get('cta','')}\n\n{hashtag_text}"
        scheduled_at = data.get("scheduled_at") or ""
        scheduled_dt = None
        if scheduled_at:
            scheduled_dt = parse_datetime(scheduled_at)
            if scheduled_dt is None:
                return JsonResponse({"success": False, "message": "Planlanan tarih veya saat geçersiz."}, status=400)
            if timezone.is_naive(scheduled_dt):
                scheduled_dt = timezone.make_aware(scheduled_dt, timezone.get_current_timezone())
            if scheduled_dt <= timezone.now():
                return JsonResponse({"success": False, "message": "Planlanan zaman gelecekte olmalıdır."}, status=400)
        raw_data = {
            "status": "scheduled" if scheduled_at else "draft",
            "source": "creative_studio",
            "project_id": project.id,
            "variant_number": variant_number,
            "visual_brief": variant.get("visual_brief", ""),
            "visual_prompt": variant.get("visual_prompt", ""),
            "media_file_name": media_file_name,
            "carousel_images": carousel_images if post_type == "CAROUSEL" else [],
        }
        if scheduled_dt:
            raw_data["scheduled_at"] = scheduled_dt.isoformat()
        post = SocialPost.objects.create(
            user=request.user,
            platform_connection=platform_account.connection,
            platform_account=platform_account,
            platform_post_id=f"creative-draft-{project.id}-{variant_number}-{int(timezone.now().timestamp())}",
            post_type=post_type,
            caption=caption,
            image_url=image_url or None,
            thumbnail_url=image_url or None,
            raw_data=raw_data,
            is_active=True,
        )
        project.selected_variant = variant_number
        project.published_to_queue = bool(scheduled_dt)
        project.status = "approved"
        project.save(update_fields=["selected_variant", "published_to_queue", "status", "updated_at"])
        if scheduled_dt:
            from core.tasks.organic_publish import publish_scheduled_social_post
            publish_scheduled_social_post.apply_async(args=[post.id], eta=scheduled_dt)
            return JsonResponse({"success": True, "post_id": post.id, "message": "Gönderi planlandı.", "redirect_url": "/organic-content/"})

        result = publish_post(post)
        if not result.success:
            return JsonResponse({"success": False, "message": result.message, "post_id": post.id}, status=400)
        project.published_to_queue = True
        project.save(update_fields=["published_to_queue", "updated_at"])
        return JsonResponse({"success": True, "post_id": post.id, "message": result.message, "redirect_url": "/organic-content/"})
    except Exception as exc:
        return JsonResponse({"success": False, "message": str(exc)}, status=500)


@login_required
@capture_errors
def get_saved_templates_api(request):
    templates = CreativeTemplate.objects.filter(Q(user=request.user) | Q(is_public=True)).values("id", "name", "template_type", "tone", "usage_count", "rating")
    return JsonResponse({"success": True, "templates": list(templates)})


@login_required
@capture_errors
def get_project_detail_api(request, project_id):
    project = get_object_or_404(CreativeProject, id=project_id, user=request.user)
    contents = GeneratedContent.objects.filter(project=project).order_by("content_type", "-score")
    contents_data = [{"content_type": item.content_type, "content": item.content, "score": item.score} for item in contents]
    return JsonResponse({"success": True, "project": {"id": project.id, "name": project.name, "status": project.status, "variants": project.generated_variants, "contents": contents_data, "selected_variant": project.selected_variant}})


@login_required
@require_POST
@capture_errors
def update_variant_text_api(request, project_id, variant_number):
    project = get_object_or_404(CreativeProject, id=project_id, user=request.user)
    data = json.loads(request.body or "{}")
    variants = list(project.generated_variants or [])
    variant = next((row for row in variants if int(row.get("variant_number", 0)) == int(variant_number)), None)
    if not variant:
        return JsonResponse({"success": False, "message": "Reklam seçeneği bulunamadı."}, status=404)
    limits = {"headline": 300, "primary_text": 5000, "description": 2000, "cta": 100}
    for field, limit in limits.items():
        if field in data:
            variant[field] = str(data.get(field) or "").strip()[:limit]
    if "hashtags" in data:
        hashtags = data.get("hashtags") or []
        if isinstance(hashtags, str):
            hashtags = [item.strip().lstrip("#") for item in hashtags.split(",") if item.strip()]
        variant["hashtags"] = [str(item).strip().lstrip("#")[:80] for item in hashtags[:30] if str(item).strip()]
    project.generated_variants = variants
    project.save(update_fields=["generated_variants", "updated_at"])
    return JsonResponse({"success": True, "variant": variant, "message": "Değişiklikler kaydedildi."})


@login_required
@capture_errors
def get_competitors_api(request, platform_code=None):
    """Rakip listesi artık Ad(source_type=COMPETITOR) üzerinden gruplanır."""
    ads = Ad.objects.filter(user=request.user, source_type="COMPETITOR", is_active=True).select_related(
        "competitor", "competitor__platform", "platform_account", "platform_account__platform", "creative"
    )
    if platform_code:
        ads = ads.filter(platform_account__platform__code=platform_code)
    grouped = {}
    for ad in ads:
        if ad.competitor_id:
            key = f"competitor-{ad.competitor_id}"
            competitor_name = ad.competitor.name
            identifier = ad.competitor.platform_identifier or ""
        else:
            key = f"account-{ad.platform_account_id}" if ad.platform_account_id else f"ad-{ad.id}"
            competitor_name = ad.platform_account.account_name if ad.platform_account else (ad.name or "Rakip")
            identifier = ad.platform_account.account_name if ad.platform_account else ""
        item = grouped.setdefault(key, {
            "id": key,
            "name": competitor_name,
            "instagram_username": identifier,
            "full_name": competitor_name,
            "profile_picture": "https://ui-avatars.com/api/?name=Rakip&background=6366f1&color=fff&size=48",
            "is_verified": False,
            "ad_count": 0,
        })
        item["ad_count"] += 1
    return JsonResponse({"success": True, "competitors": list(grouped.values()), "count": len(grouped)})


@login_required
@capture_errors
def get_competitor_ads_api(request, competitor_id):
    ads = Ad.objects.filter(user=request.user, source_type="COMPETITOR", is_active=True).select_related("creative", "platform_account")
    competitor_key = str(competitor_id)
    if competitor_key.startswith("competitor-") and competitor_key.removeprefix("competitor-").isdigit():
        ads = ads.filter(competitor_id=int(competitor_key.removeprefix("competitor-")))
    elif competitor_key.startswith("account-") and competitor_key.removeprefix("account-").isdigit():
        ads = ads.filter(platform_account_id=int(competitor_key.removeprefix("account-")))
    elif competitor_key.startswith("ad-") and competitor_key.removeprefix("ad-").isdigit():
        ads = ads.filter(id=int(competitor_key.removeprefix("ad-")))
    elif competitor_key.isdigit():
        ads = ads.filter(Q(platform_account_id=competitor_id) | Q(id=competitor_id))
    else:
        ads = ads.none()
    ads_data = []
    for ad in ads.order_by("-created_at")[:100]:
        last_metric = ad.metric_history.order_by("-date").first()
        ads_data.append({
            "id": ad.id,
            "db_id": ad.id,
            "instagram_ad_id": ad.platform_ad_id or ad.ad_library_id or "",
            "name": ad.name or ad.headline or f"Reklam #{ad.id}",
            "title": ad.headline or ad.name or "",
            "description": ad.description or ad.primary_text or "",
            "media_type": ad.ad_format or (ad.creative.creative_type if ad.creative else "UNKNOWN"),
            "media_url": ad.preview_video_url or ad.preview_image_url or "",
            "thumbnail_url": ad.preview_image_url or "",
            "status": ad.status,
            "impressions": last_metric.impressions if last_metric else 0,
            "clicks": last_metric.clicks if last_metric else 0,
            "ctr": float(last_metric.ctr) if last_metric else 0,
            "reach": last_metric.reach if last_metric else 0,
            "frequency": float(last_metric.frequency) if last_metric else 0,
            "spend": float(last_metric.spend) if last_metric else 0,
            "engagement": last_metric.engagement if last_metric else 0,
            "conversions": float(last_metric.conversions) if last_metric else 0,
            "created_at": ad.created_at.strftime("%d.%m.%Y %H:%M") if ad.created_at else "",
        })
    return JsonResponse({"success": True, "ads": ads_data, "count": len(ads_data)})
