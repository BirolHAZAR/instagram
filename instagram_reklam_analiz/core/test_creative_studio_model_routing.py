import base64
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings

from core.ai_agents.creative_studio_agent import ContentTone, CreativeStudioAgent
from core.models import AIOperationTariff
from core.services.ai_gateway import create_response


class CreativeStudioModelRoutingTests(TestCase):
    @patch("core.services.ai_gateway.create_chat_completion")
    def test_variant_generation_reserves_room_for_reasoning_and_json(self, mock_completion):
        mock_completion.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="""{
                "headline": "Yeni ürün",
                "primary_text": "Ürünü keşfedin.",
                "description": "Ürün açıklaması",
                "cta": "İncele",
                "hashtags": ["ürün"],
                "visual_brief": "Premium ürün çekimi",
                "visual_prompt": "Premium product photo",
                "landing_page_hook": "Şimdi keşfet",
                "ai_score": 90,
                "predicted_engagement": 80,
                "predicted_ctr": 3,
                "competitive_advantage": "Net sunum",
                "target_emotion": "Merak"
            }"""))]
        )
        agent = CreativeStudioAgent.__new__(CreativeStudioAgent)
        agent.client = Mock()
        agent.model = "gpt-5.6-terra"
        agent.user = None
        agent.organization = None
        agent.tone_directives = {
            ContentTone.PROFESSIONAL: "Profesyonel bir dil kullan.",
        }

        variant = agent._generate_single_variant(
            tone=ContentTone.PROFESSIONAL,
            product_description="Ürün promptu",
        )

        self.assertEqual(variant.headline, "Yeni ürün")
        kwargs = mock_completion.call_args.kwargs
        self.assertEqual(kwargs["reasoning_effort"], "low")
        self.assertEqual(kwargs["max_tokens"], 3000)

    @override_settings(OPENAI_IMAGE_MODEL="gpt-image-2")
    def test_gpt_image_2_edit_omits_unsupported_input_fidelity(self):
        agent = CreativeStudioAgent.__new__(CreativeStudioAgent)
        agent.client = Mock()
        agent.client.images.edit.return_value = SimpleNamespace(
            data=[SimpleNamespace(b64_json=base64.b64encode(b"image-bytes").decode("ascii"))]
        )

        result = agent.generate_visual(
            "Premium product photo",
            reference=[("product.png", b"reference-bytes", "image/png")],
        )

        self.assertEqual(result, b"image-bytes")
        kwargs = agent.client.images.edit.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-image-2")
        self.assertNotIn("input_fidelity", kwargs)

    def test_responses_gateway_uses_tariff_model_and_budget(self):
        AIOperationTariff.objects.update_or_create(
            key="creative-studio-final-review",
            defaults={
                "display_name": "Final review",
                "category": "Creative Studio",
                "credit_cost": 0,
                "model_name": "gpt-5.6-sol",
                "max_input_tokens": 5000,
                "max_output_tokens": 600,
                "max_calls": 1,
                "uses_openai": True,
                "is_active": True,
            },
        )
        response = SimpleNamespace(
            model="gpt-5.6-sol",
            output_text='{"overall_score":95}',
            usage=SimpleNamespace(input_tokens=20, output_tokens=5, total_tokens=25),
        )
        client = Mock()
        client.responses.create.return_value = response

        result = create_response(
            client=client,
            tariff_key="creative-studio-final-review",
            reference="test.creative.review",
            record_usage=False,
            model="wrong-model",
            input=[{"role": "user", "content": [{"type": "input_text", "text": "review"}]}],
            max_output_tokens=2000,
        )

        self.assertIs(result, response)
        kwargs = client.responses.create.call_args.kwargs
        self.assertEqual(kwargs["model"], "gpt-5.6-sol")
        self.assertEqual(kwargs["max_output_tokens"], 600)

    def test_creative_tariffs_are_routed_by_role(self):
        expected = {
            "creative-studio-prompt": "gpt-5.6-sol",
            "creative-studio-content": "gpt-5.6-terra",
            "creative-studio-final-review": "gpt-5.6-sol",
            "creative-studio-image": "gpt-image-2",
        }
        actual = dict(
            AIOperationTariff.objects.filter(key__in=expected).values_list("key", "model_name")
        )
        self.assertEqual(actual, expected)

    def test_full_visual_flow_costs_two_hundred_credits(self):
        costs = dict(
            AIOperationTariff.objects.filter(
                key__in=["creative-studio-prompt", "creative-studio-image"]
            ).values_list("key", "credit_cost")
        )
        self.assertEqual(costs["creative-studio-prompt"], 10)
        self.assertEqual(costs["creative-studio-image"], 190)
        self.assertEqual(sum(costs.values()), 200)
