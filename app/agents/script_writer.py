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
        target_episodes: Optional[int] = None,
        target_duration_seconds: int = 60
    ) -> FullScriptPackage:
        ep_count = target_episodes or analysis.recommended_episodes or 3
        duration_sec = target_duration_seconds if target_duration_seconds > 0 else 60
        target_words = max(120, int((duration_sec / 60.0) * 150))
        duration_desc = f"{duration_sec // 60} phút ({duration_sec} giây)" if duration_sec >= 60 else f"{duration_sec} giây"

        prompt = (
            f"Tên Phim: {movie_title}\n"
            f"Phong cách giọng điệu: {style}\n"
            f"Chủ đề cốt lõi: {analysis.core_theme}\n"
            f"Tóm tắt cốt truyện: {analysis.plot_summary}\n"
            f"Khoảnh khắc đắt giá: {', '.join(analysis.key_highlights)}\n"
            f"Cú Twist bất ngờ: {', '.join(analysis.plot_twists)}\n"
            f"SỐ LƯỢNG TẬP YÊU CẦU: CHÍNH XÁC {ep_count} TẬP.\n"
            f"THỜI LƯỢNG MỤC TIÊU MỖI TẬP: {duration_desc}.\n\n"
            f"YÊU CẦU VIẾT KỊCH BẢN CHUYÊN NGHIỆP (CỰC KỲ QUAN TRỌNG):\n"
            f"1. Tổng số phần (episodes) trong mảng 'episodes' BẮT BUỘC PHẢI CÓ ĐÚNG {ep_count} tập (đánh số episode_number từ 1 đến {ep_count}).\n"
            f"2. Hook (1-3s đầu): Phải là một câu hỏi giật gân, nghịch lý hoặc tình huống sống còn khiến người xem lập tức dừng lướt.\n"
            f"3. Độ dài Lời bình (Narrative Body): BẮT BUỘC viết đầy đủ, chi tiết, hấp dẫn khoảng {target_words} TỪ cho mỗi tập (tương ứng với tốc độ đọc AI chuẩn 150 từ/phút để đạt đúng thời lượng {duration_desc}).\n"
            f"4. Nhịp điệu câu chuyện: Kể chuyện lớp lang, giàu cảm xúc, dồn dập, dùng dấu câu ngắt nhịp tự nhiên để giọng đọc AI truyền cảm.\n"
            f"5. Cao trào & Kêu gọi (CTA): Kết thúc mỗi tập với cao trào nghẹt thở và câu kêu gọi đón xem tập tiếp theo."
        )
        
        system_prompt = (
            "Bạn là Chuyên Gia Biên Kịch Kênh Review & Phân Tích Phim Triệu View trên TikTok và YouTube. "
            "Phong cách viết của bạn cực kỳ cuốn hút, nghẹt thở, kịch tính từng giây, từ ngữ sinh động, giàu hình ảnh, không viết lan man hay khô khan học thuật."
        )
        
        result = await self.provider.generate_structured(
            prompt=prompt,
            schema=FullScriptPackage,
            system_prompt=system_prompt
        )
        result.total_episodes = len(result.episodes)
        return result

    async def rewrite_single_episode(
        self,
        movie_title: str,
        episode_number: int,
        total_episodes: int,
        current_hook: str,
        current_content: str,
        style: str = "dramatic",
        custom_instruction: Optional[str] = None
    ) -> EpisodeScript:
        prompt = (
            f"Tên Phim: {movie_title}\n"
            f"Tập cần viết lại: Tập {episode_number} trên tổng số {total_episodes} tập.\n"
            f"Phong cách yêu cầu: {style}\n"
            f"Nội dung hiện tại của tập {episode_number}:\n"
            f"- Hook cũ: {current_hook}\n"
            f"- Lời bình cũ: {current_content}\n\n"
            f"Yêu cầu bổ sung của người dùng: {custom_instruction or 'Làm cho nội dung kịch tính, lôi cuốn, giàu hình ảnh và sắc sảo hơn'}\n\n"
            f"YÊU CẦU ĐẦU RA:\n"
            f"1. Viết lại hoàn toàn mới cho riêng Tập {episode_number}.\n"
            f"2. Hook: Câu mở đầu cực kỳ giật gân, cuốn hút trong 1-3s đầu.\n"
            f"3. Narrative Body: Lời bình sắc sảo, dồn dập, khoảng 180-300 từ.\n"
            f"4. CTA: Câu kết thúc ấn tượng, kêu gọi tương tác."
        )
        system_prompt = (
            "Bạn là Chuyên Gia Biên Kịch Review Phim Triệu View trên TikTok. "
            "Hãy viết lại tập này với phong cách cực kỳ lôi cuốn, gay cấn và cuốn hút."
        )
        return await self.provider.generate_structured(
            prompt=prompt,
            schema=EpisodeScript,
            system_prompt=system_prompt
        )
