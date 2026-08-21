import os
from typing import Tuple, List
from app.audio.tts_engine import TTSEngine, WordTimestamp
from loguru import logger

class VoiceAgent:
    """Agent 6: Tạo giọng đọc AI (TTS), trích xuất mốc thời gian từng từ và kiểm tra âm thanh."""
    
    @staticmethod
    async def create_voiceover(
        text: str,
        output_audio_path: str,
        voice: str = "vi-VN-HoaiMyNeural",
        speed: float = 1.08
    ) -> Tuple[str, List[WordTimestamp], float]:
        rate_str = f"{int((speed - 1.0) * 100):+d}%"
        logger.info(f"Generating voiceover with voice={voice}, speed={speed} ({rate_str})")
        return await TTSEngine.generate_speech_with_timestamps(
            text=text,
            output_audio_path=output_audio_path,
            voice=voice,
            rate=rate_str
        )
