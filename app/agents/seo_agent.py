from typing import List
from pydantic import BaseModel, Field
from app.ai.provider_factory import get_ai_provider

class SEOMetadata(BaseModel):
    title: str = Field(description="Tiêu đề video ngắn giật tít dưới 60 ký tự")
    description: str = Field(description="Mô tả tóm tắt lôi cuốn kèm lời kêu gọi hành động")
    hashtags: List[str] = Field(description="Danh sách 5-8 hashtag trending (vd: #reviewphim, #phimhay, #tiktokgiaitri)")
    suggested_cover_text: str = Field(description="Chữ nổi bật in trên thumbnail/cover")

class SEOAgent:
    """Agent 10: Tối ưu hóa tiêu đề, mô tả và hashtag trending cho TikTok."""
    
    def __init__(self, provider_type: str = "gemini_free"):
        self.provider = get_ai_provider(provider_type)

    async def generate_seo_pack(
        self, 
        movie_title: str, 
        episode_number: int, 
        hook_text: str
    ) -> SEOMetadata:
        prompt = (
            f"Phim: {movie_title} (Tập {episode_number})\n"
            f"Hook: {hook_text}\n\n"
            f"Hãy tạo bộ siêu dữ liệu SEO tối ưu cho video TikTok: tiêu đề giật tít, caption hấp dẫn, "
            f"hashtag trending liên quan đến review phim và gợi ý text ngắn cho ảnh bìa."
        )
        
        system_prompt = "Bạn là SEO Agent AI chuyên gia tối ưu hóa thuật toán phân phối nội dung video ngắn trên TikTok."
        
        return await self.provider.generate_structured(
            prompt=prompt,
            schema=SEOMetadata,
            system_prompt=system_prompt
        )
