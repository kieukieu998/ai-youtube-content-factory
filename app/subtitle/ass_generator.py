import os
from pathlib import Path
from typing import List
from app.audio.tts_engine import WordTimestamp

class SubtitleGenerator:
    """Generates standard SRT and Kinetic ASS (Word-by-word Highlight) Subtitles."""
    
    @staticmethod
    def ms_to_ass_time(ms: int) -> str:
        """Convert milliseconds to ASS timestamp: H:MM:SS.cs"""
        hours = ms // 3600000
        ms %= 3600000
        minutes = ms // 60000
        ms %= 60000
        seconds = ms // 1000
        cs = (ms % 1000) // 10
        return f"{hours}:{minutes:02d}:{seconds:02d}.{cs:02d}"

    @staticmethod
    def ms_to_srt_time(ms: int) -> str:
        """Convert milliseconds to SRT timestamp: HH:MM:SS,mmm"""
        hours = ms // 3600000
        ms %= 3600000
        minutes = ms // 60000
        ms %= 60000
        seconds = ms // 1000
        millis = ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    @classmethod
    def generate_kinetic_ass(
        cls,
        words: List[WordTimestamp],
        output_ass_path: str,
        words_per_line: int = 4
    ) -> str:
        """
        Generate ASS subtitle with word-level highlight animation (TikTok style).
        """
        ass_header = """[Script Info]
Title: TikTok Kinetic Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: TikTokDefault,Arial,80,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,6,3,2,60,60,350,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        # Group words into chunks
        chunks = []
        for i in range(0, len(words), words_per_line):
            chunk = words[i:i + words_per_line]
            chunks.append(chunk)

        dialogue_lines = []
        for chunk in chunks:
            if not chunk:
                continue
            chunk_start = chunk[0].start_ms
            chunk_end = chunk[-1].end_ms
            
            # Karaoke / Kinetic effect for each word in chunk
            # {\k<duration_in_centiseconds>}word
            line_text = ""
            for w in chunk:
                dur_cs = max(1, (w.end_ms - w.start_ms) // 10)
                # \\kf is progressive fill effect, \\k is simple jump
                line_text += f"{{\\kf{dur_cs}}}{w.word} "
            
            start_str = cls.ms_to_ass_time(chunk_start)
            end_str = cls.ms_to_ass_time(chunk_end)
            dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},TikTokDefault,,0,0,0,,{line_text.strip()}")

        full_ass_content = ass_header + "\n".join(dialogue_lines) + "\n"
        
        with open(output_ass_path, "w", encoding="utf-8") as f:
            f.write(full_ass_content)
            
        return output_ass_path

    @classmethod
    def generate_srt(
        cls,
        words: List[WordTimestamp],
        output_srt_path: str,
        words_per_line: int = 5
    ) -> str:
        """Generate standard SRT file."""
        chunks = []
        for i in range(0, len(words), words_per_line):
            chunk = words[i:i + words_per_line]
            chunks.append(chunk)

        srt_lines = []
        for idx, chunk in enumerate(chunks, 1):
            if not chunk:
                continue
            chunk_start = chunk[0].start_ms
            chunk_end = chunk[-1].end_ms
            text = " ".join(w.word for w in chunk)
            
            start_str = cls.ms_to_srt_time(chunk_start)
            end_str = cls.ms_to_srt_time(chunk_end)
            
            srt_lines.append(f"{idx}\n{start_str} --> {end_str}\n{text}\n")

        with open(output_srt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(srt_lines))

        return output_srt_path
