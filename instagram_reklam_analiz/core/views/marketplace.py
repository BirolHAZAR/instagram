from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Count, Q, Sum
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import timedelta

from core.decorators import subscription_required
from core.forms import MarketplaceAccountForm, MarketplaceProductResearchForm
from core.models import (
    Marketplace,
    MarketplaceAccount,
    FeatureUsageLedger,
    MarketplaceListing,
    MarketplaceProductResearch,
    MarketplaceProductResearchMetricHistory,
    MarketplaceSyncRun,
    Organization,
    Product,
)
from core.models.marketplace import SUPPORTED_MARKETPLACE_CODES
from core.services.entitlements import get_active_subscription
from core.services.marketplace_sync import enqueue_marketplace_sync
from core.services.marketplace_connection import MarketplaceConnectionError, verify_marketplace_credentials
from core.services.notification_events import notify_user
from core.services.marketplace_research import apply_research_result, build_marketplace_research_result, mark_research_failed
from core.services.usage_metering import consume_usage, record_usage_failure
from core.services.web_market_research import MarketResearchProviderError
from core.tasks.marketplace_sync import sync_marketplace_account


def _user_marketplace_scope(user):
    return (
        Q(user=user)
        | Q(organization__owner=user)
        | Q(organization__members__user=user, organization__members__is_active=True)
    )


def _supported_marketplace_filter():
    return Q(marketplace__code__in=SUPPORTED_MARKETPLACE_CODES)


def _active_organization_for_user(user):
    owned = Organization.objects.filter(owner=user, is_active=True).order_by("name").first()
    if owned:
        return owned
    membership = (
        user.organization_memberships.select_related("organization")
        .filter(is_active=True, organization__is_active=True)
        .order_by("organization__name")
        .first()
    )
    return membership.organization if membership else None


def _research_image_url(research):
    if research.product_image:
        try:
            return research.product_image.url
        except ValueError:
            return ""
    if research.product_id and research.product.image_url:
        return research.product.image_url
    for item in research.result_items or []:
        if item.get("image_url"):
            return item["image_url"]
    return ""


def _tracking_interval_from_request(request):
    try:
        value = int(request.POST.get("tracking_interval_hours") or 24)
    except (TypeError, ValueError):
        value = 24
    return min(max(value, 6), 168)


@login_required
@subscription_required
def marketplace_product_management(request):
    marketplace_id = request.GET.get("marketplace")
    status = request.GET.get("status", "")
    query = (request.GET.get("q") or "").strip()

    account_scope = _user_marketplace_scope(request.user)
    product_scope = _user_marketplace_scope(request.user)

    marketplaces = Marketplace.objects.filter(
        code__in=SUPPORTED_MARKETPLACE_CODES,
        is_active=True,
    ).order_by("order", "name")
    accounts = (
        MarketplaceAccount.objects.select_related("marketplace", "organization", "subscription", "agency_client")
        .filter(account_scope)
        .filter(_supported_marketplace_filter())
        .distinct()
        .order_by("marketplace__order", "store_name")
    )

    if request.method == "POST":
        account_id = request.POST.get("marketplace_account")
        account = accounts.filter(id=account_id, is_active=True).first()
        if not account:
            messages.error(request, "Senkronizasyon için aktif bir pazaryeri hesabı seçmelisiniz.")
            return redirect("marketplace_product_management")
        sync_run, created = enqueue_marketplace_sync(account, requested_by=request.user)
        if not created:
            messages.info(request, f"{account.store_name} için zaten bekleyen/çalışan bir senkronizasyon var.")
            return redirect("marketplace_product_management")
        try:
            sync_marketplace_account.delay(sync_run.id)
            messages.success(request, f"{account.store_name} ürün senkronizasyonu kuyruğa alındı.")
        except Exception as exc:
            sync_run.status = MarketplaceSyncRun.STATUS_FAILED
            sync_run.error_message = str(exc)
            sync_run.save(update_fields=["status", "error_message"])
            messages.error(request, "Senkronizasyon kuyruğa alınamadı. Celery/Redis çalışıyor mu kontrol edin.")
        return redirect("marketplace_product_management")

    products = Product.objects.filter(product_scope).distinct()
    listings = (
        MarketplaceListing.objects.select_related(
            "marketplace",
            "marketplace_account",
            "product",
            "variant",
        )
        .filter(product__in=products)
        .order_by("-last_synced_at", "-updated_at", "product__name", "marketplace__order")
    )

    if marketplace_id:
        listings = listings.filter(marketplace_id=marketplace_id)
    if status:
        listings = listings.filter(status=status)
    if query:
        listings = listings.filter(
            Q(product__name__icontains=query)
            | Q(product__sku__icontains=query)
            | Q(product__barcode__icontains=query)
            | Q(variant__sku__icontains=query)
            | Q(variant__barcode__icontains=query)
            | Q(platform_sku__icontains=query)
            | Q(platform_barcode__icontains=query)
            | Q(platform_category_name__icontains=query)
        )

    paginator = Paginator(listings, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    listing_rows = page_obj.object_list
    summary = {
        "marketplace_count": marketplaces.count(),
        "account_count": accounts.count(),
        "product_count": products.count(),
        "listing_count": listings.count(),
        "total_stock": listings.aggregate(total=Sum("stock"))["total"] or 0,
        "total_views": listings.aggregate(total=Sum("view_count"))["total"] or 0,
        "total_favorites": listings.aggregate(total=Sum("favorite_count"))["total"] or 0,
        "avg_rating": listings.aggregate(avg=Avg("rating_average"))["avg"] or 0,
    }
    marketplace_breakdown = (
        listings.values("marketplace__name", "marketplace__code")
        .annotate(
            listing_count=Count("id"),
            total_stock=Sum("stock"),
            total_views=Sum("view_count"),
            avg_rating=Avg("rating_average"),
        )
        .order_by("marketplace__name")
    )
    recent_sync_runs = (
        MarketplaceSyncRun.objects.select_related("marketplace_account", "marketplace_account__marketplace")
        .filter(marketplace_account__in=accounts)
        .order_by("-created_at")[:8]
    )

    return render(
        request,
        "marketplace/product_management.html",
        {
            "marketplaces": marketplaces,
            "accounts": accounts,
            "listings": listing_rows,
            "page_obj": page_obj,
            "paginator": paginator,
            "summary": summary,
            "marketplace_breakdown": marketplace_breakdown,
            "selected_marketplace": marketplace_id or "",
            "selected_status": status,
            "query": query,
            "status_choices": MarketplaceListing.STATUS_CHOICES,
            "recent_sync_runs": recent_sync_runs,
        },
    )


@login_required
@subscription_required
def marketplace_accounts(request):
    organization = _active_organization_for_user(request.user)
    subscription = get_active_subscription(request.user, organization=organization)

    accounts = (
        MarketplaceAccount.objects.select_related("marketplace", "organization", "subscription", "agency_client")
        .filter(_user_marketplace_scope(request.user))
        .filter(_supported_marketplace_filter())
        .distinct()
        .order_by("marketplace__order", "store_name")
    )

    if request.method == "POST":
        form = MarketplaceAccountForm(request.POST, organization=organization)
        if form.is_valid():
            account = form.save(commit=False)
            account.user = request.user
            account.organization = organization
            account.subscription = subscription
            try:
                verification = verify_marketplace_credentials(account)
            except MarketplaceConnectionError as exc:
                form.add_error(None, str(exc))
            else:
                account.extra_credentials = {
                    **(account.extra_credentials or {}), **verification,
                    "connection_verified_at": timezone.now().isoformat(), "connection_error": "",
                }
                account.save()
                notify_user(
                    user=request.user, title="Pazaryeri mağazası bağlandı",
                    message=f"{account.marketplace.name} - {account.store_name} canlı API bağlantısı doğrulandı.",
                    level="success", icon="fa-store", link="/pazaryeri/hesaplar/",
                    dedupe_key=f"marketplace_account_created_{account.id}",
                )
                messages.success(request, f"{account.marketplace.name} canlı API bağlantısı doğrulandı: {account.store_name}")
                return redirect("marketplace_accounts")
    else:
        form = MarketplaceAccountForm(organization=organization, initial={"is_active": True})

    return render(
        request,
        "marketplace/accounts.html",
        {
            "accounts": accounts,
            "form": form,
            "organization": organization,
        },
    )


def _marketplace_account_for_user(request, account_id):
    queryset = (
        MarketplaceAccount.objects.select_related("marketplace")
        .filter(_user_marketplace_scope(request.user))
        .filter(_supported_marketplace_filter())
        .distinct()
    )
    return get_object_or_404(queryset, pk=account_id)


@login_required
@subscription_required
def marketplace_account_edit(request, account_id):
    account = _marketplace_account_for_user(request, account_id)
    organization = account.organization or _active_organization_for_user(request.user)
    if request.method == "POST":
        form = MarketplaceAccountForm(request.POST, instance=account, organization=organization)
        if form.is_valid():
            updated = form.save(commit=False)
            try:
                verification = verify_marketplace_credentials(updated)
            except MarketplaceConnectionError as exc:
                form.add_error(None, str(exc))
            else:
                updated.extra_credentials = {
                    **(updated.extra_credentials or {}), **verification,
                    "connection_verified_at": timezone.now().isoformat(), "connection_error": "",
                }
                updated.save()
                notify_user(
                    user=request.user, title="Pazaryeri mağazası güncellendi",
                    message=f"{updated.marketplace.name} - {updated.store_name} ayarları ve canlı bağlantısı doğrulandı.",
                    level="success", icon="fa-store", link="/pazaryeri/hesaplar/",
                    dedupe_key=f"marketplace_account_updated_{updated.id}",
                )
                messages.success(request, f"{updated.store_name} güncellendi ve canlı bağlantısı doğrulandı.")
                return redirect("marketplace_accounts")
    else:
        form = MarketplaceAccountForm(instance=account, organization=organization)
    accounts = (
        MarketplaceAccount.objects.select_related("marketplace", "agency_client")
        .filter(_user_marketplace_scope(request.user)).filter(_supported_marketplace_filter())
        .distinct().order_by("marketplace__order", "store_name")
    )
    return render(request, "marketplace/accounts.html", {
        "accounts": accounts, "form": form, "organization": organization, "editing_account": account,
    })


@login_required
@subscription_required
@require_POST
def marketplace_account_test(request, account_id):
    account = _marketplace_account_for_user(request, account_id)
    extra = dict(account.extra_credentials or {})
    try:
        verification = verify_marketplace_credentials(account)
    except MarketplaceConnectionError as exc:
        extra.update({"connection_status": "error", "connection_error": str(exc)[:500]})
        messages.error(request, f"{account.store_name}: {exc}")
        notify_user(
            user=request.user, title="Pazaryeri bağlantı hatası",
            message=f"{account.marketplace.name} - {account.store_name} bağlantısı doğrulanamadı.",
            level="warning", icon="fa-plug-circle-xmark", link="/pazaryeri/hesaplar/",
            dedupe_key=f"marketplace_connection_error_{account.id}",
        )
    else:
        extra.update(verification)
        extra.update({"connection_verified_at": timezone.now().isoformat(), "connection_error": ""})
        messages.success(request, f"{account.store_name} canlı API bağlantısı başarılı.")
    account.extra_credentials = extra
    account.save(update_fields=["extra_credentials", "updated_at"])
    return redirect("marketplace_accounts")


@login_required
@subscription_required
@require_POST
def marketplace_account_delete(request, account_id):
    account = _marketplace_account_for_user(request, account_id)
    store_name = account.store_name
    marketplace_name = account.marketplace.name
    account.delete()
    notify_user(
        user=request.user, title="Pazaryeri mağazası silindi",
        message=f"{marketplace_name} - {store_name} mağaza bağlantısı kaldırıldı.",
        level="warning", icon="fa-trash-can", link="/pazaryeri/hesaplar/",
        dedupe_key=f"marketplace_account_deleted_{account_id}",
    )
    messages.success(request, f"{store_name} mağaza bağlantısı ve ilişkili senkron kayıtları silindi.")
    return redirect("marketplace_accounts")


@login_required
@subscription_required
def marketplace_product_research(request):
    organization = _active_organization_for_user(request.user)
    subscription = get_active_subscription(request.user, organization=organization)
    selected_research = None

    if request.method == "POST":
        form = MarketplaceProductResearchForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            usage_result = consume_usage(
                user=request.user,
                organization=organization,
                subscription=subscription,
                operation=FeatureUsageLedger.OP_MARKETPLACE_PRODUCT_RESEARCH,
                reference="marketplace.product_research",
                note="Urun arastirma API kullanimi",
            )
            if not usage_result.allowed:
                messages.error(request, usage_result.reason)
                return redirect("marketplace_product_research")

            research = form.save(commit=False)
            research.user = request.user
            research.organization = organization
            research.subscription = subscription
            research.search_mode = MarketplaceProductResearch.MODE_IMAGE_AUTO
            research.status = MarketplaceProductResearch.STATUS_QUEUED
            research.progress_percent = 0
            research.current_step = "Araştırma kuyruğa hazırlanıyor"
            research.raw_result = {
                "usage_ledger_id": usage_result.ledger.id if usage_result.ledger else None,
            }
            if not research.title and research.product_id:
                research.title = research.product.name
            research.save()
            form.save_m2m()
            from core.tasks.marketplace_sync import run_product_research_agent
            task = run_product_research_agent.delay(research.id)
            research.celery_task_id = task.id or ""
            research.save(update_fields=["celery_task_id", "updated_at"])
            messages.success(request, "AI alışveriş ajanı araştırmayı başlattı. İlerleme bu ekranda güncellenecek.")
            return redirect(f"{request.path}?research={research.id}")
    else:
        form = MarketplaceProductResearchForm(user=request.user)

    researches = (
        MarketplaceProductResearch.objects.select_related("product")
        .filter(_user_marketplace_scope(request.user))
        .distinct()
        .order_by("-created_at")[:12]
    )
    requested_research_id = request.GET.get("research")
    selected_research = next(
        (
            research for research in researches
            if requested_research_id and str(research.id) == str(requested_research_id)
        ),
        None,
    )
    # Her zaman en yeni kaydı göster. Başarısız bir yeni araştırmayı gizlemek,
    # kullanıcıya eski ürünün yeni sonuçmuş gibi görünmesine neden olur.
    if selected_research is None:
        selected_research = next(iter(researches), None)

    return render(
        request,
        "marketplace/product_research.html",
        {
            "form": form,
            "researches": researches,
            "selected_research": selected_research,
        },
    )


@login_required
@subscription_required
def marketplace_product_research_status(request, research_id):
    research = (
        MarketplaceProductResearch.objects.filter(_user_marketplace_scope(request.user), id=research_id)
        .distinct()
        .first()
    )
    if not research:
        return JsonResponse({"ok": False, "error": "not_found"}, status=404)
    terminal = research.status in {
        MarketplaceProductResearch.STATUS_COMPLETED,
        MarketplaceProductResearch.STATUS_PARTIAL,
        MarketplaceProductResearch.STATUS_FAILED,
    }
    return JsonResponse({
        "ok": True,
        "id": research.id,
        "status": research.status,
        "status_label": research.get_status_display(),
        "progress": research.progress_percent,
        "current_step": research.current_step,
        "generated_prompt": research.generated_prompt,
        "source_selection": (research.search_plan or {}).get("source_selection", ""),
        "marketplaces": list(
            research.selected_marketplaces.filter(is_active=True)
            .order_by("search_priority", "order")
            .values("code", "name", "browser_verification_enabled")
        ),
        "terminal": terminal,
    })


@login_required
@subscription_required
def marketplace_price_tracking(request):
    researches_qs = (
        MarketplaceProductResearch.objects.select_related("product")
        .filter(
            _user_marketplace_scope(request.user),
            status__in=[
                MarketplaceProductResearch.STATUS_COMPLETED,
                MarketplaceProductResearch.STATUS_PARTIAL,
            ],
        )
        .distinct()
        .order_by("-track_price", "-updated_at")
    )

    if request.method == "POST":
        research_id = request.POST.get("research_id")
        action = request.POST.get("action")
        research = researches_qs.filter(id=research_id).first()
        if not research:
            messages.error(request, "Fiyat takibi için geçerli bir ürün araştırması seçmelisiniz.")
            return redirect("marketplace_price_tracking")

        if action == "track":
            research.track_price = True
            research.tracking_interval_hours = _tracking_interval_from_request(request)
            now = timezone.now()
            research.next_tracking_at = now
            research.save(update_fields=["track_price", "tracking_interval_hours", "next_tracking_at", "updated_at"])
            from core.tasks.marketplace_sync import refresh_single_tracked_research
            transaction.on_commit(lambda: refresh_single_tracked_research.delay(research.id))
            messages.success(request, f"{research} fiyat takibine alındı; ilk canlı kontrol kuyruğa gönderildi.")
        elif action == "untrack":
            research.track_price = False
            research.next_tracking_at = None
            research.save(update_fields=["track_price", "next_tracking_at", "updated_at"])
            messages.info(request, f"{research} fiyat takibinden çıkarıldı.")
        elif action == "delete":
            research_name = str(research)
            image_storage = research.product_image.storage if research.product_image else None
            image_name = research.product_image.name if research.product_image else ""
            with transaction.atomic():
                research.delete()
                if image_storage and image_name:
                    transaction.on_commit(lambda: image_storage.delete(image_name))
            messages.success(
                request,
                f"{research_name}; araştırma sonuçları, fiyat geçmişi ve görseliyle birlikte kalıcı olarak silindi.",
            )
        return redirect("marketplace_price_tracking")

    paginator = Paginator(researches_qs, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    researches = list(page_obj.object_list)
    research_ids = [research.id for research in researches]
    latest_history_by_research = {}
    previous_history_by_research = {}
    for history in (
        MarketplaceProductResearchMetricHistory.objects.filter(research_id__in=research_ids, user=request.user)
        .order_by("research_id", "-checked_at", "-id")
    ):
        if history.research_id not in latest_history_by_research:
            latest_history_by_research[history.research_id] = history
        elif history.research_id not in previous_history_by_research:
            previous_history_by_research[history.research_id] = history

    rows = []
    for research in researches:
        latest_history = latest_history_by_research.get(research.id)
        previous_history = previous_history_by_research.get(research.id)
        rows.append({
            "research": research,
            "image_url": _research_image_url(research),
            "name": research.detected_product_name or research.title or (research.product.name if research.product_id else "İsimsiz ürün"),
            "attributes": ", ".join(research.detected_attributes or []) or research.prompt,
            "latest_history": latest_history,
            "previous_history": previous_history,
        })

    return render(
        request,
        "marketplace/price_tracking.html",
        {
            "rows": rows,
            "page_obj": page_obj,
            "paginator": paginator,
        },
    )


@login_required
@subscription_required
def marketplace_price_history_report(request):
    allowed_statuses = [
        MarketplaceProductResearch.STATUS_COMPLETED,
        MarketplaceProductResearch.STATUS_PARTIAL,
    ]
    if request.method == "POST":
        research = (
            MarketplaceProductResearch.objects.filter(
                _user_marketplace_scope(request.user),
                id=request.POST.get("research_id"),
                status__in=allowed_statuses,
            )
            .distinct()
            .first()
        )
        if not research:
            messages.error(request, "Kalıcı olarak silinecek geçerli ürün araştırması bulunamadı.")
            return redirect("marketplace_price_history_report")
        research_name = str(research)
        image_storage = research.product_image.storage if research.product_image else None
        image_name = research.product_image.name if research.product_image else ""
        with transaction.atomic():
            research.delete()
            if image_storage and image_name:
                transaction.on_commit(lambda: image_storage.delete(image_name))
        messages.success(
            request,
            f"{research_name}; tüm sonuçları, ölçüm geçmişi ve görseliyle birlikte kalıcı olarak silindi.",
        )
        return redirect("marketplace_price_history_report")

    research_id = request.GET.get("research")
    tracked_researches = (
        MarketplaceProductResearch.objects.filter(
            _user_marketplace_scope(request.user),
            status__in=allowed_statuses,
        )
        .distinct()
        .order_by("-updated_at")
    )
    if research_id:
        tracked_researches = tracked_researches.filter(id=research_id)

    paginator = Paginator(tracked_researches, 50)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_researches = list(page_obj.object_list)
    research_ids = [research.id for research in page_researches]
    histories_by_research = {research_id: [] for research_id in research_ids}
    for history in (
        MarketplaceProductResearchMetricHistory.objects.filter(
            user=request.user,
            research_id__in=research_ids,
        )
        .order_by("-checked_at", "-id")
    ):
        histories_by_research[history.research_id].append(history)

    rows = []
    for research in page_researches:
        research_histories = histories_by_research.get(research.id, [])
        rows.append({
            "research": research,
            "name": research.detected_product_name or research.title or f"Araştırma #{research.id}",
            "histories": research_histories,
            "latest": research_histories[0] if research_histories else None,
            "history_count": len(research_histories),
        })

    return render(
        request,
        "marketplace/price_history_report.html",
        {
            "rows": rows,
            "tracked_researches": (
                MarketplaceProductResearch.objects.filter(
                    _user_marketplace_scope(request.user),
                    status__in=allowed_statuses,
                )
                .distinct()
                .order_by("-updated_at")
            ),
            "selected_research": research_id or "",
            "page_obj": page_obj,
            "paginator": paginator,
        },
    )
