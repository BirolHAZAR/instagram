from __future__ import annotations

import hashlib
import html
from pathlib import Path

from django.conf import settings


DEMO_MEDIA_DIR = Path(settings.MEDIA_ROOT) / "demo" / "ads"
DEMO_MEDIA_URL = f"{settings.MEDIA_URL.rstrip('/')}/demo/ads"


PLATFORM_LABELS = {
    "instagram": "INSTAGRAM",
    "facebook": "FACEBOOK",
    "google_ads": "GOOGLE ADS",
    "tiktok": "TIKTOK",
    "linkedin": "LINKEDIN",
    "x": "X",
    "youtube": "YOUTUBE",
}


def _safe_text(value: str) -> str:
    return html.escape(str(value), quote=True)


def _palette(seed: str):
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()

    palettes = [
        ("#6C63FF", "#050816"),
        ("#FF6B35", "#140B05"),
        ("#00B894", "#04130F"),
        ("#0984E3", "#04101C"),
        ("#E84393", "#180713"),
        ("#FDCB6E", "#171204"),
        ("#00CEC9", "#031313"),
        ("#A29BFE", "#0D0B18"),
    ]

    index = int(digest[:8], 16) % len(palettes)
    return palettes[index]


def _label_from_seed(seed: str) -> str:
    parts = seed.replace("_", "-").split("-")
    platform = parts[0].lower()

    if platform in PLATFORM_LABELS:
        return PLATFORM_LABELS[platform]

    if platform == "marka2" and len(parts) > 1:
        return (
            f"DEMO MARKA 2 · "
            f"{PLATFORM_LABELS.get(parts[1].lower(), parts[1].upper())}"
        )

    if platform == "rival":
        return "RAKİP REKLAM"

    if platform == "social":
        return "SOCIAL DEMO"

    if platform == "marketplace":
        return "MARKETPLACE DEMO"

    return "REKLAMANALİZ.NET DEMO"


def create_demo_svg(seed: str, force: bool = False) -> Path:
    DEMO_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    filename = f"{seed}.svg"
    path = DEMO_MEDIA_DIR / filename

    if path.exists() and not force:
        return path

    primary, background = _palette(seed)
    label = _label_from_seed(seed)

    safe_label = _safe_text(label)
    safe_seed = _safe_text(seed)

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg"
width="900"
height="900"
viewBox="0 0 900 900">

<defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="{background}"/>
        <stop offset="100%" stop-color="{primary}"/>
    </linearGradient>

    <radialGradient id="glow">
        <stop offset="0%" stop-color="{primary}" stop-opacity="0.9"/>
        <stop offset="100%" stop-color="{primary}" stop-opacity="0"/>
    </radialGradient>
</defs>

<rect width="900" height="900" fill="url(#bg)"/>

<circle
    cx="720"
    cy="160"
    r="300"
    fill="url(#glow)"
/>

<circle
    cx="100"
    cy="800"
    r="250"
    fill="url(#glow)"
    opacity="0.55"
/>

<rect
    x="55"
    y="55"
    width="790"
    height="790"
    rx="42"
    fill="none"
    stroke="{primary}"
    stroke-width="3"
    opacity="0.65"
/>

<text
    x="80"
    y="130"
    fill="white"
    font-family="Arial, Helvetica, sans-serif"
    font-size="30"
    font-weight="700">
    REKLAMANİZ.NET
</text>

<text
    x="80"
    y="390"
    fill="white"
    font-family="Arial, Helvetica, sans-serif"
    font-size="68"
    font-weight="800">
    {safe_label}
</text>

<text
    x="80"
    y="470"
    fill="white"
    opacity="0.82"
    font-family="Arial, Helvetica, sans-serif"
    font-size="34">
    DEMO REKLAM KREATİFİ
</text>

<rect
    x="80"
    y="535"
    width="300"
    height="72"
    rx="36"
    fill="{primary}"
/>

<text
    x="230"
    y="582"
    text-anchor="middle"
    fill="white"
    font-family="Arial, Helvetica, sans-serif"
    font-size="26"
    font-weight="700">
    İNCELE
</text>

<text
    x="80"
    y="770"
    fill="white"
    opacity="0.5"
    font-family="monospace"
    font-size="18">
    {safe_seed}
</text>

</svg>
"""

    path.write_text(svg, encoding="utf-8")

    return path


def demo_image_url(seed: str) -> str:
    create_demo_svg(seed)

    return f"{DEMO_MEDIA_URL}/{seed}.svg"