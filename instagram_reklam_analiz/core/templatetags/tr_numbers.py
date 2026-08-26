from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _to_decimal(value):
    try:
        if value is None or value == "":
            return Decimal("0")
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _format_tr(value, decimals=2):
    try:
        decimals = int(decimals)
    except (TypeError, ValueError):
        decimals = 2
    if decimals < 0:
        decimals = 2

    value = _to_decimal(value)
    q = Decimal("1") if decimals == 0 else Decimal("0." + ("0" * (decimals - 1)) + "1")
    value = value.quantize(q)
    sign = "-" if value < 0 else ""
    value = abs(value)
    formatted = f"{value:,.{decimals}f}"
    return sign + formatted.replace(",", "TMP").replace(".", ",").replace("TMP", ".")


@register.filter
def tr_decimal(value, decimals=2):
    return _format_tr(value, decimals)


@register.filter
def tr_number(value, decimals=2):
    return _format_tr(value, decimals)


@register.filter
def tr_money(value):
    formatted = _format_tr(value, 2)
    if formatted.startswith("-"):
        return f"-{formatted[1:]} TL"
    return f"{formatted} TL"


@register.filter
def tr_percent(value):
    return f"%{_format_tr(value, 2)}"


@register.filter
def tr_int(value):
    return _format_tr(value, 0)


def _trim_tr_decimal_text(text):
    if "," not in text:
        return text
    return text.rstrip("0").rstrip(",")


@register.filter
def tr_smart(value, decimals=1):
    return _trim_tr_decimal_text(_format_tr(value, decimals))


@register.filter
def tr_money_smart(value, decimals=1):
    formatted = tr_smart(value, decimals)
    if formatted.startswith("-"):
        return f"-{formatted[1:]} TL"
    return f"{formatted} TL"


@register.filter
def tr_percent_smart(value, decimals=1):
    return f"%{tr_smart(value, decimals)}"


@register.filter
def tr_roas(value):
    return _format_tr(value, 2)


@register.filter
def tr_delta(value, decimals=2):
    value_dec = _to_decimal(value)
    prefix = "+" if value_dec > 0 else ""
    return f"{prefix}{_format_tr(value_dec, decimals)}%"
