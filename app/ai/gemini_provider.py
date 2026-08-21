import os
import json
import asyncio
import warnings
from typing import Type, TypeVar, Optional, List
from pydantic import BaseModel
from loguru import logger
from app.ai.base import BaseAIProvider
from app.core.config import settings

# Suppress warnings
warnings.filterwarnings("ignore")

T = TypeVar("T", bound=BaseModel)

class GeminiProvider(BaseAIProvider):
    """
    Google Gemini AI Provider using Google's GenAI SDK (google.genai).
    """
    
    CANDIDATE_MODELS = [
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.5-flash",
        "gemini-3.1-flash-lite",
        "gemini-3.1-pro-preview"
    ]
    
    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-3.6-flash"):
        self.api_key = api_key or settings.GEMINI_API_KEY or os.getenv("GOOGLE_API_KEY")
        self.model_name = model_name
        self.client = None
        self._init_client()

    def _init_client(self):
        # Refresh key from config, env or database
        if not self.api_key or not self.api_key.strip():
            self.api_key = settings.GEMINI_API_KEY or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
            
        if not self.api_key or not self.api_key.strip():
            try:
                from app.database.session import SessionLocal
                from app.database.models import Setting
                db = SessionLocal()
                key_setting = db.query(Setting).filter(Setting.key == "gemini_api_key").first()
                if key_setting and key_setting.value.strip():
                    self.api_key = key_setting.value.strip()
                    settings.GEMINI_API_KEY = self.api_key
                db.close()
            except Exception:
                pass

        if self.api_key and self.api_key.strip():
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key.strip())
            except Exception as e:
                logger.warning(f"Could not initialize google.genai Client: {e}")
                self.client = None

    def _ensure_configured(self):
        if not self.api_key or not self.client:
            self._init_client()
            if not self.api_key or not self.client:
                raise ValueError(
                    "GEMINI_API_KEY chưa được thiết lập hoặc chưa hợp lệ. "
                    "Vui lòng nhập API Key tại trang Cấu Hình (Settings) hoặc trong file .env."
                )

    async def generate_text(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        self._ensure_configured()
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        loop = asyncio.get_event_loop()
        
        last_error = None
        models_to_try = [self.model_name] + [m for m in self.CANDIDATE_MODELS if m != self.model_name]
        
        for model in models_to_try:
            try:
                logger.info(f"Calling Gemini API with model: {model}...")
                response = await loop.run_in_executor(
                    None,
                    lambda m=model: self.client.models.generate_content(
                        model=m,
                        contents=full_prompt
                    )
                )
                if response and response.text:
                    return response.text.strip()
            except Exception as e:
                err_msg = str(e)
                last_error = e
                logger.warning(f"Gemini model '{model}' failed: {err_msg}. Trying fallback model...")
                if "RESOURCE_EXHAUSTED" in err_msg or "429" in err_msg:
                    # Brief pause to recover rate limit
                    await asyncio.sleep(2.0)
                if "API_KEY_INVALID" in err_msg or "PERMISSION_DENIED" in err_msg:
                    raise ValueError(f"Google API Key không hợp lệ: {err_msg}")
                continue

        raise RuntimeError(f"Tất cả các model Gemini đều không phản hồi: {last_error}")

    async def generate_structured(
        self, 
        prompt: str, 
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.3
    ) -> T:
        self._ensure_configured()
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        
        structured_instruction = (
            f"{system_prompt or ''}\n\n"
            f"BẮT BUỘC TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON HỢP LỆ THEO JSON SCHEMA SAU (KHÔNG KÈM TEXT GIẢI THÍCH, KHÔNG BỌC TRONG CODE BLOCK):\n"
            f"{schema_json}\n\n"
            f"NỘI DUNG YÊU CẦU:\n{prompt}"
        )
        
        raw_response = await self.generate_text(
            prompt=structured_instruction, 
            temperature=temperature
        )
        
        # Clean markdown code blocks
        clean_json = raw_response.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.startswith("```"):
            clean_json = clean_json[3:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()
        
        try:
            parsed_dict = json.loads(clean_json)
            return schema.model_validate(parsed_dict)
        except Exception as e:
            logger.error(f"Failed to parse structured JSON: {e}\nRaw output: {raw_response}")
            raise ValueError(f"AI response did not match expected schema: {e}")
