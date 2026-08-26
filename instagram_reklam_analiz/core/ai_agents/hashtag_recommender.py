"""
Hashtag Recommender AI Agent
Generates optimized hashtag sets based on post content, industry trends, and audience.
"""

import logging
import re
from typing import List, Dict, Any, Optional

from django.conf import settings
from langchain_openai import ChatOpenAI # type: ignore
from langchain_core.prompts import ChatPromptTemplate # type: ignore

logger = logging.getLogger(__name__)


class HashtagRecommender:
    """
    AI-powered hashtag suggestion engine.
    Provides trending and relevant hashtags for Instagram posts.
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        self.llm = ChatOpenAI(
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            api_key=openai_api_key or settings.OPENAI_API_KEY,
            temperature=0.5,
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an Instagram hashtag expert. Generate 15-20 relevant hashtags for the given post.
            Include a mix of: 5-6 high-volume broad tags, 5-6 medium-volume niche tags, and 5-6 low-volume specific tags.
            Also suggest 3-5 trending tags if applicable. Return ONLY a JSON object in this exact format:
            {
                "hashtags": ["tag1", "tag2", ...],
                "trending_hashtags": ["trend1", ...],
                "mix_advice": "brief strategy explanation"
            }
            Do not include the '#' symbol in the tags (just words).
            """),
            ("human", "Post Caption/Description: {caption}\nTarget Audience: {audience}\nIndustry: {industry}")
        ])

    def recommend(self, caption: str, audience: str = "", industry: str = "") -> Dict[str, Any]:
        """Generate hashtag recommendations for a post."""
        try:
            response = self.llm.invoke(
                self.prompt.format_messages(
                    caption=caption[:500], 
                    audience=audience or "general",
                    industry=industry or "general"
                )
            )
            content = response.content
            import json
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end] if start != -1 else "{}"
            data = json.loads(json_str)
            
            # Clean hashtags (remove # if any, strip spaces)
            cleaned = [tag.strip().lstrip('#').lower().replace(' ', '') for tag in data.get("hashtags", [])]
            data["hashtags"] = cleaned[:20]  # max 20
            data["trending_hashtags"] = [t.strip().lstrip('#') for t in data.get("trending_hashtags", [])][:5]
            return {"success": True, "recommendation": data}
        except Exception as e:
            logger.exception("HashtagRecommender failed")
            return {"success": False, "error": str(e)}

    def get_formatted_hashtags(self, recommendation: Dict) -> str:
        """Convert recommendation dict to a string of hashtags with #."""
        if not recommendation.get("success"):
            return ""
        tags = recommendation.get("recommendation", {}).get("hashtags", [])
        return " ".join([f"#{tag}" for tag in tags])
