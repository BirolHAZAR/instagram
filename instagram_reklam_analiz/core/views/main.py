# core/views/main.py
from core.ai_agents.error_manager import capture_errors
from django.http import HttpResponse
from datetime import timedelta
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.conf import settings

from core.models import InstagramAccount, AdCampaign
from core.ai_agents import PerformanceAnalyzer
from core.services.lead_messages import create_contact_message, create_demo_request

@capture_errors
def index(request):
    return render(request, 'index.html')

@capture_errors
def about(request):
    return render(request, 'about.html')

@capture_errors
def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        email = request.POST.get('email')
        subject = request.POST.get('subject')
        message_text = request.POST.get('message')
        
        if name and email and subject and message_text:
            create_contact_message(name=name, email=email, subject=subject, message=message_text)
            messages.success(request, 'Mesajiniz basariyla gonderildi!')
            return redirect('contact')
        else:
            messages.error(request, 'Lutfen tum alanlari doldurun!')
    
    return render(request, 'contact.html')


@capture_errors
def demo_request(request):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        email = (request.POST.get("email") or "").strip()
        phone = (request.POST.get("phone") or "").strip()
        company = (request.POST.get("company") or "").strip()
        role = (request.POST.get("role") or "").strip()
        ad_spend = (request.POST.get("ad_spend") or "").strip()
        platforms = request.POST.getlist("platforms")
        goal = (request.POST.get("goal") or "").strip()
        message_text = (request.POST.get("message") or "").strip()

        if name and email and phone and goal:
            create_demo_request(
                name=name,
                email=email,
                phone=phone,
                company=company,
                role=role,
                ad_spend=ad_spend,
                platforms=platforms,
                goal=goal,
                message=message_text,
            )
            messages.success(request, "Demo talebiniz alindi. Ekibimiz en kisa surede sizinle iletisime gececek.")
            return redirect("demo_request")
        messages.error(request, "Lutfen ad soyad, e-posta, telefon ve hedef alanlarini doldurun.")

    return render(request, "demo_request.html")


@login_required
@capture_errors
def dashboard(request):
    campaigns = AdCampaign.objects.filter(
        instagram_account__user=request.user
    ).select_related('instagram_account').order_by('-created_at')
    
    for campaign in campaigns:
        if not campaign.manual_override:
            campaign.update_status_from_dates()
    
    campaigns = AdCampaign.objects.filter(
        instagram_account__user=request.user
    ).select_related('instagram_account').order_by('-created_at')
    
    total_campaigns = campaigns.count()
    active_campaigns = campaigns.filter(status='active').count()
    draft_campaigns = campaigns.filter(status='draft').count()
    paused_campaigns = campaigns.filter(status='paused').count()
    
    total_budget = campaigns.aggregate(total=Sum('budget'))['total'] or 0
    total_spent = campaigns.aggregate(total=Sum('spent_amount'))['total'] or 0
    
    last_week = timezone.now() - timedelta(days=7)
    recent_campaigns = campaigns.filter(created_at__gte=last_week)
    
    instagram_accounts = InstagramAccount.objects.filter(user=request.user, is_active=True)
    
    context = {
        'campaigns': campaigns,
        'total_campaigns': total_campaigns,
        'active_campaigns': active_campaigns,
        'draft_campaigns': draft_campaigns,
        'paused_campaigns': paused_campaigns,
        'total_budget': total_budget,
        'total_spent': total_spent,
        'remaining_budget': total_budget - total_spent,
        'recent_campaigns': recent_campaigns,
        'instagram_accounts': instagram_accounts,
        'has_campaigns': campaigns.exists(),
    }
    
    return render(request, 'dashboard.html', context)
@staff_member_required
@capture_errors
def sentry_test_view(request):
    """Sentry test view'i"""
    # Kasıtlı hata
    x = 1 / 0
    return HttpResponse("Buraya asla gelemez!")

def bad_request_view(request, exception=None):
    return render(request, "400.html", status=400)


def permission_denied_view(request, exception=None):
    return render(request, "403.html", status=403)


def not_found_view(request, exception=None):
    return render(request, "404.html", status=404)


def server_error_view(request):
    return render(request, "500.html", status=500)
