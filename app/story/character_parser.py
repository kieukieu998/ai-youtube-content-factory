import re
import json
from typing import List, Dict, Any, Tuple
from pydantic import BaseModel, Field
from loguru import logger

from app.ai.provider_factory import get_ai_provider

class StorySegment(BaseModel):
    speaker_name: str = Field(default="Người dẫn chuyện", description="Tên nhân vật hoặc Người dẫn chuyện")
    character_type: str = Field(
        default="narrator",
        description="Loại nhân vật: narrator, male_young, male_elder, female_young, female_elder, child"
    )
    emotion: str = Field(default="neutral", description="Cảm xúc câu thoại")
    text: str = Field(..., description="Nội dung lời nói hoặc lời dẫn")

class DramatizedStory(BaseModel):
    characters: List[str] = Field(default_factory=list, description="Danh sách các nhân vật được nhận diện")
    segments: List[StorySegment] = Field(default_factory=list, description="Danh sách các đoạn phân cảnh thoại")

class CharacterParser:
    """AI Agent to analyze stories, identify all characters, and split narrative into multi-voice dialogue segments."""

    VOICE_PROFILE_MAP = {
        "narrator": {
            "voice": "vi-VN-NamMinhNeural",
            "pitch": "+0Hz",
            "rate": "+0%",
            "label": "Người dẫn chuyện (Trầm ấm)"
        },
        "male_young": {
            "voice": "vi-VN-NamMinhNeural",
            "pitch": "+4Hz",
            "rate": "+5%",
            "label": "Nam thanh niên (Khỏe khoắn)"
        },
        "male_elder": {
            "voice": "vi-VN-NamMinhNeural",
            "pitch": "-12Hz",
            "rate": "-10%",
            "label": "Ông lão / Cụ già nam (Trầm khàn)"
        },
        "female_young": {
            "voice": "vi-VN-HoaiMyNeural",
            "pitch": "+3Hz",
            "rate": "+5%",
            "label": "Nữ / Thiếu nữ (Ngọt ngào)"
        },
        "female_elder": {
            "voice": "vi-VN-HoaiMyNeural",
            "pitch": "-8Hz",
            "rate": "-12%",
            "label": "Bà lão / Phụ nữ lớn tuổi (Từ tốn)"
        },
        "child": {
            "voice": "vi-VN-HoaiMyNeural",
            "pitch": "+18Hz",
            "rate": "+10%",
            "label": "Trẻ em / Em bé (Trong trẻo)"
        }
    }

    @classmethod
    def get_voice_config_for_type(cls, character_type: str) -> Dict[str, str]:
        """Return Edge-TTS (voice, pitch, rate) parameters for a given character type."""
        return cls.VOICE_PROFILE_MAP.get(character_type, cls.VOICE_PROFILE_MAP["narrator"])

    @classmethod
    async def parse_story(cls, text: str) -> DramatizedStory:
        """
        Analyze story using AI to detect characters and split into dramatized speech segments.
        Falls back to rule-based parser if AI is unavailable.
        """
        clean_content = text.strip()
        if not clean_content:
            return DramatizedStory(
                characters=["Người dẫn chuyện"],
                segments=[StorySegment(speaker_name="Người dẫn chuyện", character_type="narrator", text="Nội dung truyện trống.")]
            )

        try:
            ai_provider = get_ai_provider(stage="script")
            
            prompt = f"""
Bạn là chuyên gia phân tích kịch bản và đạo diễn lồng tiếng kịch truyền thanh (Audiobook Drama).
Nhiệm vụ của bạn: Hãy đọc câu chuyện dưới đây và tách thành từng câu/đoạn kèm danh tính nhân vật để lồng tiếng đa giọng.

CÁC LOẠI NHÂN VẬT (character_type):
- "narrator": Lời dẫn chuyện, miêu tả khung cảnh, suy nghĩ nội tâm không nói thành tiếng.
- "male_young": Nam trẻ tuổi, thanh niên, chàng trai, hoàng tử, chàng thợ săn...
- "male_elder": Ông lão, cụ già nam, sư phụ già, vua cha lớn tuổi...
- "female_young": Nữ trẻ tuổi, thiếu nữ, công chúa, cô bé lớn, cô hầu gái...
- "female_elder": Bà lão, cụ bà, người mẹ già, mụ phù thủy già...
- "child": Trẻ em nhỏ tuổi, em bé, cậu bé/cô bé nhỏ tuổi lanh lợi.

HÃY TRẢ VỀ DUY NHẤT MỘT JSON OBJECT HỢP LỆ (KHÔNG THÊM BẤT KỲ VĂN BẢN NÀO NGOÀI JSON) THEO CẤU TRÚC:
{{
  "characters": ["Người dẫn chuyện", "Tên nhân vật A", "Tên nhân vật B"],
  "segments": [
    {{
      "speaker_name": "Người dẫn chuyện",
      "character_type": "narrator",
      "emotion": "neutral",
      "text": "Ngày xửa ngày xưa, trong một khu rừng nọ..."
    }},
    {{
      "speaker_name": "Cô bé",
      "character_type": "child",
      "emotion": "excited",
      "text": "Ôi bà ơi, cháu nhớ bà quá!"
    }},
    {{
      "speaker_name": "Bà cụ",
      "character_type": "female_elder",
      "emotion": "loving",
      "text": "Cháu ngoan của bà, vào đây với bà nào."
    }}
  ]
}}

NỘI DUNG TRUYỆN:
\"\"\"{clean_content}\"\"\"
"""
            logger.info("Parsing story characters and dialogue using AI Provider...")
            drama_result = await ai_provider.generate_structured(
                prompt=prompt,
                schema=DramatizedStory,
                system_prompt="Bạn là chuyên gia đạo diễn lồng tiếng truyện. Chỉ trả về JSON hợp lệ."
            )
            
            if drama_result and drama_result.segments:
                logger.info(f"AI Story Dramatization succeeded: {len(drama_result.characters)} characters, {len(drama_result.segments)} segments.")
                return drama_result

        except Exception as e:
            logger.warning(f"AI Character parsing failed or unavailable ({e}). Using rule-based dialogue detector...")

        # Rule-based fallback parser
        return cls._rule_based_parse(clean_content)

    @classmethod
    def _rule_based_parse(cls, content: str) -> DramatizedStory:
        """Fallback regex parser when AI is offline."""
        paragraphs = content.split("\n")
        segments = []
        characters = set(["Người dẫn chuyện"])

        for p in paragraphs:
            p = p.strip()
            if not p:
                continue

            # Check if line contains quoted dialogue: "..." or “...”
            parts = re.split(r'["“]([^"”]+)["”]', p)
            if len(parts) > 1:
                for i, part in enumerate(parts):
                    part = part.strip()
                    if not part:
                        continue
                    if i % 2 == 1: # Quoted speech
                        # Heuristic detection for character type
                        lower_p = p.lower()
                        if any(w in lower_p for w in ["ông", "cụ ông", "lão"]):
                            ctype = "male_elder"
                            name = "Ông lão"
                        elif any(w in lower_p for w in ["bà", "cụ bà", "mụ"]):
                            ctype = "female_elder"
                            name = "Bà lão"
                        elif any(w in lower_p for w in ["bé", "em bé", "cháu", "tiểu tử"]):
                            ctype = "child"
                            name = "Em bé"
                        elif any(w in lower_p for w in ["cô", "nàng", "chị", "thiếu nữ", "công chúa"]):
                            ctype = "female_young"
                            name = "Cô gái"
                        elif any(w in lower_p for w in ["chàng", "anh", "hoàng tử", "thợ săn", "thầy"]):
                            ctype = "male_young"
                            name = "Chàng trai"
                        else:
                            ctype = "female_young"
                            name = "Nhân vật"

                        characters.add(name)
                        segments.append(StorySegment(speaker_name=name, character_type=ctype, text=part))
                    else:
                        segments.append(StorySegment(speaker_name="Người dẫn chuyện", character_type="narrator", text=part))
            else:
                segments.append(StorySegment(speaker_name="Người dẫn chuyện", character_type="narrator", text=p))

        return DramatizedStory(characters=list(characters), segments=segments)
