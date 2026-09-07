import os
import re
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Callable
from loguru import logger

from app.core.config import settings
from app.audio.tts_engine import TTSEngine

class StoryVideoRenderer:
    """Renders high-quality audiobook listening videos with AI artwork, waveforms, and synced subtitles."""

    @classmethod
    def _sync_render_audiobook_video(
        cls,
        story_id: int,
        title: str,
        author: str,
        audio_path: str,
        aspect_ratio: str = "16:9",
        bg_image_path: Optional[str] = None,
        subtitle_path: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> str:
        """Synchronous internal render worker called inside a dedicated thread with live progress."""
        output_dir = Path("media/output/stories")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_video_path = output_dir / f"story_{story_id}_{aspect_ratio.replace(':', 'x')}.mp4"

        work_dir = Path(f"media/working/stories/render_{story_id}")
        work_dir.mkdir(parents=True, exist_ok=True)

        ffmpeg_bin = settings.FFMPEG_PATH
        audio_full_path = Path(audio_path).resolve()

        # Probe duration
        duration = TTSEngine.get_audio_duration(str(audio_full_path))
        if duration <= 0:
            duration = 10.0

        # Resolution & layout settings
        if aspect_ratio == "9:16":
            width, height = 1080, 1920
            wave_h = 200
            wave_w = 900
            wave_x = "(W-w)/2"
            wave_y = "1420"
            title_size = 46
            author_size = 28
            title_y = int(height * 0.14)
            author_y = int(height * 0.20)
        else: # 16:9
            width, height = 1920, 1080
            wave_h = 160
            wave_w = 1600
            wave_x = "(W-w)/2"
            wave_y = "720"
            title_size = 52
            author_size = 30
            title_y = int(height * 0.12)
            author_y = int(height * 0.19)

        # Write UTF-8 text files for bulletproof drawtext rendering (no Windows CLI encoding issues)
        title_txt_path = work_dir / "title.txt"
        author_txt_path = work_dir / "author.txt"
        
        with open(title_txt_path, "w", encoding="utf-8") as f:
            f.write(title.strip() or "Truyện Ngắn")
            
        with open(author_txt_path, "w", encoding="utf-8") as f:
            f.write(f"Tác giả: {author.strip() or 'Khuyết danh'}")

        escaped_title_file = str(title_txt_path.resolve()).replace("\\", "/").replace(":", "\\:")
        escaped_author_file = str(author_txt_path.resolve()).replace("\\", "/").replace(":", "\\:")

        # Windows font path
        font_arg = ""
        for font_candidate in ["C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/tahoma.ttf"]:
            if os.path.exists(font_candidate):
                escaped_font = font_candidate.replace("\\", "/").replace(":", "\\:")
                font_arg = f":fontfile='{escaped_font}'"
                break

        # Check background image
        has_bg_image = False
        bg_image_full = None
        if bg_image_path:
            bg_path_obj = Path(bg_image_path)
            if bg_path_obj.exists() and os.path.getsize(bg_path_obj) > 1000:
                has_bg_image = True
                bg_image_full = bg_path_obj.resolve()

        # Check subtitle path
        has_subtitle = False
        escaped_sub_file = ""
        if subtitle_path:
            sub_path_obj = Path(subtitle_path)
            if sub_path_obj.exists() and os.path.getsize(sub_path_obj) > 10:
                has_subtitle = True
                escaped_sub_file = str(sub_path_obj.resolve()).replace("\\", "/").replace(":", "\\:")

        # Build filter complex
        filter_parts = []
        if has_bg_image:
            filter_parts.append(
                f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}, "
                f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.45:t=fill[bg]"
            )
        else:
            filter_parts.append(f"color=c=0x0b0f19:s={width}x{height}:r=15:d={duration + 0.5}[bg]")

        # Audio waveform
        filter_parts.append(
            f"[0:a]showwaves=s={wave_w}x{wave_h}:mode=line:colors=0x38bdf8|0xec4899:scale=cbrt,format=yuva420p[wave]"
        )
        filter_parts.append(f"[bg][wave]overlay={wave_x}:{wave_y}:format=auto[v_wave]")

        # Title & Author Header
        filter_parts.append(
            f"[v_wave]drawtext=textfile='{escaped_title_file}'{font_arg}:fontsize={title_size}:fontcolor=white:x=(w-text_w)/2:y={title_y}:shadowcolor=black@0.85:shadowx=3:shadowy=3, "
            f"drawtext=textfile='{escaped_author_file}'{font_arg}:fontsize={author_size}:fontcolor=0x94a3b8:x=(w-text_w)/2:y={author_y}:shadowcolor=black@0.7:shadowx=2:shadowy=2[v_header]"
        )

        # Burn Subtitles or Footer
        if has_subtitle:
            filter_parts.append(f"[v_header]ass='{escaped_sub_file}'[v_out]")
        else:
            filter_parts.append(
                f"[v_header]drawtext=text='AI Movie Content Factory - Audiobook'{font_arg}:fontsize=22:fontcolor=0x64748b:x=(w-text_w)/2:y={int(height*0.92)}[v_out]"
            )

        filter_complex = "; ".join(filter_parts)

        tmp_output_path = output_dir / f"story_{story_id}_{aspect_ratio.replace(':', 'x')}_tmp.mp4"

        cmd = [
            ffmpeg_bin,
            "-y",
            "-threads", "0",
            "-i", str(audio_full_path)
        ]

        if has_bg_image:
            cmd.extend(["-loop", "1", "-i", str(bg_image_full)])

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[v_out]",
            "-map", "0:a",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "22",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-t", str(duration),
            str(tmp_output_path)
        ])

        logger.info(f"Rendering Story Video #{story_id} (aspect={aspect_ratio}, bg={has_bg_image}, sub={has_subtitle}, dur={duration:.1f}s)...")
        if progress_callback:
            try:
                progress_callback(0.05, "Đang khởi tạo FFmpeg render video...")
            except Exception:
                pass

        proc_res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )

        # Clean up temporary text files
        try:
            if title_txt_path.exists():
                title_txt_path.unlink()
            if author_txt_path.exists():
                author_txt_path.unlink()
            if work_dir.exists():
                work_dir.rmdir()
        except Exception:
            pass

        if proc_res.returncode != 0:
            logger.warning(f"Primary render failed ({proc_res.stderr[:300] if proc_res.stderr else ''}). Trying fallback waveform...")
            if tmp_output_path.exists():
                tmp_output_path.unlink()
            fallback_filter = (
                f"color=c=0x1e1b4b:s={width}x{height}:r=15:d={duration + 0.5}[bg]; "
                f"[0:a]showwaves=s={wave_w}x{wave_h}:mode=line:colors=0xa855f7|0xec4899:scale=cbrt,format=yuva420p[wave]; "
                f"[bg][wave]overlay={wave_x}:{wave_y}[v_out]"
            )
            cmd_fallback = [
                ffmpeg_bin, "-y",
                "-threads", "0",
                "-i", str(audio_full_path),
                "-filter_complex", fallback_filter,
                "-map", "[v_out]",
                "-map", "0:a",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-c:a", "aac",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-t", str(duration),
                str(tmp_output_path)
            ]
            fb_res = subprocess.run(cmd_fallback, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
            if fb_res.returncode != 0:
                if tmp_output_path.exists():
                    tmp_output_path.unlink()
                raise RuntimeError(f"FFmpeg render error: {fb_res.stderr}")

        # Atomic replace to final output
        if tmp_output_path.exists():
            if output_video_path.exists():
                try:
                    output_video_path.unlink()
                except Exception:
                    pass
            tmp_output_path.rename(output_video_path)

        if progress_callback:
            try:
                progress_callback(1.0, "Hoàn tất render video!")
            except Exception:
                pass

        return str(output_video_path).replace("\\", "/")

    @classmethod
    async def render_audiobook_video(
        cls,
        story_id: int,
        title: str,
        author: str,
        audio_path: str,
        aspect_ratio: str = "16:9",
        bg_image_path: Optional[str] = None,
        subtitle_path: Optional[str] = None,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> str:
        """
        Asynchronously render audiobook listening video without blocking FastAPI event loop.
        """
        return await asyncio.to_thread(
            cls._sync_render_audiobook_video,
            story_id=story_id,
            title=title,
            author=author,
            audio_path=audio_path,
            aspect_ratio=aspect_ratio,
            bg_image_path=bg_image_path,
            subtitle_path=subtitle_path,
            progress_callback=progress_callback
        )
