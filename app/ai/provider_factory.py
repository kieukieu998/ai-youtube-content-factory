from typing import Optional, Any
from app.ai.base import BaseAIProvider
from app.ai.gemini_provider import GeminiProvider
from app.ai.deepseek_provider import OpenAICompatibleProvider
from app.core.config import settings

def get_ai_provider(provider_type: Optional[str] = None, stage: Optional[str] = None, db: Optional[Any] = None) -> BaseAIProvider:
    """
    Factory function to return the configured AI Provider instance.
    Can resolve provider by explicit type or by stage ('discovery', 'script', 'render').
    """
    db_settings = {}
    try:
        if db is not None:
            from app.database.models import Setting
            db_settings = {s.key: s.value for s in db.query(Setting).all()}
        else:
            from app.database.session import SessionLocal
            from app.database.models import Setting
            _session = SessionLocal()
            db_settings = {s.key: s.value for s in _session.query(Setting).all()}
            _session.close()
    except Exception:
        pass

    # Resolve provider type based on stage or default
    if not provider_type:
        if stage == "discovery":
            provider_type = db_settings.get("discovery_ai_provider") or db_settings.get("default_ai_provider") or settings.DEFAULT_AI_PROVIDER
        elif stage == "script":
            provider_type = db_settings.get("script_ai_provider") or db_settings.get("default_ai_provider") or settings.DEFAULT_AI_PROVIDER
        elif stage == "render":
            provider_type = db_settings.get("render_ai_provider") or db_settings.get("default_ai_provider") or settings.DEFAULT_AI_PROVIDER
        else:
            provider_type = db_settings.get("default_ai_provider") or settings.DEFAULT_AI_PROVIDER

    gemini_key = db_settings.get("gemini_api_key") or settings.GEMINI_API_KEY
    deepseek_key = db_settings.get("deepseek_api_key") or settings.DEEPSEEK_API_KEY
    openai_key = db_settings.get("openai_api_key") or settings.OPENAI_API_KEY

    if provider_type in ["gemini_free", "gemini"]:
        return GeminiProvider(api_key=gemini_key)
    elif provider_type == "deepseek":
        return OpenAICompatibleProvider(
            api_key=deepseek_key,
            base_url="https://api.deepseek.com/v1",
            model_name="deepseek-chat"
        )
    elif provider_type == "openai":
        return OpenAICompatibleProvider(
            api_key=openai_key,
            base_url="https://api.openai.com/v1",
            model_name="gpt-4o"
        )
    else:
        # Default fallback to Gemini
        return GeminiProvider(api_key=gemini_key)
