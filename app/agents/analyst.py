from typing import List, Optional
from pydantic import BaseModel, Field
from app.ai.provider_factory import get_ai_provider

class MovieAnalysis(BaseModel):
    core_theme: str = Field(description="Chủ đề cốt lõi của phim")
    plot_summary: str = Field(description="Tóm tắt mạch truyện đầy đủ")
    key_highlights: List[str] = Field(description="Các điểm nhấn gây cấn nhất trong phim")
    plot_twists: List[str] = Field(description="Các cú twist hoặc bất ngờ lớn")
    target_audience: str = Field(description="Đối tượng người xem phù hợp nhất")
    recommended_episodes: int = Field(description="Số tập video ngắn đề xuất (thường từ 2 đến 4 tập)", default=3)
    tone_style: str = Field(description="Giọng điệu phù hợp (dramatic, suspense, humorous)", default="dramatic")

class MovieAnalystAgent:
    """Agent 2: Phân tích cốt truyện, bóc tách cao trào và đề xuất số tập."""
    
    def __init__(self, provider_type: Optional[str] = None):
        self.provider = get_ai_provider(provider_type=provider_type, stage="script")

    async def analyze_movie(
        self, 
        title: str, 
        synopsis: str, 
        genre: str,
        target_episodes: Optional[int] = None
    ) -> MovieAnalysis:
        ep_instruction = f"BẮT BUỘC ĐỀ XUẤT ĐÚNG {target_episodes} TẬP VIDEO NGẮN." if target_episodes else "Đề xuất số tập video tối ưu (từ 1 đến 5 tập)."
        prompt = (
            f"Phim: {title}\n"
            f"Thể loại: {genre}\n"
            f"Tóm tắt: {synopsis}\n\n"
            f"Hãy phân tích chi tiết cốt truyện, bóc tách các điểm nhấn, cao trào và cú lật (twist) "
            f"để chuẩn bị làm loạt video review ngắn trên TikTok. {ep_instruction}"
        )
        
        system_prompt = "Bạn là Movie Analyst AI chuyên gia phân tích kịch bản điện ảnh và tâm lý người xem video ngắn."
        
        result = await self.provider.generate_structured(
            prompt=prompt,
            schema=MovieAnalysis,
            system_prompt=system_prompt
        )
        if target_episodes and target_episodes > 0:
            result.recommended_episodes = target_episodes
        return result
