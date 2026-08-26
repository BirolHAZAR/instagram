# core/decorators.py
from functools import wraps

from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect
from django.utils import timezone

from .models import AICreditLedger, InstagramAccount, UserSubscription, Ad
from core.models import FeatureUsageLedger
from core.services.entitlements import can_use_feature, get_access_subscription
from core.services.openai_usage import consume_openai_operation, refund_ai_tariff_credits
from core.services.ai_credit_purchase import insufficient_credit_payload


def _wants_json(request):
    return request.path.startswith("/api/") or "application/json" in request.headers.get("Accept", "")


def get_user_active_subscription(user):
    """Return the personal or agency subscription granting app access."""
    return get_access_subscription(user)


def instagram_account_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        if not InstagramAccount.objects.filter(user=request.user, is_active=True).exists():
            messages.warning(request, "Önce bir Instagram hesabı bağlamalısınız!")
            return redirect("add_instagram_account")
        return view_func(request, *args, **kwargs)
    return wrapper


def subscription_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        subscription = get_user_active_subscription(request.user)
        if not subscription:
            messages.warning(request, "Bu özelliği kullanmak için bir üyelik paketi satın almalısınız!")
            return redirect("pricing")
        return view_func(request, *args, **kwargs)
    return wrapper


def api_subscription_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"success": False, "message": "Oturum gerekli."}, status=401)
        subscription = get_user_active_subscription(request.user)
        if not subscription:
            return JsonResponse(
                {
                    "success": False,
                    "error": "subscription_required",
                    "message": "Bu islem icin aktif paket gerekli.",
                },
                status=402,
            )
        return view_func(request, *args, **kwargs)
    return wrapper


def check_instagram_account_limit(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        subscription = get_user_active_subscription(request.user)
        if not subscription:
            messages.warning(request, "Instagram hesabı eklemek için önce bir üyelik paketi satın almalısınız!")
            return redirect("pricing")
        plan = subscription.plan
        if plan:
            max_accounts = plan.max_instagram_accounts
            if max_accounts >= 999:
                return view_func(request, *args, **kwargs)
            current_count = InstagramAccount.objects.filter(user=request.user, is_active=True).count()
            if current_count >= max_accounts:
                messages.error(request, f"Paketiniz ({plan.display_name}) en fazla {max_accounts} Instagram hesabı eklemenize izin veriyor.")
                return redirect("pricing")
        return view_func(request, *args, **kwargs)
    return wrapper


def check_competitor_limit(view_func):
    """Rakip hesabı artık Rakip tablosu değil, Ad(source_type='COMPETITOR') üzerinden sayılır."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("login")
        subscription = get_user_active_subscription(request.user)
        if not subscription:
            messages.warning(request, "Rakip analizi için önce bir üyelik paketi satın almalısınız!")
            return redirect("pricing")
        plan = subscription.plan
        if plan:
            max_competitors = plan.max_competitors
            if max_competitors == 0:
                messages.error(request, f"{plan.display_name} paketiniz rakip analizi içermiyor.")
                return redirect("pricing")
            if max_competitors >= 9999:
                return view_func(request, *args, **kwargs)
            current_count = (
                Ad.objects.filter(user=request.user, source_type="COMPETITOR", is_active=True)
                .values("platform_account_id")
                .distinct()
                .count()
            )
            if current_count >= max_competitors:
                messages.error(request, f"{plan.display_name} paketiniz en fazla {max_competitors} rakip hesabı izlemenize izin veriyor.")
                return redirect("pricing")
        return view_func(request, *args, **kwargs)
    return wrapper


def ai_credit_required(amount=1, feature_key=None, reason="AI kullanimi", weekly_limit_field=None, weekly_reference_prefix=None, operation=None, tariff_key=""):
    """Require an active package and consume AI credits for premium AI actions."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"success": False, "message": "Oturum gerekli."}, status=401)

            if request.user.is_staff or request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            if not getattr(settings, "AI_CREDITS_ENFORCED", True):
                return view_func(request, *args, **kwargs)

            subscription = get_access_subscription(request.user)
            if not subscription:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "subscription_required",
                        "message": "Bu AI ozelligi icin aktif paket gerekli.",
                    },
                    status=402,
                )

            if feature_key:
                feature = can_use_feature(request.user, feature_key)
                if not feature.allowed:
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "feature_not_in_plan",
                            "message": feature.reason,
                        },
                        status=403,
                    )

            if weekly_limit_field:
                weekly_limit = int(getattr(subscription.plan, weekly_limit_field, 0) or 0)
                if 0 < weekly_limit < 9999:
                    today = timezone.localdate()
                    week_start = today - timezone.timedelta(days=today.weekday())
                    reference = weekly_reference_prefix or f"{view_func.__module__}.{view_func.__name__}"
                    used_this_week = AICreditLedger.objects.filter(
                        user=request.user,
                        action=AICreditLedger.ACTION_CONSUME,
                        reference__startswith=reference,
                        created_at__date__gte=week_start,
                    ).count()
                    if used_this_week >= weekly_limit:
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "weekly_ai_limit_reached",
                                "message": f"Bu paket haftalık {weekly_limit} AI analiz hakkı içeriyor. Haftalık limit doldu.",
                                "limit": weekly_limit,
                                "used": used_this_week,
                            },
                            status=429,
                        )

            if amount and amount > 0:
                result = consume_openai_operation(
                    user=request.user,
                    operation=operation or FeatureUsageLedger.OP_OPENAI_ANALYSIS,
                    tariff_key=tariff_key,
                    credit_amount=amount,
                    reason=reason,
                    reference=f"{view_func.__module__}.{view_func.__name__}",
                )
                if not result.allowed:
                    return JsonResponse(insufficient_credit_payload(
                        message=result.reason,
                        required_credits=result.used or amount,
                        available_credits=result.limit,
                    ), status=402)

            response = view_func(request, *args, **kwargs)
            if tariff_key and getattr(response, "status_code", 200) >= 400 and amount and amount > 0:
                refund_ai_tariff_credits(
                    user=request.user, tariff_key=tariff_key,
                    reason=f"HTTP {response.status_code}",
                    reference=f"{view_func.__module__}.{view_func.__name__}",
                )
            return response
        return wrapper
    return decorator


def ai_credit_required(amount=1, feature_key=None, reason="AI kullanimi", weekly_limit_field=None, weekly_reference_prefix=None, operation=None, tariff_key=""):
    """Route premium AI actions through the central OpenAI usage meter."""
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return JsonResponse({"success": False, "message": "Oturum gerekli."}, status=401)

            if request.user.is_staff or request.user.is_superuser:
                return view_func(request, *args, **kwargs)

            if not getattr(settings, "AI_CREDITS_ENFORCED", True):
                return view_func(request, *args, **kwargs)

            subscription = get_access_subscription(request.user)
            if not subscription:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "subscription_required",
                        "message": "Bu AI ozelligi icin aktif paket gerekli.",
                    },
                    status=402,
                )

            if feature_key:
                feature = can_use_feature(request.user, feature_key)
                if not feature.allowed:
                    return JsonResponse(
                        {
                            "success": False,
                            "error": "feature_not_in_plan",
                            "message": feature.reason,
                        },
                        status=403,
                    )

            if amount and amount > 0:
                result = consume_openai_operation(
                    user=request.user,
                    operation=operation or FeatureUsageLedger.OP_OPENAI_ANALYSIS,
                    credit_amount=amount,
                    tariff_key=tariff_key,
                    reference=f"{view_func.__module__}.{view_func.__name__}",
                    reason=reason,
                )
                if not result.allowed:
                    if result.code == "insufficient_ai_credits":
                        return JsonResponse(insufficient_credit_payload(
                            message=result.reason,
                            required_credits=result.used or amount,
                            available_credits=result.limit,
                        ), status=402)
                    return JsonResponse({
                        "success": False,
                        "error": result.code or "ai_usage_not_allowed",
                        "message": result.reason,
                        "limit": result.limit,
                        "used": result.used,
                    }, status=402)

            response = view_func(request, *args, **kwargs)
            if tariff_key and getattr(response, "status_code", 200) >= 400 and amount and amount > 0:
                refund_ai_tariff_credits(
                    user=request.user, tariff_key=tariff_key,
                    reason=f"HTTP {response.status_code}",
                    reference=f"{view_func.__module__}.{view_func.__name__}",
                )
            return response
        return wrapper
    return decorator
