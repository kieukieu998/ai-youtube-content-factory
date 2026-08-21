from typing import List, Dict, Any
from pydantic import BaseModel, Field
from app.ai.provider_factory import get_ai_provider

class PerformanceReport(BaseModel):
    hook_rating: str = Field(description="Đánh giá hiệu quả của câu hook (Xuất sắc, Tốt, Cần cải thiện)")
    retention_analysis: str = Field(description="Phân tích tỷ lệ giữ chân người xem")
    actionable_recommendations: List[str] = Field(description="Các gợi ý hành động để kịch bản phim sau đạt tương tác cao hơn")

class AnalyticsAgent:
    """Agent 11: Phân tích số liệu tương tác và phản hồi tối ưu hóa kịch bản."""
    
    def __init__(self, provider_type: str = "gemini_free"):
        self.provider = get_ai_provider(provider_type)

    async def analyze_performance(
        self, 
        video_title: str, 
        views: int, 
        likes: int, 
        retention_rate: float
    ) -> PerformanceReport:
        prompt = (
            f"Video: {video_title}\n"
            f"Views: {views} | Likes: {likes} | Tỷ lệ giữ chân (Retention): {retention_rate}%\n\n"
            f"Hãy phân tích hiệu suất video này và đề xuất các cải tiến cụ thể cho các tập phim tiếp theo."
        )
        
        system_prompt = "Bạn là Analytics Agent AI chuyên gia phân tích dữ liệu tăng trưởng video ngắn."
        
        return await self.provider.generate_structured(
            prompt=prompt,
            schema=PerformanceReport,
            system_prompt=system_prompt
        )
