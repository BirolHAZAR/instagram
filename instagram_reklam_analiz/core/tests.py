from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Ad,
    AdMetricHistory,
    AICreditLedger,
    Campaign,
    CampaignMetricHistory,
    CampaignOctoAnalysis,
    CampaignOctoRecommendation,
    MembershipPlan,
    Platform,
    PlatformAccount,
    PlatformConnection,
    UserSubscription,
)

User = get_user_model()

class ModelTests(TestCase):
    def test_create_user(self):
        user = User.objects.create_user(username='testuser', password='12345')
        self.assertEqual(user.username, 'testuser')
        self.assertTrue(user.check_password('12345'))

    def test_membership_plan_creation(self):
        plan = MembershipPlan.objects.create(
            name='bronze', display_name='Bronze', price=0, price_with_kdv=0,
            features='Test feature', order=1, is_active=True
        )
        self.assertEqual(plan.display_name, 'Bronze')

    def test_placeholder_token_account_is_skipped_in_batch_ad_sync(self):
        from core.tasks.v2_platform_sync import sync_all_v2_platform_accounts

        user = User.objects.create_user(username='placeholder-token-user', password='12345')
        platform = Platform.objects.create(name='Instagram', code='instagram')
        connection = PlatformConnection.objects.create(
            user=user,
            platform=platform,
            name='Instagram Organic',
            access_token='',
        )
        placeholder_account = PlatformAccount.objects.create(
            user=user,
            platform=platform,
            connection=connection,
            account_id='organic_instagram_001',
            account_name='Instagram Organic',
            access_token='',
        )
        demo_account = PlatformAccount.objects.create(
            user=user,
            platform=platform,
            account_id='demo-instagram-001',
            account_name='Instagram Demo',
            access_token='demo-token',
            extra_data={'demo': True},
        )
        real_account = PlatformAccount.objects.create(
            user=user,
            platform=platform,
            account_id='real-instagram-ad-account',
            account_name='Real Instagram Ads',
            access_token='EAAB_realistic_long_token_value_123456789',
        )

        with patch('core.tasks.v2_platform_sync.sync_v2_platform_account_ads.delay') as delay_mock:
            delay_mock.return_value.id = 'task-1'
            result = sync_all_v2_platform_accounts.run()

        delay_mock.assert_called_once_with(real_account.id, 'OWN')
        self.assertIn(
            {
                'account_id': placeholder_account.id,
                'platform': 'instagram',
                'source_type': 'OWN',
                'ads_synced': 0,
                'skipped': True,
                'reason': 'missing_or_placeholder_token',
            },
            result,
        )
        self.assertIn(
            {
                'account_id': demo_account.id,
                'platform': 'instagram',
                'source_type': 'OWN',
                'ads_synced': 0,
                'skipped': True,
                'reason': 'demo_account',
            },
            result,
        )

    @override_settings(
        STORAGES={
            'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
        }
    )
    def test_scheduled_report_preview_loads_email_html_in_iframe(self):
        from core.models import ScheduledReport

        user = User.objects.create_user(username='report-preview-user', email='preview@example.com', password='12345')
        report = ScheduledReport.objects.create(
            user=user,
            name='Preview Test Report',
            frequency='daily',
            recipient_emails=['preview@example.com'],
            send_hour=9,
        )
        campaign = Campaign.objects.create(
            user=user,
            platform_campaign_id='preview-campaign-001',
            name='Preview Campaign',
            status='ACTIVE',
            daily_budget='1234.56',
            currency='TRY',
        )
        report.campaigns.add(campaign)
        ad = Ad.objects.create(
            user=user,
            campaign=campaign,
            source_type='OWN',
            name='Preview Ad',
            status='ACTIVE',
        )
        AdMetricHistory.objects.create(
            ad=ad,
            date=timezone.localdate(),
            spend='123.45',
            impressions=100000,
            clicks=1234,
            conversions='12',
        )
        self.client.force_login(user)

        preview_response = self.client.get(reverse('scheduled_report_preview', args=[report.id]))
        self.assertEqual(preview_response.status_code, 200)
        self.assertContains(preview_response, 'mail-preview')
        self.assertContains(preview_response, 'Preview Test Report')
        self.assertContains(preview_response, 'Kapat')
        self.assertNotContains(preview_response, '<iframe')
        self.assertNotContains(preview_response, 'AI jetonu')

        html_response = self.client.get(reverse('scheduled_report_preview_html', args=[report.id]))
        self.assertEqual(html_response.status_code, 200)
        self.assertEqual(html_response['Content-Type'], 'text/html; charset=utf-8')
        self.assertEqual(html_response['X-Frame-Options'], 'SAMEORIGIN')
        self.assertContains(html_response, 'Preview Test Report')
        self.assertNotContains(html_response, 'AI jetonu')
        self.assertContains(html_response, '1.234,56 TL')
        self.assertContains(html_response, '123,45 TL')
        self.assertContains(html_response, '1.234')
        self.assertContains(html_response, '100.000')

    def test_scheduled_report_dispatch_claims_each_run_once(self):
        from core.models import ScheduledReport
        from core.tasks.report_tasks import dispatch_due_scheduled_reports

        user = User.objects.create_user(username='report-dispatch-user', password='12345')
        reports = [
            ScheduledReport.objects.create(
                user=user,
                name=f'{frequency.title()} Report',
                frequency=frequency,
                recipient_emails=[f'{frequency}@example.com'],
                send_hour=9,
                next_run_at=timezone.now() - timedelta(minutes=1),
            )
            for frequency in ('daily', 'weekly', 'biweekly', 'monthly')
        ]

        with patch('core.tasks.report_tasks.send_scheduled_report.delay') as delay_mock:
            first = dispatch_due_scheduled_reports.run()
            second = dispatch_due_scheduled_reports.run()

        self.assertEqual(delay_mock.call_count, 4)
        self.assertEqual({item.args[0] for item in delay_mock.call_args_list}, {report.id for report in reports})
        self.assertEqual(first['queued'], 4)
        self.assertEqual(second['queued'], 0)

    def test_scheduled_report_recipients_are_unique_case_insensitively(self):
        from core.services.scheduled_reports import _unique_recipient_emails

        recipients = _unique_recipient_emails([
            'team@example.com',
            ' TEAM@example.com ',
            'owner@example.com',
            'team@example.com',
        ])

        self.assertEqual(recipients, ['team@example.com', 'owner@example.com'])

    def test_duplicate_scheduled_report_task_sends_only_once(self):
        from core.models import ScheduledReport
        from core.tasks.report_tasks import send_scheduled_report

        user = User.objects.create_user(username='report-idempotency-user', password='12345')
        scheduled_for = timezone.now() - timedelta(minutes=1)
        report = ScheduledReport.objects.create(
            user=user,
            name='Daily Idempotent Report',
            frequency='daily',
            recipient_emails=['daily@example.com'],
            send_hour=9,
            next_run_at=timezone.now() + timedelta(days=1),
        )

        def mark_as_sent(report_instance):
            report_instance.last_sent_at = timezone.now()
            report_instance.save(update_fields=['last_sent_at', 'updated_at'])
            return {'sent': 1}

        with patch('core.services.scheduled_reports.send_scheduled_report', side_effect=mark_as_sent) as send_mock:
            first = send_scheduled_report.run(report.id, scheduled_for.isoformat())
            second = send_scheduled_report.run(report.id, scheduled_for.isoformat())

        self.assertTrue(first['success'])
        self.assertTrue(second['skipped'])
        send_mock.assert_called_once()

    def test_send_now_does_not_resend_a_recent_report(self):
        from core.models import ScheduledReport

        user = User.objects.create_user(username='report-send-now-user', password='12345')
        report = ScheduledReport.objects.create(
            user=user,
            name='Manual Report',
            frequency='daily',
            recipient_emails=['manual@example.com'],
            send_hour=9,
            last_sent_at=timezone.now(),
        )
        self.client.force_login(user)

        with patch('core.views.reports.send_report_now') as send_mock:
            response = self.client.post(reverse('scheduled_report_send_now', args=[report.id]))

        self.assertRedirects(response, reverse('report_list'))
        send_mock.assert_not_called()

    def _create_campaign_ai_fixture(self):
        user = User.objects.create_user(username='ai-campaign-user', password='12345')
        plan = MembershipPlan.objects.create(
            name='ai-test-plan',
            display_name='AI Test Plan',
            price=0,
            price_with_kdv=0,
            features='AI test',
            order=1,
            is_active=True,
            ai_analysis_per_month=5,
            ai_recommendation_per_month=5,
            ai_analysis_per_week=5,
            ai_recommendation_per_week=5,
            ai_credits_per_month=20,
        )
        UserSubscription.objects.create(
            user=user,
            plan=plan,
            start_date=timezone.localdate() - timedelta(days=1),
            end_date=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        AICreditLedger.objects.create(
            user=user,
            action=AICreditLedger.ACTION_GRANT,
            amount=20,
            balance_after=20,
            reference='test-grant',
            note='Test AI credits',
        )
        platform = Platform.objects.create(name='Facebook', code='facebook')
        account = PlatformAccount.objects.create(
            user=user,
            platform=platform,
            account_id='act_test_001',
            account_name='Test Ads Account',
            access_token='test-token',
        )
        campaign = Campaign.objects.create(
            user=user,
            platform_account=account,
            platform_campaign_id='cmp_test_001',
            name='Test Performans Kampanyasi',
            objective='SALES',
            status='ACTIVE',
            daily_budget=500,
            currency='TRY',
        )
        CampaignMetricHistory.objects.create(
            campaign=campaign,
            date=timezone.localdate(),
            impressions=10000,
            clicks=280,
            spend=1000,
            conversion_value=3200,
            conversions=12,
            ctr=2.8,
            cpc=3.57,
            cpm=100,
            roas=3.2,
            frequency=1.8,
        )
        return user, campaign

    def test_campaign_ai_analysis_and_recommendation_are_saved_separately(self):
        user, campaign = self._create_campaign_ai_fixture()
        self.client.force_login(user)

        with patch('core.services.campaign_panel_service._openai_campaign_text') as ai_text:
            ai_text.side_effect = [
                'Analiz bulgusu 1\nAnaliz bulgusu 2',
                'Yorum 1\nOneri 1',
            ]

            analysis_response = self.client.get(
                reverse('api_campaign_ai_report', args=[campaign.id]),
                {'type': 'analysis'},
            )
            recommendation_response = self.client.get(
                reverse('api_campaign_ai_report', args=[campaign.id]),
                {'type': 'recommendation'},
            )

        self.assertEqual(analysis_response.status_code, 200)
        self.assertEqual(recommendation_response.status_code, 200)

        analysis_payload = analysis_response.json()
        recommendation_payload = recommendation_response.json()
        self.assertTrue(analysis_payload['success'])
        self.assertTrue(recommendation_payload['success'])
        self.assertEqual(analysis_payload['type'], 'analysis')
        self.assertEqual(recommendation_payload['type'], 'recommendation')
        self.assertEqual(analysis_payload['recommendations'], [])
        self.assertIn('analysis_id', analysis_payload)
        self.assertIn('recommendation_id', recommendation_payload)

        self.assertEqual(CampaignOctoAnalysis.objects.filter(user=user, campaign=campaign).count(), 1)
        self.assertEqual(CampaignOctoRecommendation.objects.filter(user=user, campaign=campaign).count(), 1)

        analysis = CampaignOctoAnalysis.objects.get(user=user, campaign=campaign)
        recommendation = CampaignOctoRecommendation.objects.get(user=user, campaign=campaign)
        self.assertEqual(analysis.recommendation_text, '')
        self.assertTrue(analysis.agents_payload)
        self.assertTrue(recommendation.agents_payload)
        self.assertEqual(recommendation.analysis_id, analysis.id)
        self.assertEqual(recommendation.platform_name, 'Facebook')
        self.assertEqual(recommendation.account_name, 'Test Ads Account')

        consume_refs = list(
            AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME)
            .order_by('reference')
            .values_list('reference', flat=True)
        )
        self.assertEqual(consume_refs, [
            'campaign_panel.ai_report.analysis.campaign',
            'campaign_panel.ai_report.recommendation.campaign',
        ])

    def test_campaign_ai_report_uses_saved_record_without_new_ai_or_credit(self):
        user, campaign = self._create_campaign_ai_fixture()
        self.client.force_login(user)

        with patch('core.services.campaign_panel_service._openai_campaign_text', return_value='Kaydedilecek analiz'):
            first_response = self.client.get(
                reverse('api_campaign_ai_report', args=[campaign.id]),
                {'type': 'analysis'},
            )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(CampaignOctoAnalysis.objects.filter(user=user, campaign=campaign).count(), 1)
        first_consume_count = AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME).count()
        self.assertEqual(first_consume_count, 1)

        with patch('core.services.campaign_panel_service._openai_campaign_text') as ai_text:
            second_response = self.client.get(
                reverse('api_campaign_ai_report', args=[campaign.id]),
                {'type': 'analysis'},
            )

        self.assertEqual(second_response.status_code, 200)
        second_payload = second_response.json()
        self.assertTrue(second_payload['success'])
        self.assertTrue(second_payload['cached'])
        ai_text.assert_not_called()
        self.assertEqual(CampaignOctoAnalysis.objects.filter(user=user, campaign=campaign).count(), 1)
        self.assertEqual(
            AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME).count(),
            first_consume_count,
        )

    def test_campaign_ai_pdf_does_not_create_new_saved_records(self):
        user, campaign = self._create_campaign_ai_fixture()
        self.client.force_login(user)

        with patch('core.services.campaign_panel_service._openai_campaign_text', return_value='PDF icin analiz metni'):
            response = self.client.get(
                reverse('api_campaign_ai_pdf', args=[campaign.id]),
                {'type': 'analysis'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(CampaignOctoAnalysis.objects.filter(user=user, campaign=campaign).count(), 0)
        self.assertEqual(CampaignOctoRecommendation.objects.filter(user=user, campaign=campaign).count(), 0)
        self.assertEqual(
            AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME).count(),
            0,
        )
