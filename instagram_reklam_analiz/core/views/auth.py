# core/views/auth.py
from core.ai_agents.error_manager import capture_errors
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout as auth_logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm
from django.utils import timezone

from core.services.account_lifecycle import suspend_user_for_deletion
from core.services.trial import ensure_trial_subscription


@sensitive_post_parameters()
@csrf_protect
@capture_errors
def custom_signup(request):
    form_errors = {}
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')
        
        if not username:
            form_errors['username'] = 'Kullanici adi gereklidir.'
        elif len(username) < 3:
            form_errors['username'] = 'En az 3 karakter.'
        elif User.objects.filter(username=username).exists():
            form_errors['username'] = 'Bu kullanici adi kullaniliyor.'
        
        if email and User.objects.filter(email__iexact=email).exists():
            form_errors['email'] = 'Bu e-posta kullaniliyor.'
        
        if not password1:
            form_errors['password1'] = 'Sifre gereklidir.'
        elif len(password1) < 8:
            form_errors['password1'] = 'Sifre en az 8 karakter.'
        elif password1 != password2:
            form_errors['password2'] = 'Sifreler eslesmiyor.'
        
        if not form_errors:
            try:
                user = User.objects.create_user(username=username, email=email, password=password1)
                ensure_trial_subscription(user)
                user.backend = 'django.contrib.auth.backends.ModelBackend'
                login(request, user)
                messages.success(request, f'Hos geldin {username}!')
                if next_url and next_url.startswith("/"):
                    return redirect(next_url)
                return redirect('hesap_ekle')
            except Exception as e:
                messages.error(request, f'Hata: {str(e)}')
    
    return render(request, 'account/signup.html', {'form_errors': form_errors, 'next_url': next_url})


@login_required
@capture_errors
def profile_view(request):
    instagram_count = 0
    campaign_count = 0
    ai_credit_balance = None
    ai_credit_total = 0

    try:
        instagram_count = request.user.instagram_accounts.count()
    except Exception:
        instagram_count = 0

    try:
        campaign_count = request.user.adcampaign_set.count()
    except Exception:
        campaign_count = 0

    try:
        from core.services.entitlements import get_access_subscription, refresh_ai_credit_balance

        subscription = get_access_subscription(request.user)
        organization = subscription.organization if subscription else None
        ai_credit_balance = refresh_ai_credit_balance(request.user, organization=organization)
        if ai_credit_balance:
            ai_credit_total = (
                ai_credit_balance.plan_credits
                + ai_credit_balance.purchased_credits
            )
    except Exception:
        ai_credit_balance = None

    context = {
        "instagram_count": instagram_count,
        "campaign_count": campaign_count,
        "ai_credit_balance": ai_credit_balance,
        "ai_credit_total": ai_credit_total,
    }
    return render(request, 'account/profile.html', context)


@login_required
@capture_errors
def profile_update(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()

        if username and User.objects.exclude(pk=request.user.pk).filter(username=username).exists():
            messages.error(request, 'Bu kullanici adi zaten kullaniliyor.')
            return redirect('profile')
        if email and User.objects.exclude(pk=request.user.pk).filter(email__iexact=email).exists():
            messages.error(request, 'Bu e-posta adresi zaten kullaniliyor.')
            return redirect('profile')

        if username:
            request.user.username = username
        request.user.first_name = first_name
        request.user.last_name = last_name
        if email:
            request.user.email = email
        request.user.save(update_fields=["username", "first_name", "last_name", "email"])
        messages.success(request, 'Profil bilgileri guncellendi.')
        return redirect('profile')
    return redirect('profile')


@login_required
@capture_errors
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Sifreniz degistirildi!')
            return redirect('profile')
    return render(request, 'account/password_change.html')


@login_required
@capture_errors
def account_delete(request):
    if request.method == 'POST':
        profile = suspend_user_for_deletion(request.user)
        now = timezone.now()
        if profile.deletion_suspends_at and profile.deletion_suspends_at > now:
            messages.success(
                request,
                (
                    "Hesap silme talebiniz alindi. Aktif aboneliginiz bittikten sonra "
                    f"{profile.deletion_suspends_at:%d.%m.%Y} tarihinde aski sureci baslayacak; "
                    f"kalici silme tarihi {profile.scheduled_deletion_at:%d.%m.%Y}."
                ),
            )
            return redirect('profile')

        auth_logout(request)
        messages.success(
            request,
            (
                "Hesabiniz askiya alindi. "
                f"{profile.scheduled_deletion_at:%d.%m.%Y} tarihine kadar tekrar giris yaparsaniz hesap otomatik olarak acilir."
            ),
        )
        return redirect('index')
    profile = getattr(request.user, "profile", None)
    return render(request, 'account/delete_confirm.html', {"profile": profile})

def custom_logout(request):
    auth_logout(request)
    return redirect('index')
