from typing import List
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
    
    def __init__(self, provider_type: str = "gemini_free"):
        self.provider = get_ai_provider(provider_type)

    async def analyze_movie(self, title: str, synopsis: str, genre: str) -> MovieAnalysis:
        prompt = (
            f"Phim: {title}\n"
            f"Thể loại: {genre}\n"
            f"Tóm tắt: {synopsis}\n\n"
            f"Hãy phân tích chi tiết cốt truyện, bóc tách các điểm nhấn, cao trào và cú lật (twist) "
            f"để chuẩn bị làm loạt video review ngắn trên TikTok. Đề xuất số tập video tối ưu."
        )
        
        system_prompt = "Bạn là Movie Analyst AI chuyên gia phân tích kịch bản điện ảnh và tâm lý người xem video ngắn."
        
        return await self.provider.generate_structured(
            prompt=prompt,
            schema=MovieAnalysis,
            system_prompt=system_prompt
        )
