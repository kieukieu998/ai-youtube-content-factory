import json
from typing import Type, TypeVar, Optional
from pydantic import BaseModel
import httpx
from loguru import logger
from app.ai.base import BaseAIProvider
from app.core.config import settings

T = TypeVar("T", bound=BaseModel)

class OpenAICompatibleProvider(BaseAIProvider):
    """Generic Provider for OpenAI, DeepSeek, and custom OpenAI-compatible endpoints."""
    
    def __init__(
        self, 
        api_key: Optional[str] = None, 
        base_url: str = "https://api.deepseek.com/v1", 
        model_name: str = "deepseek-chat"
    ):
        self.api_key = api_key or settings.DEEPSEEK_API_KEY
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    async def generate_text(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        if not self.api_key:
            raise ValueError("API Key chưa được cung cấp cho Provider này.")
            
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
            
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()

    async def generate_structured(
        self, 
        prompt: str, 
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.3
    ) -> T:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        structured_instruction = (
            f"{system_prompt or ''}\n\n"
            f"BẮT BUỘC TRẢ VỀ ĐỊNH DẠNG JSON HỢP LỆ THEO JSON SCHEMA SAU (KHÔNG KÈM TEXT GIẢI THÍCH):\n"
            f"{schema_json}\n\n"
            f"NỘI DUNG YÊU CẦU:\n{prompt}"
        )
        
        raw_response = await self.generate_text(
            prompt=structured_instruction, 
            temperature=temperature
        )
        
        clean_json = raw_response.strip()
        if clean_json.startswith("```json"):
            clean_json = clean_json[7:]
        if clean_json.startswith("```"):
            clean_json = clean_json[3:]
        if clean_json.endswith("```"):
            clean_json = clean_json[:-3]
        clean_json = clean_json.strip()
        
        parsed_dict = json.loads(clean_json)
        return schema.model_validate(parsed_dict)
