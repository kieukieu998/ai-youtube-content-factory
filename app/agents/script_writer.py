from typing import List, Optional
from pydantic import BaseModel, Field
from app.ai.provider_factory import get_ai_provider
from app.agents.analyst import MovieAnalysis

class EpisodeScript(BaseModel):
    episode_number: int = Field(description="Số thứ tự tập (1, 2, 3...)")
    title: str = Field(description="Tiêu đề gợi tò mò cho tập")
    hook_draft: str = Field(description="Câu mở đầu gợi ý trong 1-3s")
    narrative_body: str = Field(description="Lời bình chi tiết cho tập (khoảng 150-250 từ)")
    call_to_action: str = Field(description="Câu kêu gọi xem tiếp hoặc follow ở cuối video")

class FullScriptPackage(BaseModel):
    movie_title: str
    total_episodes: int
    episodes: List[EpisodeScript]

class ScriptWriterAgent:
    """Agent 3: Viết kịch bản review ngắn theo từng tập cho TikTok."""
    
    def __init__(self, provider_type: Optional[str] = None):
        self.provider = get_ai_provider(provider_type=provider_type, stage="script")

    async def generate_scripts(
        self, 
        movie_title: str, 
        analysis: MovieAnalysis,
        style: str = "dramatic",
        target_episodes: Optional[int] = None
    ) -> FullScriptPackage:
        ep_count = target_episodes or analysis.recommended_episodes or 3
        prompt = (
            f"Tên Phim: {movie_title}\n"
            f"Phong cách giọng điệu: {style}\n"
            f"Chủ đề: {analysis.core_theme}\n"
            f"Tóm tắt cốt truyện: {analysis.plot_summary}\n"
            f"Khoảnh khắc đắt giá: {', '.join(analysis.key_highlights)}\n"
            f"Cú Twist bất ngờ: {', '.join(analysis.plot_twists)}\n"
            f"SỐ LƯỢNG TẬP YÊU CẦU BẮT BUỘC: CHÍNH XÁC {ep_count} TẬP.\n\n"
            f"YÊU CẦU VIẾT KỊCH BẢN TIKTOK TRIỆU VIEW (CỰC KỲ QUAN TRỌNG):\n"
            f"1. Tổng số phần (episodes) trong mảng 'episodes' BẮT BUỘC PHẢI CÓ ĐÚNG {ep_count} tập (đánh số episode_number từ 1 đến {ep_count}).\n"
            f"2. Hook (1-3s): Phải là một câu hỏi giật gân, nghịch lý hoặc tình huống sống còn khiến người xem lập tức dừng lướt.\n"
            f"3. Lời bình (Narrative Body ~90-130 từ/tập): Kể chuyện nhịp độ nhanh, dồn dập, câu từ sắc bén, giàu hình ảnh và cảm xúc. Dùng dấu câu ngắt nhịp hợp lý để giọng đọc AI truyền cảm, có điểm nhấn.\n"
            f"4. Cao trào & Kêu gọi (CTA): Dừng ngay tại thời điểm gay cấn nhất, đặt câu hỏi bỏ lửng khiến người xem đón xem tiếp theo."
        )
        
        system_prompt = (
            "Bạn là Chuyên Gia Biên Kịch Kênh Review Phim Triệu View trên TikTok và YouTube Shorts. "
            "Phong cách viết của bạn cực kỳ cuốn hút, nghẹt thở, kịch tính từng giây, từ ngữ sinh động, không viết lan man hay khô khan học thuật."
        )
        
        result = await self.provider.generate_structured(
            prompt=prompt,
            schema=FullScriptPackage,
            system_prompt=system_prompt
        )
        result.total_episodes = len(result.episodes)
        return result
