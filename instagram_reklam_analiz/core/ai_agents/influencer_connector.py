"""
Influencer Connector AI Agent
Suggests potential influencers based on niche, engagement, and audience overlap.
"""

import logging
from typing import List, Dict, Any, Optional

from django.conf import settings
from langchain_openai import ChatOpenAI # type: ignore
from langchain_core.prompts import ChatPromptTemplate # type: ignore

logger = logging.getLogger(__name__)


class InfluencerConnector:
    """
    Matches brand with suitable Instagram influencers using AI analysis.
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        self.llm = ChatOpenAI(
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            api_key=openai_api_key or settings.OPENAI_API_KEY,
            temperature=0.3,
        )
        self.match_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an influencer marketing AI. Given brand requirements and influencer profiles,
            output a list of top 3 matching influencers with scores.
            Return JSON: [{"influencer_name": str, "match_score": float (0-100), "reason": str, "estimated_reach": int}]
            """),
            ("human", "Brand requirements: {brand_requirements}\nInfluencers data: {influencers_data}")
        ])

    def find_matches(self, brand_requirements: Dict, influencers: List[Dict]) -> List[Dict]:
        """
        Find best matching influencers based on brand criteria.
        influencers list should contain dict with keys: name, followers, engagement_rate, niche, audience_demo.
        """
        if not influencers:
            return []
        try:
            response = self.llm.invoke(
                self.match_prompt.format_messages(
                    brand_requirements=str(brand_requirements),
                    influencers_data=str(influencers[:20])
                )
            )
            import json
            content = response.content
            start = content.find('[')
            end = content.rfind(']') + 1
            if start == -1:
                start = content.find('{')
                end = content.rfind('}') + 1
                json_str = content[start:end] if start != -1 else "[]"
                data = json.loads(json_str)
                if isinstance(data, dict):
                    data = [data]
            else:
                json_str = content[start:end]
                data = json.loads(json_str)
            return data[:3]
        except Exception as e:
            logger.exception("InfluencerConnector failed")
            return []

    def enrich_influencer_data(self, influencer_username: str) -> Dict:
        """
        Placeholder: Fetch real-time influencer stats from Instagram or third-party API.
        """
        # TODO: Integrate with Instagram API or influencer marketing platforms.
        return {
            "name": influencer_username,
            "followers": 10000,
            "engagement_rate": 4.5,
            "niche": "fashion",
            "audience_demo": {"age_18_24": 40, "age_25_34": 35}
        }
