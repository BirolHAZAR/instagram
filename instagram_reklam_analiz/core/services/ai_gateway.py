from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from core.models import AIOperationTariff
from core.services.openai_usage import extract_openai_usage, record_openai_token_usage


class AIGatewayBudgetExceeded(RuntimeError):
    pass


def _uses_max_completion_tokens(model_name: str) -> bool:
    """New reasoning/chat models reject the legacy ``max_tokens`` parameter."""
    normalized = str(model_name or "").strip().lower()
    return normalized.startswith(("gpt-5", "o1", "o3", "o4"))


def _estimate_tokens(value: Any) -> int:
    def compact_media(item):
        if isinstance(item, dict):
            return {key: compact_media(child) for key, child in item.items()}
        if isinstance(item, list):
            return [compact_media(child) for child in item]
        if isinstance(item, str) and item.startswith("data:image/"):
            return "[inline-image]"
        return item

    value = compact_media(value)
    text = json.dumps(value, ensure_ascii=False, default=str) if not isinstance(value, str) else value
    return max(1, (len(text) + 3) // 4)


@dataclass
class AIOperationBudget:
    operation_key: str
    max_input_tokens: int
    max_output_tokens: int
    max_calls: int
    request_id: str
    model_name: str = ""
    uses_openai: bool = True
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    _lock: Any = field(default_factory=Lock, repr=False)

    @classmethod
    def from_tariff(cls, tariff_key: str, *, request_id: str = ""):
        tariff = AIOperationTariff.objects.get(key=tariff_key, is_active=True)
        return cls(
            operation_key=tariff.key,
            max_input_tokens=int(tariff.max_input_tokens or 0),
            max_output_tokens=int(tariff.max_output_tokens or 0),
            max_calls=max(1, int(getattr(tariff, "max_calls", 1) or 1)),
            request_id=request_id or uuid.uuid4().hex,
            model_name=tariff.model_name or "",
            uses_openai=bool(tariff.uses_openai),
        )

    def reserve(self, *, estimated_input: int, requested_output: int):
        with self._lock:
            if self.calls >= self.max_calls:
                raise AIGatewayBudgetExceeded(
                    f"{self.operation_key}: toplam cagri limiti asildi ({self.max_calls})."
                )
            if self.max_input_tokens and self.input_tokens + estimated_input > self.max_input_tokens:
                raise AIGatewayBudgetExceeded(
                    f"{self.operation_key}: toplam giris token butcesi asildi ({self.max_input_tokens})."
                )
            remaining_output = self.max_output_tokens - self.output_tokens if self.max_output_tokens else requested_output
            if self.max_output_tokens and remaining_output <= 0:
                raise AIGatewayBudgetExceeded(
                    f"{self.operation_key}: toplam cikis token butcesi tukendi ({self.max_output_tokens})."
                )
            self.calls += 1
            self.input_tokens += estimated_input
            return max(1, min(requested_output, remaining_output))

    def reconcile(self, response, *, estimated_input: int):
        usage = extract_openai_usage(response)
        with self._lock:
            if usage.input_tokens:
                self.input_tokens += usage.input_tokens - estimated_input
            self.output_tokens += usage.output_tokens


def create_chat_completion(
    *, client, tariff_key: str, user=None, organization=None, reference: str,
    usage_kind: str = "customer_usage", budget: AIOperationBudget | None = None,
    record_usage: bool = True, **kwargs,
):
    """Execute and meter one chat completion under a shared operation budget."""
    if usage_kind == "customer_usage" and user is None:
        usage_kind = "system_job"
    elif usage_kind == "customer_usage" and (
        getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
    ):
        usage_kind = "admin_test"
    budget = budget or AIOperationBudget.from_tariff(tariff_key)
    if not budget.uses_openai:
        raise RuntimeError(f"{tariff_key}: OpenAI kullanmayan tarife Gateway'e gonderildi.")
    if budget.operation_key != tariff_key:
        raise ValueError("Gateway butcesi ile tarife anahtari uyusmuyor.")

    estimated_input = _estimate_tokens(kwargs.get("messages") or [])
    requested_output = int(
        kwargs.pop("max_completion_tokens", None)
        or kwargs.pop("max_tokens", None)
        or budget.max_output_tokens
        or 1000
    )
    reserved_output = budget.reserve(
        estimated_input=estimated_input,
        requested_output=requested_output,
    )
    if budget.model_name:
        kwargs["model"] = budget.model_name
    uses_completion_limit = _uses_max_completion_tokens(kwargs.get("model"))
    output_parameter = "max_completion_tokens" if uses_completion_limit else "max_tokens"
    if uses_completion_limit:
        # Reasoning models currently accept only their default sampling values.
        kwargs.pop("temperature", None)
        kwargs.pop("top_p", None)
    kwargs[output_parameter] = reserved_output

    response = client.chat.completions.create(**kwargs)
    budget.reconcile(response, estimated_input=estimated_input)
    if record_usage:
        record_openai_token_usage(
            response,
            user=user,
            organization=organization,
            reference=reference,
            operation_key=tariff_key,
            usage_kind=usage_kind,
            request_id=budget.request_id,
        )
    return response


def create_response(
    *, client, tariff_key: str, user=None, organization=None, reference: str,
    usage_kind: str = "customer_usage", budget: AIOperationBudget | None = None,
    record_usage: bool = True, **kwargs,
):
    """Execute and meter one Responses API call under a central tariff budget."""
    if usage_kind == "customer_usage" and user is None:
        usage_kind = "system_job"
    elif usage_kind == "customer_usage" and (
        getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
    ):
        usage_kind = "admin_test"
    budget = budget or AIOperationBudget.from_tariff(tariff_key)
    if not budget.uses_openai:
        raise RuntimeError(f"{tariff_key}: OpenAI kullanmayan tarife Gateway'e gonderildi.")
    if budget.operation_key != tariff_key:
        raise ValueError("Gateway butcesi ile tarife anahtari uyusmuyor.")

    estimated_input = _estimate_tokens(kwargs.get("input") or [])
    requested_output = int(kwargs.get("max_output_tokens") or budget.max_output_tokens or 1000)
    kwargs["max_output_tokens"] = budget.reserve(
        estimated_input=estimated_input,
        requested_output=requested_output,
    )
    if budget.model_name:
        kwargs["model"] = budget.model_name

    response = client.responses.create(**kwargs)
    budget.reconcile(response, estimated_input=estimated_input)
    if record_usage:
        record_openai_token_usage(
            response,
            user=user,
            organization=organization,
            reference=reference,
            operation_key=tariff_key,
            usage_kind=usage_kind,
            request_id=budget.request_id,
        )
    return response


def create_chat_completion_http(
    *, api_url: str, api_key: str, payload: dict, tariff_key: str, reference: str,
    user=None, organization=None, usage_kind: str = "customer_usage", timeout: int = 45,
):
    """Gateway equivalent for legacy HTTP integrations not using the OpenAI SDK."""
    import requests

    if usage_kind == "customer_usage" and user is None:
        usage_kind = "system_job"
    elif usage_kind == "customer_usage" and (
        getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)
    ):
        usage_kind = "admin_test"

    tariff = AIOperationTariff.objects.get(key=tariff_key, is_active=True)
    budget = AIOperationBudget.from_tariff(tariff_key)
    estimated_input = _estimate_tokens(payload.get("messages") or [])
    requested_output = int(
        payload.get("max_completion_tokens")
        or payload.get("max_tokens")
        or tariff.max_output_tokens
        or 1000
    )
    payload = dict(payload)
    payload.pop("max_tokens", None)
    payload.pop("max_completion_tokens", None)
    output_parameter = "max_completion_tokens" if _uses_max_completion_tokens(
        tariff.model_name or payload.get("model")
    ) else "max_tokens"
    if output_parameter == "max_completion_tokens":
        payload.pop("temperature", None)
        payload.pop("top_p", None)
    payload[output_parameter] = budget.reserve(
        estimated_input=estimated_input, requested_output=requested_output
    )
    if tariff.model_name:
        payload["model"] = tariff.model_name
    response = requests.post(
        api_url,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=timeout,
    )
    response.raise_for_status()
    result = response.json()
    budget.reconcile(result, estimated_input=estimated_input)
    record_openai_token_usage(
        result, user=user, organization=organization, reference=reference,
        operation_key=tariff_key, usage_kind=usage_kind, request_id=budget.request_id,
    )
    return result
