from typing import List
from pydantic import BaseModel, Field
from app.ai.provider_factory import get_ai_provider

class MovieCandidate(BaseModel):
    title: str = Field(description="Tên phim tiếng Việt hoặc tiếng Anh")
    original_title: str = Field(description="Tên gốc của phim")
    release_year: int = Field(description="Năm phát hành")
    genre: str = Field(description="Thể loại phim")
    duration_minutes: int = Field(description="Thời lượng phim tính bằng phút")
    synopsis: str = Field(description="Tóm tắt ngắn gọn nội dung cốt truyện")
    potential_score: float = Field(description="Điểm tiềm năng viral review TikTok từ 0 đến 100")

class HunterCandidatesList(BaseModel):
    movies: List[MovieCandidate]

class MovieHunterAgent:
    """Agent 1: Tìm kiếm, gợi ý phim hấp dẫn và chấm điểm tiềm năng viral."""
    
    def __init__(self, provider_type: str = "gemini_free"):
        self.provider = get_ai_provider(provider_type)

    async def discover_movies(
        self, 
        genre: str = "Hành Động, Kinh Dị", 
        limit: int = 3,
        existing_titles: List[str] = None
    ) -> List[MovieCandidate]:
        exclusion_text = ""
        if existing_titles and len(existing_titles) > 0:
            exclusion_text = f"\nTUYỆT ĐỐI KHÔNG GỢI Ý LẠI CÁC PHIM ĐÃ CÓ SAU ĐÂY: {', '.join(existing_titles[:30])}."

        prompt = (
            f"Hãy gợi ý {limit} bộ phim điện ảnh cực hay thuộc thể loại '{genre}' "
            f"có nhiều cao trào, nút thắt (twist) bất ngờ, thích hợp nhất để làm video review ngắn triệu view trên TikTok.{exclusion_text}\n\n"
            f"YÊU CẦU ĐỊNH DẠNG:\n"
            f"- 'title': Tên phim bằng TIẾNG VIỆT (kèm tên phổ biến tại Việt Nam).\n"
            f"- 'original_title': Tên gốc quốc tế của phim (Tiếng Anh/Hàn/Trung...).\n"
            f"- 'synopsis': Tóm tắt cốt truyện hấp dẫn bằng Tiếng Việt (khoảng 3-4 câu).\n"
            f"- 'genre': Thể loại chi tiết bằng Tiếng Việt.\n"
            f"- 'potential_score': Điểm tiềm năng viral từ 80.0 đến 99.0."
        )
        
        system_prompt = (
            "Bạn là Movie Hunter AI chuyên gia săn tìm các bộ phim điện ảnh xuất sắc, "
            "luôn đa dạng hóa danh mục phim và trình bày chuẩn song ngữ Việt - Anh."
        )
        
        result: HunterCandidatesList = await self.provider.generate_structured(
            prompt=prompt,
            schema=HunterCandidatesList,
            system_prompt=system_prompt
        )
        return result.movies
