import json
import re
from typing import Dict, Any, List, Optional
from loguru import logger

from app.ai.provider_factory import get_ai_provider

class SEOGenerator:
    """Uses AI to generate high-CTR YouTube Titles, Descriptions, and Hashtags."""

    @classmethod
    async def generate_youtube_seo(
        cls,
        title: str,
        content: str,
        author: Optional[str] = None,
        aspect_ratio: str = "16:9"
    ) -> Dict[str, Any]:
        """
        Generate optimized YouTube SEO metadata including title, description, and hashtags.
        """
        is_shorts = (aspect_ratio == "9:16")
        excerpt = content[:1500] if len(content) > 1500 else content
        author_name = author or "Khuyết danh"

        prompt = f"""
Bạn là chuyên gia tăng trưởng kênh YouTube và tối ưu SEO video triệu view.
Hãy phân tích nội dung câu chuyện sau và tạo bộ siêu dữ liệu SEO YouTube bằng Tiếng Việt hấp dẫn nhất:

- Tiêu đề gốc: {title}
- Tác giả: {author_name}
- Định dạng: {"YouTube Shorts (Dọc 9:16)" if is_shorts else "YouTube Video Chuẩn (Ngang 16:9)"}
- Trích đoạn nội dung:
{excerpt}

YÊU CẦU ĐẦU RA JSON CHÍNH XÁC (không markdown ngoài, chỉ JSON hợp lệ):
{{
    "title": "Tiêu đề video chính thức (dưới 90 ký tự, cực kỳ tò mò, giật gân, cuốn hút {'kèm #Shorts ở cuối' if is_shorts else ''})",
    "alternative_titles": [
        "Tiêu đề gợi ý 2",
        "Tiêu đề gợi ý 3"
    ],
    "description": "Nội dung mô tả video đầy đủ: đoạn hook 2 câu đầu kịch tính, tóm tắt nội dung hấp dẫn không tiết lộ hết kết cục, thông tin tác giả, lời kêu gọi Đăng Ký Kênh (Subscribe) & Like, các hashtag ở cuối",
    "tags": ["danh", "sach", "the", "tags", "pho", "bien", "khong", "dau", "va", "co", "dau"],
    "hashtags": ["#truyenngan", "#audiobook", "#shorts", "#viral"]
}}
"""
        try:
            provider = get_ai_provider()
            response = await provider.generate_text(
                prompt=prompt,
                system_prompt="Bạn là chuyên gia SEO YouTube hàng đầu. Luôn xuất dữ liệu dạng JSON thuần túy.",
                temperature=0.7
            )

            # Clean JSON formatting
            clean_res = response.strip()
            if clean_res.startswith("```json"):
                clean_res = clean_res[7:]
            if clean_res.startswith("```"):
                clean_res = clean_res[3:]
            if clean_res.endswith("```"):
                clean_res = clean_res[:-3]
            clean_res = clean_res.strip()

            parsed = json.loads(clean_res)
            return {
                "title": parsed.get("title", title),
                "alternative_titles": parsed.get("alternative_titles", []),
                "description": parsed.get("description", f"{title}\nTác giả: {author_name}\n\nĐăng ký kênh để nghe thêm truyện mới nhé!"),
                "tags": parsed.get("tags", ["truyen ngan", "audiobook", "truyen hay"]),
                "hashtags": parsed.get("hashtags", ["#truyenngan", "#audiobook", "#viral"])
            }
        except Exception as e:
            logger.warning(f"Error generating AI SEO metadata: {e}. Using intelligent fallback.")
            
            # Fallback template
            short_tag = " #Shorts" if is_shorts else ""
            default_title = f"🔥 {title} | Truyện Đa Giọng Cực Hay - Tác Giả: {author_name}{short_tag}"
            default_desc = (
                f"📖 {title}\n"
                f"✍️ Tác giả: {author_name}\n\n"
                f"✨ Thưởng thức truyện ngắn đa giọng AI hấp dẫn với âm thanh sống động và hình ảnh nghệ thuật độc quyền.\n\n"
                f"🔔 Đừng quên bấm ĐĂNG KÝ KÊNH (Subscribe), Like và Chia sẻ để ủng hộ chúng mình ra thêm nhiều tập mới nhé!\n\n"
                f"#truyenngan #audiobook #truyenaudio {'#shorts #viral' if is_shorts else '#phimngan'}"
            )
            return {
                "title": default_title[:100],
                "alternative_titles": [
                    f"Truyện Ngắn Hay: {title}{short_tag}",
                    f"Nghe Truyện Đêm Khuya: {title}{short_tag}"
                ],
                "description": default_desc,
                "tags": ["truyen ngan", "audiobook", "truyen audio", "truyen dem khuya", title.lower()],
                "hashtags": ["#truyenngan", "#audiobook", "#viral"] + (["#shorts"] if is_shorts else [])
            }

    @classmethod
    async def generate_tiktok_seo(
        cls,
        title: str,
        content: str,
        author: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate optimized TikTok caption and viral hashtags.
        TikTok captions work best when short, punchy (hook) with trending tags.
        """
        excerpt = content[:1000] if len(content) > 1000 else content
        author_name = author or "Khuyết danh"

        prompt = f"""
Bạn là chuyên gia sáng tạo nội dung TikTok triệu view (viral creator).
Hãy phân tích nội dung câu chuyện sau và tạo caption TikTok hấp dẫn nhất bằng Tiếng Việt:

- Tiêu đề gốc: {title}
- Tác giả: {author_name}
- Trích đoạn nội dung:
{excerpt}

YÊU CẦU ĐẦU RA JSON CHÍNH XÁC (chỉ JSON, không markdown ngoài):
{{
    "caption": "Đoạn caption hoàn chỉnh cho TikTok (dưới 300 ký tự gồm câu hook cực sốc, kêu gọi xem hết video và 4-6 hashtag viral như #fyp #xuhuong #truyenngan #reviewphim)",
    "hook": "Câu mở đầu giật gân (hook)",
    "alternative_captions": [
        "Caption gợi ý 2 kèm hashtags",
        "Caption gợi ý 3 kèm hashtags"
    ],
    "hashtags": ["#fyp", "#xuhuong", "#truyenngan", "#audiobook", "#viral"]
}}
"""
        try:
            provider = get_ai_provider()
            response = await provider.generate_text(
                prompt=prompt,
                system_prompt="Bạn là chuyên gia TikTok Content Creator hàng đầu. Luôn xuất dữ liệu dạng JSON thuần túy.",
                temperature=0.7
            )

            clean_res = response.strip()
            if clean_res.startswith("```json"):
                clean_res = clean_res[7:]
            if clean_res.startswith("```"):
                clean_res = clean_res[3:]
            if clean_res.endswith("```"):
                clean_res = clean_res[:-3]
            clean_res = clean_res.strip()

            parsed = json.loads(clean_res)
            return {
                "caption": parsed.get("caption", f"🔥 {title} | Nghe đến cuối để biết sự thật rùng mình! #fyp #xuhuong #truyenngan #audiobook"),
                "hook": parsed.get("hook", f"Liệu cái kết của {title} có khiến bạn bất ngờ?"),
                "alternative_captions": parsed.get("alternative_captions", []),
                "hashtags": parsed.get("hashtags", ["#fyp", "#xuhuong", "#truyenngan", "#audiobook", "#viral"])
            }
        except Exception as e:
            logger.warning(f"Error generating TikTok SEO: {e}. Using fallback.")
            default_caption = f"🔥 {title} - Tác giả: {author_name} | Cái kết khiến ai cũng phải lặng người... Nghe hết nhé! #fyp #xuhuong #truyenngan #audiobook #viral"
            return {
                "caption": default_caption,
                "hook": f"Cái kết bất ngờ của {title}...",
                "alternative_captions": [
                    f"Nghe trọn bộ {title} đa giọng cực cuốn 🔥 #xuhuong #truyenhay #fyp",
                    f"Bạn có tin vào câu chuyện này? {title} 😱 #truyenngan #fyp #viral"
                ],
                "hashtags": ["#fyp", "#xuhuong", "#truyenngan", "#audiobook", "#viral"]
            }

