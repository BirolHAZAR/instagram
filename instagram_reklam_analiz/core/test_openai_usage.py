from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from core.models import AICreditLedger, AICreditPackage, AIOperationTariff, FeatureUsageLedger, MembershipPlan, OpenAITokenUsageLedger, Organization
from core.services.entitlements import add_ai_credits, get_ai_credit_balance
from core.services.openai_usage import consume_openai_operation, record_openai_token_usage, refund_ai_tariff_credits
from core.services.ai_agent_ecosystem import run_sixteen_agent_orchestration
from core.services.ai_gateway import AIGatewayBudgetExceeded, AIOperationBudget, create_chat_completion
from core.services.ai_credit_purchase import insufficient_credit_payload


class OpenAITokenUsageTests(TestCase):
    def test_gateway_uses_max_completion_tokens_for_gpt5_models(self):
        AIOperationTariff.objects.create(
            key="gateway-gpt5", display_name="Gateway GPT-5", credit_cost=0,
            model_name="gpt-5.6-terra", max_input_tokens=1000, max_output_tokens=100,
            max_calls=1, is_active=True,
        )
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    model="gpt-5.6-terra",
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                    choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
                )

        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        create_chat_completion(
            client=client, tariff_key="gateway-gpt5", reference="gateway.gpt5",
            messages=[{"role": "user", "content": "test"}], max_tokens=50,
            temperature=0.2, top_p=0.8,
        )

        self.assertEqual(captured["max_completion_tokens"], 50)
        self.assertNotIn("max_tokens", captured)
        self.assertNotIn("temperature", captured)
        self.assertNotIn("top_p", captured)

    def test_insufficient_credit_response_points_to_credit_packages(self):
        payload = insufficient_credit_payload(
            message="AI kredi bakiyesi yetersiz.", required_credits=50, available_credits=40
        )
        self.assertEqual(payload["error"], "insufficient_ai_credits")
        self.assertEqual(payload["required_credits"], 50)
        self.assertEqual(payload["available_credits"], 40)
        self.assertEqual(payload["purchase_url"], "/pricing/#ai-kredi-paketleri")

        MembershipPlan.objects.create(
            name="pricing-test", display_name="Pricing Test", price=100,
            price_with_kdv=120, features="Test", is_active=True,
        )
        AICreditPackage.objects.create(
            name="credit-test", display_name="Credit Test", credits=100,
            price=100, price_with_kdv=120, is_active=True,
        )
        cache.clear()
        response = self.client.get("/pricing/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="ai-kredi-paketleri"')

    def test_gateway_enforces_shared_call_budget(self):
        AIOperationTariff.objects.create(
            key="gateway-budget", display_name="Gateway budget", credit_cost=1,
            model_name="gpt-4o", max_input_tokens=1000, max_output_tokens=100,
            max_calls=1, is_active=True,
        )

        class FakeCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(
                    model="gpt-4o",
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
                    choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
                )

        client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        budget = AIOperationBudget.from_tariff("gateway-budget")
        create_chat_completion(
            client=client, tariff_key="gateway-budget", budget=budget,
            reference="gateway.first", messages=[{"role": "user", "content": "test"}],
            max_tokens=50,
        )
        with self.assertRaises(AIGatewayBudgetExceeded):
            create_chat_completion(
                client=client, tariff_key="gateway-budget", budget=budget,
                reference="gateway.second", messages=[{"role": "user", "content": "test"}],
                max_tokens=50,
            )

    def test_gateway_classifies_staff_usage_as_admin_test(self):
        user = get_user_model().objects.create_superuser(
            username="gateway-admin", email="gateway@example.com", password="test"
        )
        AIOperationTariff.objects.create(
            key="gateway-admin-test", display_name="Gateway admin", credit_cost=0,
            model_name="gpt-4o", max_input_tokens=1000, max_output_tokens=100,
            max_calls=1, is_active=True,
        )

        response = SimpleNamespace(
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
        )
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
        create_chat_completion(
            client=client, tariff_key="gateway-admin-test", user=user,
            reference="gateway.admin", messages=[{"role": "user", "content": "test"}],
            max_tokens=50,
        )
        self.assertEqual(OpenAITokenUsageLedger.objects.get(reference="gateway.admin").usage_kind, "admin_test")

    def test_real_tokens_are_recorded_without_consuming_member_credits(self):
        user = get_user_model().objects.create_user(username="token-user", password="test")
        response = SimpleNamespace(
            model="gpt-4o",
            usage=SimpleNamespace(prompt_tokens=2650, completion_tokens=802, total_tokens=3452),
        )
        credit_rows_before = AICreditLedger.objects.filter(user=user).count()

        usage = record_openai_token_usage(response, user=user, reference="health_center.test")

        self.assertEqual(usage.total_tokens, 3452)
        token_row = OpenAITokenUsageLedger.objects.get(user=user)
        self.assertEqual(token_row.input_tokens, 2650)
        self.assertEqual(token_row.output_tokens, 802)
        self.assertEqual(token_row.total_tokens, 3452)
        self.assertEqual(token_row.model_name, "gpt-4o")
        self.assertEqual(AICreditLedger.objects.filter(user=user).count(), credit_rows_before)
        self.assertFalse(
            AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME).exists()
        )

    def test_system_usage_is_also_recorded_without_a_user(self):
        response = {"model": "gpt-4.1", "usage": {"input_tokens": 10, "output_tokens": 5}}

        record_openai_token_usage(response, reference="background.job")

        row = OpenAITokenUsageLedger.objects.get()
        self.assertIsNone(row.user)
        self.assertEqual(row.total_tokens, 15)

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_admin_change_list_renders_token_totals(self):
        admin_user = get_user_model().objects.create_superuser(
            username="token-admin", email="admin@example.com", password="test"
        )
        OpenAITokenUsageLedger.objects.create(input_tokens=10, output_tokens=5, total_tokens=15)
        member = get_user_model().objects.create_user(username="token-member", email="member@example.com")
        OpenAITokenUsageLedger.objects.create(user=member, input_tokens=20, output_tokens=7, total_tokens=27)
        FeatureUsageLedger.objects.create(
            user=member, operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS,
            status=FeatureUsageLedger.STATUS_BLOCKED,
            metadata={"tariff_key": "control-tower-analysis", "required_credits": 50, "available_credits": 40, "credit_state": "blocked"},
        )
        self.client.force_login(admin_user)

        response = self.client.get("/admin/core/openaitokenusageledger/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Toplam token")
        self.assertEqual(response.context["token_totals"]["token_sum"], 42)
        self.assertEqual(response.context["token_user_totals"][0]["token_sum"], 27)
        self.assertContains(response, "member@example.com")

        tariff_response = self.client.get("/admin/core/aioperationtariff/")
        self.assertEqual(tariff_response.status_code, 200)
        self.assertContains(tariff_response, "De&#287;i&#351;iklikleri Kaydet", html=True)

        usage_response = self.client.get("/admin/core/featureusageledger/")
        self.assertEqual(usage_response.status_code, 200)
        self.assertContains(usage_response, "Kredi: gerekli / mevcut")
        self.assertContains(usage_response, "Ger&#231;ek token", html=True)

        report_response = self.client.get("/admin/ai-kontor-raporu/")
        self.assertEqual(report_response.status_code, 200)
        self.assertContains(report_response, "AI i&#351;lem ge&#231;mi&#351;i", html=True)
        self.assertContains(report_response, "Son 30 g&#252;n engellenen", html=True)

    def test_tariff_credit_cost_overrides_hard_coded_fallback(self):
        user = get_user_model().objects.create_user(username="tariff-user", password="test")
        AIOperationTariff.objects.update_or_create(
            key="test-tariff", defaults={"display_name": "Test", "credit_cost": 4, "is_active": True}
        )

        result = consume_openai_operation(
            user=user, tariff_key="test-tariff", credit_amount=99, reference="test.tariff"
        )

        self.assertTrue(result.allowed)
        self.assertTrue(
            AICreditLedger.objects.filter(
                user=user, action=AICreditLedger.ACTION_CONSUME, amount=-4, reference="test.tariff"
            ).exists()
        )

    def test_zero_credit_local_tariff_does_not_consume_credits(self):
        user = get_user_model().objects.create_user(username="local-user", password="test")
        AIOperationTariff.objects.update_or_create(
            key="local-test", defaults={"display_name": "Local", "credit_cost": 0, "is_active": True, "uses_openai": False}
        )
        before = AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME).count()

        result = consume_openai_operation(user=user, tariff_key="local-test", reference="test.local")

        self.assertTrue(result.allowed)
        self.assertEqual(
            AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME).count(), before
        )

    def test_rapid_duplicate_operation_consumes_counter_and_credit_only_once(self):
        user = get_user_model().objects.create_user(username="duplicate-user", password="test")
        AIOperationTariff.objects.update_or_create(
            key="duplicate-test",
            defaults={"display_name": "Duplicate test", "credit_cost": 2, "is_active": True},
        )

        first = consume_openai_operation(
            user=user,
            operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS,
            tariff_key="duplicate-test",
            reference="same-button-action",
        )
        second = consume_openai_operation(
            user=user,
            operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS,
            tariff_key="duplicate-test",
            reference="same-button-action",
        )

        self.assertTrue(first.allowed)
        self.assertTrue(second.allowed)
        self.assertEqual(second.code, "duplicate_suppressed")
        self.assertEqual(
            FeatureUsageLedger.objects.filter(
                user=user,
                operation=FeatureUsageLedger.OP_OPENAI_ANALYSIS,
                status=FeatureUsageLedger.STATUS_ALLOWED,
                reference="same-button-action",
            ).count(),
            1,
        )
        self.assertEqual(
            AICreditLedger.objects.filter(
                user=user,
                action=AICreditLedger.ACTION_CONSUME,
                reference="same-button-action",
            ).count(),
            1,
        )

    @override_settings(TRIAL_AI_CREDITS=40)
    def test_member_with_40_credits_cannot_start_50_credit_operation(self):
        user = get_user_model().objects.create_user(username="limited-credit-user", password="test")
        AIOperationTariff.objects.update_or_create(
            key="fifty-credit-test",
            defaults={"display_name": "50 credit test", "credit_cost": 50, "is_active": True},
        )
        current = get_ai_credit_balance(user)
        if current < 40:
            add_ai_credits(user, 40 - current, reference="limited-credit-setup")

        result = consume_openai_operation(
            user=user, tariff_key="fifty-credit-test", reference="limited.credit.operation"
        )

        self.assertFalse(result.allowed)
        self.assertEqual(result.code, "insufficient_ai_credits")
        self.assertEqual(get_ai_credit_balance(user), 40)
        self.assertEqual(result.ledger.status, result.ledger.STATUS_BLOCKED)
        self.assertEqual(result.ledger.metadata["required_credits"], 50)
        self.assertEqual(result.ledger.metadata["available_credits"], 40)
        self.assertFalse(
            AICreditLedger.objects.filter(
                user=user, action=AICreditLedger.ACTION_CONSUME, reference="limited.credit.operation"
            ).exists()
        )

    def test_real_orchestrator_runs_four_grouped_calls_for_sixteen_agents(self):
        user = get_user_model().objects.create_user(username="sixteen-user", password="test")

        class FakeCompletions:
            def __init__(self):
                self.calls = 0

            def create(self, **kwargs):
                self.calls += 1
                names = [item["name"] for item in __import__("json").loads(kwargs["messages"][1]["content"])["agents"]]
                agents = [
                    {"name": name, "finding": "Kanita dayali bulgu", "recommendation": "Olculebilir aksiyon", "confidence": 0.8, "risk": "Kontrollu risk"}
                    for name in names
                ]
                return SimpleNamespace(
                    model="gpt-4o",
                    usage=SimpleNamespace(prompt_tokens=20, completion_tokens=10, total_tokens=30),
                    choices=[SimpleNamespace(message=SimpleNamespace(content=__import__("json").dumps({"agents": agents})))],
                )

        completions = FakeCompletions()
        client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
        credit_rows_before = AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME).count()
        AIOperationTariff.objects.update_or_create(
            key="test-sixteen",
            defaults={
                "display_name": "Test sixteen", "credit_cost": 0, "model_name": "gpt-4o",
                "max_input_tokens": 10000, "max_output_tokens": 4000, "max_calls": 4,
                "is_active": True,
            },
        )

        result = run_sixteen_agent_orchestration(
            client=client, model="gpt-4o", task="Test", context={"metric": 1}, user=user,
            reference="test.sixteen", max_workers=4, tariff_key="test-sixteen",
        )

        self.assertEqual(completions.calls, 4)
        self.assertEqual(len(result["agents"]), 16)
        self.assertEqual(OpenAITokenUsageLedger.objects.filter(user=user, reference__startswith="test.sixteen.group.").count(), 4)
        self.assertEqual(
            AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_CONSUME).count(), credit_rows_before
        )

    def test_failed_tariff_operation_can_refund_the_same_credit_cost(self):
        user = get_user_model().objects.create_user(username="refund-user", password="test")
        AIOperationTariff.objects.update_or_create(
            key="refund-test", defaults={"display_name": "Refund", "credit_cost": 5, "is_active": True}
        )
        initial_net = sum(AICreditLedger.objects.filter(user=user).values_list("amount", flat=True))
        result = consume_openai_operation(user=user, tariff_key="refund-test", reference="refund.operation")
        self.assertTrue(result.allowed)

        refund_ai_tariff_credits(
            user=user, tariff_key="refund-test", reason="provider error", reference="refund.operation"
        )
        refund_ai_tariff_credits(
            user=user, tariff_key="refund-test", reason="provider error again", reference="refund.operation"
        )

        net = sum(AICreditLedger.objects.filter(user=user).values_list("amount", flat=True))
        self.assertEqual(net, initial_net)
        self.assertEqual(AICreditLedger.objects.filter(user=user, action=AICreditLedger.ACTION_REFUND).count(), 1)
        usage_row = result.ledger
        usage_row.refresh_from_db()
        self.assertEqual(usage_row.status, usage_row.STATUS_FAILED)
        self.assertEqual(usage_row.metadata.get("credit_state"), "refunded")

    def test_personal_and_organization_credit_pools_are_isolated(self):
        user = get_user_model().objects.create_user(username="pool-user", password="test")
        organization = Organization.objects.create(name="Test Ajans", owner=user)
        personal_before = get_ai_credit_balance(user)
        organization_before = get_ai_credit_balance(user, organization=organization)

        add_ai_credits(user, 40, organization=None, reference="personal")
        add_ai_credits(user, 90, organization=organization, reference="agency")

        self.assertEqual(get_ai_credit_balance(user), personal_before + 40)
        self.assertEqual(get_ai_credit_balance(user, organization=organization), organization_before + 90)
