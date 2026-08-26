import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from core.models import OctoRuleEngineRun, Platform, PlatformAccount


class OctoRuleAutomationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="octo-auto-user",
            password="test-password",
        )
        self.platform = Platform.objects.create(name="Facebook", code="facebook")
        self.account = PlatformAccount.objects.create(
            user=self.user,
            platform=self.platform,
            account_id="octo-auto-account",
            account_name="Octo Auto Account",
            access_token="test-token-for-facebook-account",
        )

    def test_rule_task_persists_auditable_completed_run(self):
        from core.tasks.admin_ops import generate_octo_tasks

        summary = {
            "campaigns_evaluated": 2,
            "signals_matched": 3,
            "tasks_created": 1,
            "tasks_skipped": 2,
        }

        def fake_command(*args, **kwargs):
            kwargs["stdout"].write("OCTO_SUMMARY_JSON=" + json.dumps(summary))

        with patch("core.tasks.admin_ops.call_command", side_effect=fake_command):
            result = generate_octo_tasks.run(
                user_id=self.user.id,
                account_id=self.account.id,
                trigger="ad_sync",
                days=7,
            )

        run = OctoRuleEngineRun.objects.get(id=result["run_id"])
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.platform_account, self.account)
        self.assertEqual(run.campaigns_evaluated, 2)
        self.assertEqual(run.signals_matched, 3)
        self.assertEqual(run.tasks_created, 1)

    def test_successful_ad_sync_queues_rule_engine_for_same_account(self):
        from core.tasks.v2_platform_sync import sync_v2_platform_account_ads

        class FakeAPI:
            def __init__(self, account):
                self.account = account

            def get_ads(self):
                return [{
                    "id": "ad-001",
                    "campaign_id": "campaign-001",
                    "campaign_name": "Campaign 001",
                    "adgroup_id": "group-001",
                    "adgroup_name": "Group 001",
                    "name": "Ad 001",
                    "status": "ACTIVE",
                    "date": "2026-07-13",
                    "spend": "100.00",
                    "impressions": 1000,
                    "clicks": 50,
                }]

        with patch("core.tasks.v2_platform_sync._get_api_class", return_value=FakeAPI), patch(
            "core.tasks.admin_ops.generate_octo_tasks.apply_async"
        ) as enqueue:
            enqueue.return_value.id = "octo-task-001"
            result = sync_v2_platform_account_ads.run(self.account.id, "OWN", 30)

        self.assertEqual(result["ads_synced"], 1)
        self.assertEqual(result["rule_engine"]["status"], "queued")
        enqueue.assert_called_once()
        kwargs = enqueue.call_args.kwargs["kwargs"]
        self.assertEqual(kwargs["user_id"], self.user.id)
        self.assertEqual(kwargs["account_id"], self.account.id)
        self.assertEqual(kwargs["trigger"], "ad_sync")

