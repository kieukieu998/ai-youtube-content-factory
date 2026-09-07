import subprocess
from pathlib import Path
from typing import Optional
from loguru import logger
from app.core.config import settings

class BGMMixer:
    """Audio Ducking and Background Music Mixer via FFmpeg."""
    
    @staticmethod
    def mix_voice_and_bgm(
        voice_audio_path: str,
        bgm_audio_path: str,
        output_audio_path: str,
        ducking_ratio: float = 5.0,
        ducking_threshold: float = 0.1,
        bgm_base_volume: float = 0.35
    ) -> str:
        """
        Mix voiceover with background music using sidechaincompress (Audio Ducking).
        BGM automatically lowers when voiceover speaks.
        """
        ffmpeg_bin = settings.FFMPEG_PATH
        
        filter_complex = (
            f"[1:a]volume={bgm_base_volume}[bgm_base]; "
            f"[bgm_base][0:a]sidechaincompress=threshold={ducking_threshold}:ratio={ducking_ratio}:attack=100:release=500[bgm_ducked]; "
            f"[0:a][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=2[a_out]"
        )
        
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", str(voice_audio_path),
            "-i", str(bgm_audio_path),
            "-filter_complex", filter_complex,
            "-map", "[a_out]",
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            "-ar", "44100",
            str(output_audio_path)
        ]
        
        logger.info(f"Mixing voice & BGM: {' '.join(cmd)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        if result.returncode != 0:
            logger.error(f"FFmpeg Audio Ducking failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg Audio Ducking error: {result.stderr}")
            
        return output_audio_path
