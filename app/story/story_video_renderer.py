import os
import re
import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any, Tuple
from loguru import logger

from app.core.config import settings
from app.audio.tts_engine import TTSEngine

class StoryVideoRenderer:
    """
    Advanced video renderer for audiobooks and episodic story content.
    Features:
    - 2.5D Ken Burns Dynamic Pan & Zoom motion engine for still art
    - Tpad frame freeze (stop_mode=clone) to eliminate narration cutoffs
    - Multi-shot timeline composer with stream concatenation
    - Dual aspect ratio support (9:16 vertical shorts & 16:9 widescreen)
    - Anti-overflow typography, header vignettes, and synced ASS captions
    """

    @classmethod
    def _find_usable_font(cls) -> str:
        """Find a reliable font file on the host system with fallback."""
        candidates = [
            "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/tahoma.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
        ]
        for c in candidates:
            if os.path.exists(c):
                return c.replace("\\", "/")
        return ""

    @classmethod
    def build_ken_burns_filter(
        cls,
        width: int,
        height: int,
        duration: float,
        pattern_idx: int = 0,
        intensity: float = 0.16,
        fps: int = 24
    ) -> str:
        """
        Builds a dynamic 2.5D Ken Burns zoompan filter for static images.
        Cycles across 4 camera movement presets:
          0: Smooth push-in toward center
          1: Smooth pull-out with subtle upward drift
          2: Push-in with smooth rightward pan
          3: Push-in with smooth leftward pan and tilt
        """
        frames = max(int(round(duration * fps)), fps)
        last = max(frames - 1, 1)
        amp = max(0.08, min(float(intensity), 0.35))
        z_max = f"{1.0 + amp:.3f}"
        
        # Scale up canvas beforehand to avoid subpixel blur during zoom
        scale_w = int(width * 1.3) // 2 * 2
        scale_h = int(height * 1.3) // 2 * 2

        pattern = pattern_idx % 4
        if pattern == 0:
            # Push-in centered
            z = f"min(1.0+{amp}*on/{last},{z_max})"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif pattern == 1:
            # Pull-out with upward drift
            z = f"max({z_max}-{amp}*on/{last},1.0)"
            x = "iw/2-(iw/zoom/2)"
            y = f"ih/2-(ih/zoom/2)-ih*0.06*on/{last}"
        elif pattern == 2:
            # Push-in with pan right
            z = f"min(1.0+{amp}*on/{last},{z_max})"
            x = f"(iw-iw/zoom)*on/{last}"
            y = "ih/2-(ih/zoom/2)"
        else:
            # Push-in with pan left & slight tilt
            z = f"min(1.0+{amp}*on/{last},{z_max})"
            x = f"(iw-iw/zoom)*(1-on/{last})"
            y = f"(ih-ih/zoom)*0.3*on/{last}"

        return (
            f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
            f"crop={scale_w}:{scale_h},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
            f"format=yuv420p"
        )

    @classmethod
    def pad_or_trim_clip(
        cls,
        src: Path,
        dest: Path,
        target_duration: float,
        width: int,
        height: int,
        fps: int = 24
    ) -> bool:
        """
        Fits video clip to target duration.
        If shorter than narration: Freezes the last frame cleanly using tpad=stop_mode=clone.
        If longer: Trims cleanly to avoid overrun.
        """
        ffmpeg_bin = settings.FFMPEG_PATH
        target = max(float(target_duration), 0.5)
        
        # Probe source duration
        src_dur = TTSEngine.get_audio_duration(str(src)) or 0.0
        scale_pad = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=yuv420p"
        )
        base_vf = f"{scale_pad},setpts=PTS-STARTPTS,fps={fps}"

        if src_dur > 0.05 and src_dur + 0.1 < target:
            # Clip is shorter than narration: freeze last frame
            pad_dur = min(target - src_dur, 120.0)
            vf = f"{base_vf},tpad=stop_mode=clone:stop_duration={pad_dur:.3f},format=yuv420p"
        else:
            vf = f"{base_vf},format=yuv420p"

        cmd = [
            ffmpeg_bin, "-y",
            "-threads", "0",
            "-i", str(src),
            "-t", f"{target:.3f}",
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-an",
            str(dest)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0 and dest.exists() and dest.stat().st_size > 0

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
        motion_mode: str = "ken_burns",
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> str:
        """
        Synchronous internal render worker with Ken Burns dynamic motion,
        header vignettes, waveform visualization, and subtitles.
        """
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

        # Layout settings per aspect ratio
        if aspect_ratio == "9:16":
            width, height = 1080, 1920
            wave_h = 180
            wave_w = 880
            wave_x = "(W-w)/2"
            wave_y = "1420"
            title_size = 46
            author_size = 28
            title_y = int(height * 0.12)
            author_y = int(height * 0.17)
            top_bar_h = int(height * 0.23)
        else:  # 16:9
            width, height = 1920, 1080
            wave_h = 150
            wave_w = 1500
            wave_x = "(W-w)/2"
            wave_y = "720"
            title_size = 50
            author_size = 30
            title_y = int(height * 0.10)
            author_y = int(height * 0.16)
            top_bar_h = int(height * 0.22)

        # Write UTF-8 text files for text rendering
        title_txt_path = work_dir / "title.txt"
        author_txt_path = work_dir / "author.txt"
        
        with open(title_txt_path, "w", encoding="utf-8") as f:
            f.write(title.strip() or "Truyện Ngắn")
            
        with open(author_txt_path, "w", encoding="utf-8") as f:
            f.write(f"Tác giả: {author.strip() or 'Khuyết danh'}")

        escaped_title_file = str(title_txt_path.resolve()).replace("\\", "/").replace(":", "\\:")
        escaped_author_file = str(author_txt_path.resolve()).replace("\\", "/").replace(":", "\\:")

        # Font configuration
        font_path = cls._find_usable_font()
        font_arg = f":fontfile='{font_path.replace(':', chr(92) + ':')}'" if font_path else ""

        # Check background image
        has_bg_image = False
        bg_image_full = None
        if bg_image_path:
            bg_path_obj = Path(bg_image_path)
            if bg_path_obj.exists() and bg_path_obj.stat().st_size > 1000:
                has_bg_image = True
                bg_image_full = bg_path_obj.resolve()

        # Check subtitle path
        has_subtitle = False
        escaped_sub_file = ""
        if subtitle_path:
            sub_path_obj = Path(subtitle_path)
            if sub_path_obj.exists() and sub_path_obj.stat().st_size > 10:
                has_subtitle = True
                escaped_sub_file = str(sub_path_obj.resolve()).replace("\\", "/").replace(":", "\\:")

        # Build visual layers
        filter_parts = []
        use_ken_burns = has_bg_image and motion_mode == "ken_burns" and duration <= 900 # Safe up to 15 mins

        if use_ken_burns:
            # 2.5D Ken Burns zoompan movement
            kb_filter = cls.build_ken_burns_filter(
                width=width,
                height=height,
                duration=duration,
                pattern_idx=story_id % 4,
                intensity=0.15,
                fps=24
            )
            # Add dark dimming overlay over artwork so text & wave stand out
            filter_parts.append(f"[1:v]{kb_filter},drawbox=x=0:y=0:w=iw:h=ih:color=black@0.40:t=fill[bg]")
        elif has_bg_image:
            filter_parts.append(
                f"[1:v]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},"
                f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.45:t=fill[bg]"
            )
        else:
            filter_parts.append(f"color=c=0x0b0f19:s={width}x{height}:r=24:d={duration + 0.5}[bg]")

        # Audio waveform overlay
        filter_parts.append(
            f"[0:a]showwaves=s={wave_w}x{wave_h}:mode=line:colors=0x38bdf8|0xec4899:scale=cbrt,format=yuva420p[wave]"
        )
        filter_parts.append(f"[bg][wave]overlay={wave_x}:{wave_y}:format=auto[v_wave]")

        # Elegant Top Header Vignette Bar + Title & Author
        filter_parts.append(
            f"[v_wave]drawbox=x=0:y=0:w=iw:h={top_bar_h}:color=black@0.35:t=fill,"
            f"drawtext=textfile='{escaped_title_file}'{font_arg}:fontsize={title_size}:fontcolor=white:x=(w-text_w)/2:y={title_y}:shadowcolor=black@0.9:shadowx=3:shadowy=3,"
            f"drawtext=textfile='{escaped_author_file}'{font_arg}:fontsize={author_size}:fontcolor=0x94a3b8:x=(w-text_w)/2:y={author_y}:shadowcolor=black@0.8:shadowx=2:shadowy=2[v_header]"
        )

        # Burn Subtitles or Branding Footer
        if has_subtitle:
            filter_parts.append(f"[v_header]ass='{escaped_sub_file}'[v_out]")
        else:
            filter_parts.append(
                f"[v_header]drawtext=text='AI Movie Content Factory - Audiobook'{font_arg}:fontsize=22:fontcolor=0x64748b:x=(w-text_w)/2:y={int(height*0.93)}[v_out]"
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
            "-preset", "veryfast",
            "-crf", "21",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-t", str(duration),
            str(tmp_output_path)
        ])

        logger.info(
            f"Rendering Story Video #{story_id} (aspect={aspect_ratio}, motion={motion_mode}, "
            f"bg={has_bg_image}, sub={has_subtitle}, dur={duration:.1f}s)..."
        )
        if progress_callback:
            try:
                progress_callback(0.08, "Đang xử lý hiệu ứng chuyển động Ken Burns & âm thanh...")
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

        # Fallback if Ken Burns or complex filter fails
        if proc_res.returncode != 0:
            logger.warning(f"Primary motion render failed ({proc_res.stderr[:300] if proc_res.stderr else ''}). Executing safe fallback...")
            if tmp_output_path.exists():
                tmp_output_path.unlink()

            fallback_filter = (
                f"color=c=0x111827:s={width}x{height}:r=24:d={duration + 0.5}[bg]; "
                f"[0:a]showwaves=s={wave_w}x{wave_h}:mode=line:colors=0x38bdf8|0xec4899:scale=cbrt,format=yuva420p[wave]; "
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
        motion_mode: str = "ken_burns",
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
            motion_mode=motion_mode,
            progress_callback=progress_callback
        )

    @classmethod
    def _sync_compose_multi_shot_video(
        cls,
        story_id: int,
        shots: List[Dict[str, Any]],
        output_path: Path,
        aspect_ratio: str = "9:16",
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.20,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> str:
        """
        Composes a multi-scene episodic story video from individual shot elements.
        Each shot item schema:
          - 'image_path': Path to scene illustration
          - 'video_path': (Optional) Video clip path if generated via AI Video
          - 'duration': Duration in seconds
          - 'narration': Voiceover text
          - 'shot_no': Index number
        """
        if not shots:
            raise ValueError("No shots provided for multi-shot composition.")

        ffmpeg_bin = settings.FFMPEG_PATH
        width, height = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix=f"story_multi_{story_id}_") as tmp_dir_str:
            tmp_path = Path(tmp_dir_str)
            segment_paths: List[Path] = []
            total_shots = len(shots)

            for idx, shot in enumerate(shots):
                shot_no = shot.get("shot_no", idx + 1)
                duration = max(float(shot.get("duration", 4.0)), 0.8)
                img_p = Path(shot.get("image_path", "")) if shot.get("image_path") else None
                vid_p = Path(shot.get("video_path", "")) if shot.get("video_path") else None

                seg_dest = tmp_path / f"seg_{shot_no:03d}.mp4"

                if progress_callback:
                    pct = 0.10 + (idx / total_shots) * 0.70
                    progress_callback(pct, f"Dựng phân cảnh #{shot_no}/{total_shots}...")

                if vid_p and vid_p.exists() and vid_p.stat().st_size > 1000:
                    # Clip video: use tpad clone freeze if shorter than narration
                    cls.pad_or_trim_clip(vid_p, seg_dest, duration, width, height)
                elif img_p and img_p.exists() and img_p.stat().st_size > 1000:
                    # Static image: use dynamic Ken Burns motion engine
                    kb = cls.build_ken_burns_filter(width, height, duration, pattern_idx=idx, intensity=0.15)
                    cmd = [
                        ffmpeg_bin, "-y",
                        "-threads", "0",
                        "-loop", "1",
                        "-i", str(img_p.resolve()),
                        "-t", f"{duration:.3f}",
                        "-vf", kb,
                        "-c:v", "libx264",
                        "-preset", "veryfast",
                        "-crf", "20",
                        "-pix_fmt", "yuv420p",
                        "-r", "24",
                        "-an",
                        str(seg_dest)
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
                else:
                    # Fallback solid dark canvas
                    cmd = [
                        ffmpeg_bin, "-y",
                        "-f", "lavfi",
                        "-i", f"color=c=0x0b0f19:s={width}x{height}:r=24:d={duration:.3f}",
                        "-c:v", "libx264",
                        "-pix_fmt", "yuv420p",
                        "-an",
                        str(seg_dest)
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

                if seg_dest.exists() and seg_dest.stat().st_size > 0:
                    segment_paths.append(seg_dest)

            # Concatenate all normalized segments
            concat_txt = tmp_path / "concat.txt"
            concat_txt.write_text(
                "\n".join(f"file '{p.resolve().as_posix()}'" for p in segment_paths),
                encoding="utf-8"
            )
            merged_video = tmp_path / "merged.mp4"

            if progress_callback:
                progress_callback(0.85, "Đang ghép nối toàn bộ phân cảnh...")

            concat_cmd = [
                ffmpeg_bin, "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_txt),
                "-c", "copy",
                "-movflags", "+faststart",
                str(merged_video)
            ]
            subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

            # Move or mix with BGM if provided
            if bgm_path and os.path.exists(bgm_path):
                if progress_callback:
                    progress_callback(0.92, "Đang hòa âm nhạc nền BGM...")
                vol = max(0.05, min(float(bgm_volume), 0.5))
                mix_cmd = [
                    ffmpeg_bin, "-y",
                    "-i", str(merged_video),
                    "-stream_loop", "-1",
                    "-i", str(Path(bgm_path).resolve()),
                    "-filter_complex", f"[1:a]volume={vol:.3f}[bgm]",
                    "-map", "0:v:0",
                    "-map", "[bgm]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    "-movflags", "+faststart",
                    str(output_path)
                ]
                subprocess.run(mix_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
            else:
                if output_path.exists():
                    output_path.unlink()
                merged_video.rename(output_path)

        if progress_callback:
            progress_callback(1.0, "Hoàn tất dựng video phân cảnh!")

        return str(output_path).replace("\\", "/")

    @classmethod
    async def compose_multi_shot_video(
        cls,
        story_id: int,
        shots: List[Dict[str, Any]],
        output_path: Path,
        aspect_ratio: str = "9:16",
        bgm_path: Optional[str] = None,
        bgm_volume: float = 0.20,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> str:
        """Asynchronous wrapper for multi-shot video composition."""
        return await asyncio.to_thread(
            cls._sync_compose_multi_shot_video,
            story_id=story_id,
            shots=shots,
            output_path=output_path,
            aspect_ratio=aspect_ratio,
            bgm_path=bgm_path,
            bgm_volume=bgm_volume,
            progress_callback=progress_callback
        )
