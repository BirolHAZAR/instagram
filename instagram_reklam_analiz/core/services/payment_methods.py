import secrets

from django.utils import timezone

from core.models import PaymentMethod


def normalize_card_number(card_number):
    return "".join(ch for ch in str(card_number or "") if ch.isdigit())


def detect_card_brand(card_number):
    number = normalize_card_number(card_number)
    if number.startswith("4"):
        return "Visa"
    if number[:2] in {"51", "52", "53", "54", "55"} or 2221 <= int(number[:4] or 0) <= 2720:
        return "Mastercard"
    if number.startswith(("34", "37")):
        return "Amex"
    return "Kart"


def create_demo_card_token(card_number):
    number = normalize_card_number(card_number)
    return f"demo_tok_{number[-4:]}_{secrets.token_urlsafe(24)}"


def save_payment_method_from_checkout(user, cleaned_data):
    card_number = normalize_card_number(cleaned_data.get("card_number"))
    if len(card_number) < 12:
        return None

    expiry_month = int(cleaned_data.get("expiry_month") or 0)
    expiry_year = int(cleaned_data.get("expiry_year") or 0)
    if expiry_year < 100:
        expiry_year += 2000
    if not (1 <= expiry_month <= 12) or expiry_year < timezone.localdate().year:
        return None

    PaymentMethod.objects.filter(user=user, is_default=True).update(is_default=False)
    return PaymentMethod.objects.create(
        user=user,
        provider=PaymentMethod.PROVIDER_DEMO,
        token_encrypted=create_demo_card_token(card_number),
        card_holder=(cleaned_data.get("card_holder") or "")[:120],
        card_brand=detect_card_brand(card_number),
        last4=card_number[-4:],
        expiry_month=expiry_month,
        expiry_year=expiry_year,
        is_default=True,
        is_active=True,
    )
