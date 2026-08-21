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
        Returns: (output_audio_path, list of WordTimestamp, duration_seconds)
        """
        clean_text = text.strip()
        if not clean_text:
            clean_text = "Nội dung phim đang được cập nhật."

        Path(output_audio_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Try primary voice and fallbacks
        voices_to_try = [voice, "vi-VN-HoaiMyNeural", "vi-VN-NamMinhNeural"]
        success = False
        last_err = None

        for v in dict.fromkeys(voices_to_try):
            try:
                communicate = edge_tts.Communicate(clean_text, v, rate=rate, pitch=pitch)
                await communicate.save(output_audio_path)
                if os.path.exists(output_audio_path) and os.path.getsize(output_audio_path) > 0:
                    success = True
                    break
            except Exception as e:
                last_err = e
                logger.warning(f"Voice {v} failed: {e}. Trying fallback voice...")
                await asyncio.sleep(1.0)

        if not success:
            raise RuntimeError(f"Edge-TTS failed with all voices: {last_err}")

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
