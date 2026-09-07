import os
from pathlib import Path
from typing import List, Dict, Any
from dataclasses import dataclass
from loguru import logger

@dataclass
class SegmentTiming:
    speaker_name: str
    character_type: str
    text: str
    start_sec: float
    end_sec: float

class StorySubtitleBuilder:
    """Builds synchronized ASS / SRT subtitles for audiobook stories."""

    @staticmethod
    def sec_to_ass_time(sec: float) -> str:
        """Convert seconds to ASS timestamp format: H:MM:SS.cs"""
        hours = int(sec // 3600)
        rem = sec % 3600
        minutes = int(rem // 60)
        seconds = int(rem % 60)
        cs = int(round((rem - int(rem)) * 100))
        if cs >= 100:
            cs = 99
        return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"

    @classmethod
    def split_text_into_sub_chunks(cls, text: str, max_words: int = 14) -> List[str]:
        """Split a long paragraph or line into balanced readable chunks."""
        words = text.strip().split()
        if len(words) <= max_words:
            return [text.strip()]

        chunks = []
        for i in range(0, len(words), max_words):
            chunks.append(" ".join(words[i:i + max_words]))
        return chunks

    @classmethod
    def generate_story_ass(
        cls,
        timings: List[SegmentTiming],
        output_ass_path: Path,
        aspect_ratio: str = "16:9"
    ) -> Path:
        """
        Generate ASS subtitle file tailored for audiobook video reading.
        Displays speaker badge + dialogue text.
        """
        is_vertical = aspect_ratio == "9:16"
        res_x = 1080 if is_vertical else 1920
        res_y = 1920 if is_vertical else 1080
        font_size = 54 if is_vertical else 42
        margin_v = 420 if is_vertical else 130
        margin_lr = 60 if is_vertical else 120
        max_words_per_chunk = 8 if is_vertical else 14

        # Speaker color mapping
        speaker_colors = {
            "narrator": "&H00E2E8F0&",   # Crisp White / Silver
            "male_young": "&H0038BDF8&", # Sky Blue
            "male_old": "&H0094A3B8&",   # Steel Grey
            "female_young": "&H00F472B6&",# Pink
            "female_old": "&H00C084FC&", # Violet
            "child": "&H00FDE047&"       # Sunshine Yellow
        }

        ass_header = f"""[Script Info]
Title: AI Audiobook Synchronized Subtitles
ScriptType: v4.00+
PlayResX: {res_x}
PlayResY: {res_y}
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: StorySub,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,-1,0,0,0,100,100,0,0,1,3.5,2,2,{margin_lr},{margin_lr},{margin_v},1
Style: StorySubBox,Arial,{font_size},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,-1,0,0,0,100,100,0,0,3,4,0,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

        events = []
        for seg in timings:
            dur = max(0.4, seg.end_sec - seg.start_sec)
            chunks = cls.split_text_into_sub_chunks(seg.text, max_words=max_words_per_chunk)
            chunk_dur = dur / len(chunks)

            char_color = speaker_colors.get(seg.character_type, "&H0038BDF8&")
            speaker_badge = ""
            if seg.speaker_name and seg.speaker_name not in ["Người dẫn chuyện", "Dẫn chuyện"]:
                speaker_badge = f"{{\\b1\\c{char_color}}}【{seg.speaker_name}】{{\\b0\\c&H00FFFFFF&}}\\N"

            for i, chunk in enumerate(chunks):
                c_start = seg.start_sec + i * chunk_dur
                c_end = c_start + chunk_dur
                
                # Sanitize ASS special characters
                safe_text = chunk.replace("{", "(").replace("}", ")").replace("\\", "/")
                ass_text = f"{speaker_badge}{safe_text}"

                start_str = cls.sec_to_ass_time(c_start)
                end_str = cls.sec_to_ass_time(c_end)
                events.append(f"Dialogue: 0,{start_str},{end_str},StorySub,,0,0,0,,{ass_text}")

        output_ass_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(ass_header + "\n".join(events) + "\n")

        logger.info(f"Generated {len(events)} synchronized subtitle cues at {output_ass_path}")
        return output_ass_path
