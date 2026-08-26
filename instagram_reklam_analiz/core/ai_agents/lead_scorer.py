"""
Lead Scorer AI Agent
Scores potential leads (accounts that interacted with posts/stories) based on engagement signals.
"""

import logging
from typing import Dict, Any, List, Optional

from django.conf import settings
from langchain_openai import ChatOpenAI # type: ignore
from langchain_core.prompts import ChatPromptTemplate # type: ignore

logger = logging.getLogger(__name__)


class LeadScorer:
    """
    Automatically assigns a lead score (0-100) to Instagram users based on their interactions.
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        self.llm = ChatOpenAI(
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            api_key=openai_api_key or settings.OPENAI_API_KEY,
            temperature=0.2,
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a lead scoring AI. Analyze the user's interaction history with our Instagram account.
            Score from 0 to 100 based on: frequency of likes/comments/DMs, recency, sentiment, profile completeness.
            Return JSON: {"score": int, "tier": "hot"|"warm"|"cold", "reasoning": str}
            """),
            ("human", "User interaction data: {interaction_data}")
        ])

    def score_user(self, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Calculate lead score for a single user.
        user_data should contain: username, interaction_count, last_interaction_date, sentiment_score, etc.
        """
        try:
            response = self.llm.invoke(
                self.prompt.format_messages(interaction_data=str(user_data))
            )
            import json
            content = response.content
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end] if start != -1 else "{}"
            result = json.loads(json_str)
            return {"success": True, **result}
        except Exception as e:
            logger.exception("LeadScorer failed")
            return {"success": False, "error": str(e), "score": 0}

    def score_batch(self, users: List[Dict]) -> List[Dict]:
        """Score multiple users and return sorted by score descending."""
        scored = []
        for user in users:
            res = self.score_user(user)
            scored.append({
                "user": user.get("username"),
                "score": res.get("score", 0),
                "tier": res.get("tier", "cold"),
                "reasoning": res.get("reasoning", "")
            })
        return sorted(scored, key=lambda x: x["score"], reverse=True)
