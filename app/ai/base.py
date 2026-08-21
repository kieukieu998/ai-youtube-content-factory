from abc import ABC, abstractmethod
from typing import Type, TypeVar, Optional, Dict, Any
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

class BaseAIProvider(ABC):
    """Abstract Base Class for all AI Providers (Gemini, DeepSeek, OpenAI, Claude)."""
    
    @abstractmethod
    async def generate_text(
        self, 
        prompt: str, 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> str:
        """Generate free-form text from prompt."""
        pass

    @abstractmethod
    async def generate_structured(
        self, 
        prompt: str, 
        schema: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.4
    ) -> T:
        """Generate validated Pydantic model response directly from AI."""
        pass
