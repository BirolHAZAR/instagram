from django.urls import reverse


AI_CREDIT_ANCHOR = "ai-kredi-paketleri"


def ai_credit_purchase_url():
    return f"{reverse('pricing')}#{AI_CREDIT_ANCHOR}"


def insufficient_credit_payload(*, message, required_credits=0, available_credits=0):
    purchase_url = ai_credit_purchase_url()
    return {
        "success": False,
        "error": "insufficient_ai_credits",
        "code": "insufficient_ai_credits",
        "message": message or "AI kredi bakiyeniz yetersiz.",
        "required_credits": int(required_credits or 0),
        "available_credits": int(available_credits or 0),
        "purchase_url": purchase_url,
        "redirect_url": purchase_url,
        "action_label": "Kredi Satın Al",
    }
