# core/views/campaigns.py
from core.ai_agents.error_manager import capture_errors
import os
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from core.models import InstagramAccount, AdCampaign


@login_required
@capture_errors
def campaign_list(request):
    campaigns = AdCampaign.objects.filter(instagram_account__user=request.user).select_related('instagram_account')
    return render(request, 'campaigns/list.html', {'campaigns': campaigns})


@login_required
@capture_errors
def campaign_detail(request, campaign_id):
    campaign = get_object_or_404(AdCampaign, id=campaign_id, instagram_account__user=request.user)
    return render(request, 'campaigns/detail.html', {'campaign': campaign})


@login_required
@capture_errors
def campaign_create(request):
    instagram_accounts = InstagramAccount.objects.filter(user=request.user, is_active=True)
    
    if not instagram_accounts.exists():
        messages.warning(request, 'Once bir Instagram hesabi eklemelisiniz!')
        return redirect('instagram_dashboard')
    
    if request.method == 'POST':
        campaign_name = request.POST.get('campaign_name')
        account_id = request.POST.get('instagram_account')
        ad_type = request.POST.get('ad_type')
        budget = request.POST.get('budget')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        
        account = get_object_or_404(InstagramAccount, id=account_id, user=request.user)
        
        target_audience = {
            'age_range': {
                'min': int(request.POST.get('age_min')) if request.POST.get('age_min') else None,
                'max': int(request.POST.get('age_max')) if request.POST.get('age_max') else None,
            },
            'gender': request.POST.get('gender', 'all'),
            'language': request.POST.get('language', ''),
            'regions': request.POST.getlist('regions'),
            'interests': request.POST.getlist('interests'),
            'ad_title': request.POST.get('ad_title', ''),
            'ad_description': request.POST.get('ad_description', ''),
            'hashtags': request.POST.get('hashtags', ''),
            'target_url': request.POST.get('target_url', ''),
        }
        
        campaign = AdCampaign.objects.create(
            instagram_account=account,
            campaign_name=campaign_name,
            ad_type=ad_type,
            status='draft',
            budget=budget,
            spent_amount=0,
            start_date=start_date,
            end_date=end_date if end_date else None,
            target_audience=target_audience,
        )
        
        messages.success(request, f'{campaign_name} kampanyasi olusturuldu!')
        return redirect('campaign_detail', campaign_id=campaign.id)
    
    return render(request, 'campaigns/create.html', {
        'instagram_accounts': instagram_accounts,
    })


@login_required
@capture_errors
def campaign_edit(request, campaign_id):
    campaign = get_object_or_404(AdCampaign, id=campaign_id, instagram_account__user=request.user)
    
    if request.method == 'POST':
        campaign.campaign_name = request.POST.get('campaign_name', campaign.campaign_name)
        campaign.ad_type = request.POST.get('ad_type', campaign.ad_type)
        campaign.budget = request.POST.get('budget', campaign.budget)
        campaign.start_date = request.POST.get('start_date', campaign.start_date)
        campaign.end_date = request.POST.get('end_date') or None
        
        manual_override = request.POST.get('manual_override') == 'on'
        campaign.manual_override = manual_override
        if manual_override:
            campaign.manual_status = request.POST.get('manual_status')
            campaign.override_reason = request.POST.get('override_reason')
            campaign.override_date = timezone.now()
            campaign.status = campaign.manual_status
        
        target_audience = campaign.target_audience or {}
        target_audience['age_range'] = {
            'min': request.POST.get('age_min') or None,
            'max': request.POST.get('age_max') or None
        }
        target_audience['gender'] = request.POST.get('gender', 'all')
        target_audience['ad_title'] = request.POST.get('ad_title', '')
        target_audience['ad_description'] = request.POST.get('ad_description', '')
        campaign.target_audience = target_audience
        
        campaign.save()
        messages.success(request, 'Kampanya basariyla guncellendi!')
        return redirect('campaign_detail', campaign_id=campaign.id)
    
    return render(request, 'campaigns/edit.html', {
        'campaign': campaign,
        'now': timezone.now(),
    })


@login_required
@capture_errors
def campaign_delete(request, campaign_id):
    campaign = get_object_or_404(AdCampaign, id=campaign_id, instagram_account__user=request.user)
    campaign_name = campaign.campaign_name
    campaign.delete()
    messages.success(request, f'{campaign_name} kampanyasi silindi!')
    return redirect('campaign_list')


@login_required
@capture_errors
def campaign_pause(request, campaign_id):
    campaign = get_object_or_404(AdCampaign, id=campaign_id, instagram_account__user=request.user)
    if campaign.status == 'active':
        campaign.status = 'paused'
        campaign.save()
        messages.success(request, f'{campaign.campaign_name} kampanyasi duraklatildi.')
    return redirect('campaign_detail', campaign_id=campaign.id)


@login_required
@capture_errors
def send_to_instagram(request, campaign_id):
    campaign = get_object_or_404(AdCampaign, id=campaign_id, instagram_account__user=request.user)
    campaign.status = 'sent_to_instagram'
    campaign.sent_to_instagram_at = timezone.now()
    campaign.save()
    messages.success(request, f'{campaign.campaign_name} kampanyasi Instagram\'a gonderildi!')
    return redirect('campaign_detail', campaign_id=campaign.id)