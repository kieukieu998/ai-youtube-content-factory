from typing import List, Tuple
from app.subtitle.ass_generator import SubtitleGenerator
from app.audio.tts_engine import WordTimestamp

class SubtitleAgent:
    """Agent 7: Tạo phụ đề động chuẩn ASS Kinetic Highlight và file SRT chuẩn."""
    
    @staticmethod
    def generate_subtitles(
        words: List[WordTimestamp],
        output_ass_path: str,
        output_srt_path: str
    ) -> Tuple[str, str]:
        ass_path = SubtitleGenerator.generate_kinetic_ass(words, output_ass_path)
        srt_path = SubtitleGenerator.generate_srt(words, output_srt_path)
        return ass_path, srt_path
