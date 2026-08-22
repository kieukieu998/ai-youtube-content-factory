import os
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Tuple
import edge_tts
from pydantic import BaseModel
from loguru import logger
from app.core.config import settings

class WordTimestamp(BaseModel):
    word: str
    start_ms: int
    end_ms: int

class TTSEngine:
    """Async Text-to-Speech Engine using Edge-TTS with resilient fallback and accurate duration."""
    
    SUPPORTED_VOICES = {
        "vi-VN-HoaiMyNeural": "Nữ miền Bắc (Truyền cảm)",
        "vi-VN-NamMinhNeural": "Nam miền Bắc (Trầm ấm)"
    }
    
    @staticmethod
    def get_audio_duration(audio_file_path: str) -> float:
        """Extract exact duration in seconds using ffprobe."""
        ffprobe_bin = settings.FFPROBE_PATH
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_file_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return float(res.stdout.strip())
        except Exception as e:
            logger.warning(f"Could not get audio duration via ffprobe: {e}")
            # Fallback estimation: file size based
            if os.path.exists(audio_file_path):
                size_kb = os.path.getsize(audio_file_path) / 1024
                return max(1.0, size_kb / 16.0) # ~16KB/s for 128kbps mp3
            return 5.0

    @staticmethod
    def _split_text_into_chunks(text: str, max_chars: int = 1200) -> List[str]:
        """Split long narrative into sentence-aligned chunks for reliable Edge-TTS streaming."""
        paragraphs = text.split("\n")
        chunks = []
        current_chunk = []
        current_len = 0

        for p in paragraphs:
            p = p.strip()
            if not p:
                continue
            sentences = [s.strip() for s in p.replace("? ", "?|").replace("! ", "!|").replace(". ", ".|").split("|") if s.strip()]
            for s in sentences:
                if current_len + len(s) + 1 > max_chars and current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = [s]
                    current_len = len(s)
                else:
                    current_chunk.append(s)
                    current_len += len(s) + 1

        if current_chunk:
            chunks.append(" ".join(current_chunk))
        return chunks if chunks else [text]

    @classmethod
    async def generate_speech_with_timestamps(
        cls,
        text: str,
        output_audio_path: str,
        voice: str = "vi-VN-HoaiMyNeural",
        rate: str = "+0%",
        pitch: str = "+0Hz"
    ) -> Tuple[str, List[WordTimestamp], float]:
        """
        Generate audio mp3 and calculate word-level timestamps.
        Supports seamless chunking for large 10-20 minute narrations.
        """
        clean_text = text.strip()
        if not clean_text:
            clean_text = "Nội dung phim đang được cập nhật."

        out_path = Path(output_audio_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        
        chunks = cls._split_text_into_chunks(clean_text, max_chars=1200)
        temp_chunk_files = []

        try:
            for idx, chunk in enumerate(chunks):
                chunk_file = str(out_path.parent / f"tts_chunk_{idx}_{out_path.name}")
                voices_to_try = [voice, "vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"]
                success = False
                last_err = None

                for v in dict.fromkeys(voices_to_try):
                    try:
                        communicate = edge_tts.Communicate(chunk, v, rate=rate, pitch=pitch)
                        await communicate.save(chunk_file)
                        if os.path.exists(chunk_file) and os.path.getsize(chunk_file) > 0:
                            success = True
                            temp_chunk_files.append(chunk_file)
                            break
                    except Exception as e:
                        last_err = e
                        logger.warning(f"Voice {v} on chunk {idx} failed: {e}")
                        await asyncio.sleep(0.5)

                if not success:
                    raise RuntimeError(f"Edge-TTS failed on chunk {idx}: {last_err}")

            # Concatenate chunks into final output file
            with open(output_audio_path, "wb") as outfile:
                for c_file in temp_chunk_files:
                    with open(c_file, "rb") as infile:
                        outfile.write(infile.read())

        finally:
            # Clean up temporary chunk files
            for c_file in temp_chunk_files:
                try:
                    if os.path.exists(c_file) and c_file != output_audio_path:
                        os.remove(c_file)
                except Exception:
                    pass

        # Get exact duration of generated audio
        duration_seconds = cls.get_audio_duration(output_audio_path)
        total_duration_ms = int(duration_seconds * 1000)

        # Generate smooth word timestamps
        words_list = clean_text.split()
        word_count = len(words_list)
        words: List[WordTimestamp] = []

        if word_count > 0:
            ms_per_word = max(100, total_duration_ms // word_count)
            current_ms = 0
            for w in words_list:
                start_ms = current_ms
                end_ms = min(total_duration_ms, current_ms + ms_per_word)
                words.append(WordTimestamp(word=w, start_ms=start_ms, end_ms=end_ms))
                current_ms = end_ms

        logger.info(f"Generated TTS audio: {output_audio_path} (Duration: {duration_seconds:.2f}s, Words: {len(words)})")
        return output_audio_path, words, duration_seconds
