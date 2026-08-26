import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


_METRIC_VALUE_RE = re.compile(
    r"(?P<label>Mevcut değer|Önceki değer|Değişim):\s*%?\s*"
    r"(?P<value>[-+]?\d(?:[\d.,]*\d)?)",
    flags=re.IGNORECASE,
)

_TURKISH_TERM_REPLACEMENTS = (
    (r"\bFrequency\b", "Sıklık"),
    (r"\bCTA\b", "Eylem çağrısı"),
    (r"\bCall to Action\b", "Eylem çağrısı"),
    (r"\bReels/Story/Feed\b", "Reels/Hikâyeler/Akış"),
    (r"\bStory\b", "Hikâyeler"),
    (r"\bFeed\b", "Akış"),
    (r"\bEngagement\b", "Etkileşim"),
    (r"\bConversion\b", "Dönüşüm"),
    (r"\bConversions\b", "Dönüşümler"),
    (r"\bRevenue\b", "Gelir"),
    (r"\bTracking\b", "Dönüşüm takibi"),
)


def _as_decimal(value):
    text = str(value or "0").strip().replace(" ", "")
    if "." in text and "," in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def format_tr_decimal(value):
    """Return a Turkish number with thousands separators and two decimals."""
    number = _as_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_metric_text_tr(text):
    """Normalize persisted rule messages and translate visible English terms."""
    if not text:
        return text or ""

    def replace_metric(match):
        label = match.group("label")
        prefix = "%" if label.casefold() == "değişim".casefold() else ""
        return f"{label}: {prefix}{format_tr_decimal(match.group('value'))}"

    result = str(text).translate(str.maketrans({
        "þ": "ş", "Þ": "Ş", "ý": "ı", "Ý": "İ", "ð": "ğ", "Ð": "Ğ",
    }))
    result = _METRIC_VALUE_RE.sub(replace_metric, result)
    for pattern, replacement in _TURKISH_TERM_REPLACEMENTS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result
