"""
Auto Responder AI Agent
Automatically replies to direct messages based on intent classification.
"""
import os
import logging
from typing import Dict, Any, Optional
import venv

from django.conf import settings
from langchain_openai import ChatOpenAI # type: ignore

from langchain_core.prompts import ChatPromptTemplate # type: ignore

logger = logging.getLogger(__name__)


class AutoResponder:
    """
    Sends intelligent auto-replies to incoming DMs.
    Integrates with Instagram API to send replies.
    """

    def __init__(self, openai_api_key: Optional[str] = None):
        self.llm = ChatOpenAI(
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o"),
            api_key=openai_api_key or settings.OPENAI_API_KEY,
            temperature=0.7,
        )
        self.classify_prompt = ChatPromptTemplate.from_messages([
            ("system", "Classify the intent of this Instagram DM into one of: 'question', 'complaint', 'compliment', 'spam', 'order', 'support', 'other'. Return only the category name."),
            ("human", "{message}")
        ])
        self.reply_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a helpful brand assistant. Generate a polite, on-brand reply to this DM.
            Keep it under 300 characters. Use emojis appropriately. Do not include any hashtags.
            Reply as if you are the brand's social media manager.
            """),
            ("human", "Message: {message}\nIntent: {intent}\nBrand tone: {tone}")
        ])

    def classify_intent(self, message: str) -> str:
        """Determine intent of the incoming message."""
        try:
            response = self.llm.invoke(self.classify_prompt.format_messages(message=message[:500]))
            intent = response.content.strip().lower()
            return intent if intent in ['question', 'complaint', 'compliment', 'spam', 'order', 'support', 'other'] else 'other'
        except Exception:
            return "other"

    def generate_reply(self, message: str, intent: str, tone: str = "friendly") -> str:
        """Generate an appropriate reply based on intent."""
        try:
            if intent == "spam":
                return ""  # Do not reply to spam
            response = self.llm.invoke(
                self.reply_prompt.format_messages(message=message, intent=intent, tone=tone)
            )
            reply = response.content.strip()
            # Ensure reply is not too long
            return reply[:300]
        except Exception as e:
            logger.exception("AutoResponder generation failed")
            return "Thank you for your message! We'll get back to you soon."

    def handle_message(self, message_text: str, sender_username: str) -> Dict[str, Any]:
        """Full pipeline: classify, generate reply, and return response."""
        intent = self.classify_intent(message_text)
        reply = self.generate_reply(message_text, intent)
        return {
            "success": True,
            "intent": intent,
            "reply": reply,
            "sender": sender_username,
            "should_reply": bool(reply and intent != "spam")
        }
