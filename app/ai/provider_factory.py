from typing import Optional
from app.ai.base import BaseAIProvider
from app.ai.gemini_provider import GeminiProvider
from app.ai.deepseek_provider import OpenAICompatibleProvider
from app.core.config import settings

def get_ai_provider(provider_type: Optional[str] = None) -> BaseAIProvider:
    """Factory function to return the configured AI Provider instance."""
    provider = provider_type or settings.DEFAULT_AI_PROVIDER
    
    if provider in ["gemini_free", "gemini"]:
        return GeminiProvider()
    elif provider == "deepseek":
        return OpenAICompatibleProvider(
            api_key=settings.DEEPSEEK_API_KEY,
            base_url="https://api.deepseek.com/v1",
            model_name="deepseek-chat"
        )
    elif provider == "openai":
        return OpenAICompatibleProvider(
            api_key=settings.OPENAI_API_KEY,
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o"
        )
    else:
        # Default fallback to Gemini Free
        return GeminiProvider()
