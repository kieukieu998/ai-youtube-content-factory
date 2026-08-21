from typing import List
from pydantic import BaseModel, Field
from app.ai.provider_factory import get_ai_provider

class HookOption(BaseModel):
    hook_text: str = Field(description="Nội dung câu hook 1-3s gây sốc, giật gân hoặc đặt câu hỏi")
    hook_score: float = Field(description="Điểm giữ chân người xem (Retention Score) từ 0 đến 100")
    psychological_trigger: str = Field(description="Yếu tố tâm lý tác động (Curiosity, Shock, Fear, Mystery)")

class HookGenerationResult(BaseModel):
    options: List[HookOption]
    recommended_best_hook: str = Field(description="Câu hook được AI đánh giá cao nhất")

class HookGeneratorAgent:
    """Agent 4: Tạo 3-5 câu mở đầu (Hook) giữ chân người xem trong 3s đầu tiên."""
    
    def __init__(self, provider_type: str = "gemini_free"):
        self.provider = get_ai_provider(provider_type)

    async def generate_hooks(self, episode_content: str, movie_title: str) -> HookGenerationResult:
        prompt = (
            f"Phim: {movie_title}\n"
            f"Nội dung tập review:\n{episode_content}\n\n"
            f"Hãy sáng tạo 4 câu Hook mở đầu (dưới 15 từ) cực kỳ giật gân, khơi gợi tò mò tột độ "
            f"để giữ chân người dùng TikTok không lướt qua trong 3 giây đầu. Đánh giá điểm chất lượng cho từng câu."
        )
        
        system_prompt = "Bạn là Hook Generator AI bậc thầy về tâm lý học hành vi người xem mạng xã hội ngắn (TikTok / Reels)."
        
        return await self.provider.generate_structured(
            prompt=prompt,
            schema=HookGenerationResult,
            system_prompt=system_prompt
        )
