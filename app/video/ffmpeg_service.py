import os
import subprocess
from pathlib import Path
from typing import List, Optional
from loguru import logger
from app.core.config import settings

class FFmpegService:
    """Comprehensive FFmpeg Video Rendering Service for TikTok 9:16 vertical videos."""
    
    @staticmethod
    def render_vertical_video(
        video_input_path: str,
        audio_input_path: str,
        output_video_path: str,
        subtitle_ass_path: Optional[str] = None,
        enable_anti_shadowban: bool = True,
        preset_mode: str = "blurred_stack" # blurred_stack or center_crop
    ) -> str:
        """
        Render vertical 9:16 (1080x1920) video with blurred background stack, audio, and optional subtitles.
        """
        ffmpeg_bin = settings.FFMPEG_PATH
        
        # Escape path for windows subtitle filter
        sub_filter = ""
        if preset_mode == "blurred_stack":
            # Fast blurred background stack filter graph
            filter_complex = (
                f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=8:1,setsar=1[bg]; "
                f"[0:v]scale=1080:-2,setsar=1[fg]; "
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
            )
        else:
            filter_complex = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1"

        if subtitle_ass_path and Path(subtitle_ass_path).exists():
            ass_escaped = str(Path(subtitle_ass_path).resolve()).replace("\\", "/").replace(":", "\\:")
            filter_complex += f",ass='{ass_escaped}'[v_out]"
        else:
            filter_complex += "[v_out]"

        if enable_anti_shadowban:
            # Slight color grading and micro-zoom
            filter_complex += "; [v_out]eq=contrast=1.02:brightness=0.01:saturation=1.04[v_final]"
            v_map = "[v_final]"
        else:
            v_map = "[v_out]"

        # Check if video_input_path has an audio stream
        has_source_audio = False
        a_map = "1:a"
        try:
            probe_cmd = [
                settings.FFPROBE_PATH, "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_name",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_input_path)
            ]
            probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, text=True)
            if probe_res.stdout.strip():
                has_source_audio = True
        except Exception:
            pass

        if has_source_audio:
            # Mix voice/BGM with original film SFX (ends when voice ends)
            filter_complex += "; [0:a]volume=0.15,lowpass=f=3500[orig_sfx]; [1:a][orig_sfx]amix=inputs=2:duration=shortest[a_final]"
            a_map = "[a_final]"
        # Get precise audio duration
        audio_duration = 30.0
        try:
            probe_dur_cmd = [
                settings.FFPROBE_PATH, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_input_path)
            ]
            dur_res = subprocess.run(probe_dur_cmd, stdout=subprocess.PIPE, text=True)
            if dur_res.stdout.strip():
                audio_duration = float(dur_res.stdout.strip())
        except Exception:
            pass

        cmd = [
            ffmpeg_bin,
            "-y",
            "-stream_loop", "-1", # Loop video if shorter than audio
            "-i", str(video_input_path),
            "-i", str(audio_input_path),
            "-filter_complex", filter_complex,
            "-map", v_map,
            "-map", a_map,
            "-t", f"{audio_duration:.2f}", # Exact duration capping
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "192k",
            "-ar", "48000",
            "-ac", "2",
            "-shortest",
            str(output_video_path)
        ]

        logger.info(f"Executing FFmpeg render: {' '.join(cmd)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg Render failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg Render error: {result.stderr}")

        return output_video_path

    @staticmethod
    def concatenate_clips(
        clip_paths: List[str],
        output_concat_path: str
    ) -> str:
        """Concatenate multiple scene clips into one continuous video."""
        ffmpeg_bin = settings.FFMPEG_PATH
        list_file_path = Path(output_concat_path).parent / "concat_list.txt"
        
        with open(list_file_path, "w", encoding="utf-8") as f:
            for clip in clip_paths:
                escaped = str(Path(clip).resolve()).replace("\\", "/")
                f.write(f"file '{escaped}'\n")
                
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file_path),
            "-c", "copy",
            str(output_concat_path)
        ]
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg Concatenation failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg Concat error: {result.stderr}")
            
        try:
            if list_file_path.exists():
                list_file_path.unlink()
        except Exception:
            pass
            
        return output_concat_path
