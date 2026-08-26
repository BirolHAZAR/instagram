import base64
import json
import os

import requests
from django.conf import settings

from core.services.ai_gateway import create_chat_completion_http


class AIContentAnalyzer:
    """OpenAI destekli gercek gorsel/video reklam analizi."""

    def __init__(self):
        self.api_key = getattr(settings, "OPENAI_API_KEY", "")
        self.api_url = "https://api.openai.com/v1/chat/completions"

    def _unavailable(self, message):
        return {
            "success": False,
            "score": 0,
            "quality": "Analiz edilemedi",
            "improvements": [],
            "suggested_title": "",
            "suggested_description": "",
            "hashtags": [],
            "error": message,
        }

    def analyze_image(self, image_path):
        if not image_path or not os.path.exists(image_path):
            return self._unavailable("Gorsel dosyasi bulunamadi.")
        if not self.api_key:
            return self._unavailable("OPENAI_API_KEY tanimli degil; gorsel analizi yapilamadi.")
        try:
            return self._call_openai_vision_api(image_path)
        except Exception as exc:
            return self._unavailable(f"Gorsel analizi tamamlanamadi: {exc}")

    def analyze_video(self, video_path):
        if not video_path or not os.path.exists(video_path):
            return self._unavailable("Video dosyasi bulunamadi.")
        if not self.api_key:
            return self._unavailable("OPENAI_API_KEY tanimli degil; video analizi yapilamadi.")
        try:
            video_info = self._get_video_info(video_path)
            return self._call_openai_video_api(video_info)
        except Exception as exc:
            return self._unavailable(f"Video analizi tamamlanamadi: {exc}")

    def analyze_carousel(self, image_paths):
        analyses = [self.analyze_image(path) for path in (image_paths or [])[:5]]
        successful = [item for item in analyses if item.get("success", True) is not False]
        if not successful:
            return self._unavailable("Karusel icin analiz edilebilir gorsel bulunamadi.")
        total_score = sum(item.get("score", 0) for item in successful) / len(successful)
        return {
            "success": True,
            "score": round(total_score),
            "quality": "Gorsel seti analiz edildi",
            "improvements": self._combine_recommendations(successful),
            "suggested_title": successful[0].get("suggested_title", ""),
            "suggested_description": successful[0].get("suggested_description", ""),
            "hashtags": successful[0].get("hashtags", []),
        }

    def _call_openai_vision_api(self, image_path):
        with open(image_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")

        payload = {
            "model": getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Sen profesyonel reklam kreatif analiz uzmanisin. "
                        "Gorseli reklam performansi, metin okunabilirligi, urun netligi, guven, teklif ve CTA acisindan degerlendir. "
                        "Sadece JSON dondur."
                    ),
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "Bu gorseli bir reklam kreatifi olarak analiz et. "
                                "JSON semasi: score, quality, improvements, suggested_title, suggested_description, hashtags."
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                    ],
                },
            ],
            "max_tokens": 700,
            "temperature": 0.25,
        }
        result = create_chat_completion_http(
            api_url=self.api_url, api_key=self.api_key, payload=payload,
            tariff_key="vision-analysis", reference="ai_content_analyzer.vision", timeout=45,
        )
        return self._parse_json_response(result["choices"][0]["message"]["content"])

    def _call_openai_video_api(self, video_info):
        payload = {
            "model": getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Sen profesyonel video reklam analiz uzmanisin. "
                        "Sadece verilen gercek metadata uzerinden yorum yap; izlemedigin kareler hakkinda iddia uretme. "
                        "Sadece JSON dondur."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Video reklami metadata uzerinden sinirli analiz et. "
                        f"Video bilgileri: {json.dumps(video_info, ensure_ascii=False)}. "
                        "JSON semasi: score, quality, improvements, suggested_title, suggested_description, hashtags."
                    ),
                },
            ],
            "max_tokens": 600,
            "temperature": 0.25,
        }
        result = create_chat_completion_http(
            api_url=self.api_url, api_key=self.api_key, payload=payload,
            tariff_key="video-analysis", reference="ai_content_analyzer.video", timeout=45,
        )
        parsed = self._parse_json_response(result["choices"][0]["message"]["content"])
        parsed["video_analysis_scope"] = "metadata_only"
        return parsed

    def _parse_json_response(self, content):
        content = (content or "").strip()
        if "```json" in content:
            content = content.split("```json", 1)[1].split("```", 1)[0]
        elif "```" in content:
            content = content.split("```", 1)[1].split("```", 1)[0]
        result = json.loads(content)
        return {
            "success": True,
            "score": int(result.get("score") or 0),
            "quality": result.get("quality") or "",
            "improvements": result.get("improvements") or [],
            "suggested_title": result.get("suggested_title") or "",
            "suggested_description": result.get("suggested_description") or "",
            "hashtags": result.get("hashtags") or [],
        }

    def _get_video_info(self, video_path):
        file_size = os.path.getsize(video_path) // 1024
        return {
            "size_kb": file_size,
            "filename": os.path.basename(video_path),
            "analysis_scope": "metadata_only",
        }

    def _combine_recommendations(self, analyses):
        all_recs = []
        for item in analyses:
            all_recs.extend(item.get("improvements", []))
        return list(dict.fromkeys(all_recs))[:8]
