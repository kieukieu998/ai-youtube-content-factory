import os
from pathlib import Path
from typing import List, Optional
from app.video.ffmpeg_service import FFmpegService
from app.audio.bgm_mixer import BGMMixer
from loguru import logger

class VideoEditorAgent:
    """Agent 8: Gọi FFmpeg tổng hợp video 9:16, mix BGM, phụ đề và bộ lọc chống trùng."""
    
    @staticmethod
    def render_episode_video(
        selected_clips: List[str],
        voice_audio_path: str,
        output_video_path: str,
        bgm_audio_path: Optional[str] = None,
        subtitle_ass_path: Optional[str] = None,
        enable_anti_shadowban: bool = True
    ) -> str:
        working_dir = Path(output_video_path).parent
        
        # 1. Concat selected clips
        concat_video_path = str(working_dir / "temp_concat.mp4")
        FFmpegService.concatenate_clips(selected_clips, concat_video_path)
        
        # 2. Mix BGM if provided
        final_audio_path = voice_audio_path
        if bgm_audio_path and os.path.exists(bgm_audio_path):
            mixed_audio_path = str(working_dir / "temp_mixed_audio.aac")
            try:
                BGMMixer.mix_voice_and_bgm(
                    voice_audio_path=voice_audio_path,
                    bgm_audio_path=bgm_audio_path,
                    output_audio_path=mixed_audio_path
                )
                final_audio_path = mixed_audio_path
            except Exception as e:
                logger.warning(f"BGM mixing skipped due to error: {e}. Falling back to clean voice.")

        # 3. Render final 9:16 video
        final_video = FFmpegService.render_vertical_video(
            video_input_path=concat_video_path,
            audio_input_path=final_audio_path,
            output_video_path=output_video_path,
            subtitle_ass_path=subtitle_ass_path,
            enable_anti_shadowban=enable_anti_shadowban
        )
        
        # Clean temp concat
        if os.path.exists(concat_video_path):
            try:
                os.remove(concat_video_path)
            except Exception:
                pass
                
        return final_video
