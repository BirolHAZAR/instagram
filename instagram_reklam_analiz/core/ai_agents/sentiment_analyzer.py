"""
Sentiment Analyzer AI Agent
Analyzes user comments and feedback to gauge brand perception.
"""

import logging
from typing import List, Dict, Any, Optional

from django.conf import settings
from langchain_openai import ChatOpenAI # type: ignore
from langchain_core.prompts import ChatPromptTemplate # type: ignore

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """
    Analyzes sentiment of Instagram comments and mentions.
    Provides overall polarity, emotion classification, and actionable insights.
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        self.llm = ChatOpenAI(
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            api_key=openai_api_key or settings.OPENAI_API_KEY,
            temperature=0.1,
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a sentiment analysis expert. Analyze the provided comments and return a JSON object.
            Use the following schema:
            {
                "overall_sentiment": "positive" | "negative" | "neutral",
                "confidence": float 0-1,
                "emotion_distribution": {"joy": x, "anger": y, "sadness": z, "surprise": w, "fear": v},
                "positive_keywords": [...],
                "negative_keywords": [...],
                "summary": "brief insight",
                "actionable_advice": "what to improve or maintain"
            }
            """),
            ("human", "Comments to analyze: {comments_text}")
        ])

    def analyze(self, comments: List[str]) -> Dict[str, Any]:
        """Analyze sentiment of a list of comments."""
        if not comments:
            return {"success": True, "overall_sentiment": "neutral", "message": "No comments to analyze"}
        
        try:
            # Limit number of comments to avoid token overflow
            comments_sample = comments[:50]
            text = "\n".join([f"- {c[:200]}" for c in comments_sample])
            response = self.llm.invoke(self.prompt.format_messages(comments_text=text))
            
            import json
            content = response.content
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end] if start != -1 else "{}"
            result = json.loads(json_str)
            return {"success": True, **result}
        except Exception as e:
            logger.exception("SentimentAnalyzer failed")
            return {"success": False, "error": str(e)}

    def batch_analyze(self, comments_by_post: Dict[int, List[str]]) -> Dict[int, Dict]:
        """Analyze sentiment for multiple posts."""
        results = {}
        for post_id, comment_list in comments_by_post.items():
            results[post_id] = self.analyze(comment_list)
        return results
