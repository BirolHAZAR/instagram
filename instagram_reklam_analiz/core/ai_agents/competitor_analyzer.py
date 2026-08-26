"""
Competitor Analyzer AI Agent
Tracks and analyzes competitor Instagram accounts and campaigns.
"""

import logging
from typing import List, Dict, Any, Optional

from django.conf import settings
from langchain_openai import ChatOpenAI # type: ignore
from langchain_core.prompts import ChatPromptTemplate # type: ignore

logger = logging.getLogger(__name__)


class CompetitorAnalyzer:
    """
    Analyzes competitor Instagram profiles (public data) to derive insights.
    Note: Requires ability to fetch competitor metrics via Instagram API or scraping.
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        self.llm = ChatOpenAI(
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            api_key=openai_api_key or settings.OPENAI_API_KEY,
            temperature=0.3,
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a competitive intelligence analyst. Compare our brand metrics with competitor data.
            Provide a JSON output with:
            - "strengths": list of our advantages
            - "weaknesses": list of areas we are behind
            - "opportunities": list of gaps we can exploit
            - "threats": list of competitor moves that could harm us
            - "recommended_actions": list of 3-5 concrete actions
            """),
            ("human", "Our metrics: {our_metrics}\nCompetitor metrics: {competitor_metrics}")
        ])

    def analyze_competitor(self, our_metrics: Dict, competitor_metrics: Dict) -> Dict[str, Any]:
        """Perform SWOT-like analysis against a single competitor."""
        try:
            response = self.llm.invoke(
                self.prompt.format_messages(
                    our_metrics=str(our_metrics),
                    competitor_metrics=str(competitor_metrics)
                )
            )
            import json
            content = response.content
            start = content.find('{')
            end = content.rfind('}') + 1
            json_str = content[start:end] if start != -1 else "{}"
            result = json.loads(json_str)
            return {"success": True, **result}
        except Exception as e:
            logger.exception("CompetitorAnalyzer failed")
            return {"success": False, "error": str(e)}

    def track_multiple(self, our_metrics: Dict, competitors: List[Dict]) -> List[Dict]:
        """Analyze multiple competitors and return prioritized threats."""
        results = []
        for comp in competitors:
            analysis = self.analyze_competitor(our_metrics, comp.get("metrics", {}))
            results.append({
                "competitor_name": comp.get("name"),
                "analysis": analysis
            })
        return results
