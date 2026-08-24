import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, Callable
from loguru import logger
from app.core.config import settings

class VideoTransformerService:
    """
    Engine to transform full-length videos for Anti-Copyright & Anti-Shadowban (1:1 Duration).
    Applies audio frequency shifts, EQ modifications, visual transformations, and metadata stripping.
    """

    @staticmethod
    def get_media_info(video_path: str) -> Dict[str, Any]:
        """Probe video duration, dimensions, and audio stream presence."""
        info = {
            "duration": 0.0,
            "width": 1920,
            "height": 1080,
            "has_audio": False,
            "audio_sample_rate": 44100
        }
        if not os.path.exists(video_path):
            return info

        try:
            # Check duration
            cmd_dur = [
                settings.FFPROBE_PATH, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ]
            res_dur = subprocess.run(cmd_dur, stdout=subprocess.PIPE, text=True, check=True)
            info["duration"] = float(res_dur.stdout.strip() or 0.0)
        except Exception:
            pass

        try:
            # Check video stream dimensions
            cmd_dim = [
                settings.FFPROBE_PATH, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                str(video_path)
            ]
            res_dim = subprocess.run(cmd_dim, stdout=subprocess.PIPE, text=True, check=True)
            dim_str = res_dim.stdout.strip()
            if "x" in dim_str:
                parts = dim_str.split("x")
                info["width"] = int(parts[0])
                info["height"] = int(parts[1])
        except Exception:
            pass

        try:
            # Check audio stream presence and sample rate
            cmd_aud = [
                settings.FFPROBE_PATH, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ]
            res_aud = subprocess.run(cmd_aud, stdout=subprocess.PIPE, text=True, check=True)
            aud_str = res_aud.stdout.strip()
            if aud_str:
                info["has_audio"] = True
                info["audio_sample_rate"] = int(aud_str)
        except Exception:
            pass

        return info

    @classmethod
    def transform_full_length_video(
        cls,
        input_video_path: str,
        output_video_path: str,
        aspect_ratio: str = "original",
        pitch_shift: float = 1.02,
        audio_volume: float = 1.0,
        enable_audio_eq: bool = True,
        enable_hflip: bool = False,
        enable_color_grading: bool = True,
        enable_micro_zoom: bool = True,
        start_time: Optional[float] = None,
        duration: Optional[float] = None,
        dubbed_audio_path: Optional[str] = None,
        dubbing_mode: str = "voiceover",
        subtitles_srt_path: Optional[str] = None,
        progress_callback: Optional[Callable[[float], None]] = None
    ) -> str:
        """
        Execute 1:1 full-length transformation or segmented part transformation with dynamic progress tracking
        and optional AI Dubbing audio mixing / subtitle overlay.
        """
        in_path = Path(input_video_path).resolve()
        out_path = Path(output_video_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not in_path.exists():
            raise FileNotFoundError(f"Input video not found: {in_path}")

        media_info = cls.get_media_info(str(in_path))
        orig_sr = media_info.get("audio_sample_rate", 44100)
        has_audio = media_info.get("has_audio", False)
        orig_dur = media_info.get("duration", 0.0)

        has_dubbed_audio = dubbed_audio_path and Path(dubbed_audio_path).exists()

        # 1. Build Video Filter Graph
        filter_complex_v = ""
        v_map = "[0:v]"

        if aspect_ratio == "blurred_stack_9_16":
            filter_complex_v = (
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=8:1,setsar=1[bg]; "
                "[0:v]scale=1080:-2,setsar=1[fg]; "
                "[bg][fg]overlay=(W-w)/2:(H-h)/2[v_base]"
            )
            v_map = "[v_base]"
        elif aspect_ratio == "center_crop_9_16":
            filter_complex_v = (
                "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v_base]"
            )
            v_map = "[v_base]"

        v_mods = []
        if enable_color_grading:
            v_mods.append("eq=contrast=1.03:brightness=0.01:saturation=1.05:gamma=1.02")

        if enable_micro_zoom:
            v_mods.append("crop=iw*0.98:ih*0.98,scale=iw:ih")

        if enable_hflip:
            v_mods.append("hflip")

        if v_mods:
            mod_str = ",".join(v_mods)
            if filter_complex_v:
                filter_complex_v += f"; {v_map}{mod_str}[v_final]"
            else:
                filter_complex_v = f"[0:v]{mod_str}[v_final]"
            v_map = "[v_final]"

        # Optional Subtitles Burning
        if subtitles_srt_path and Path(subtitles_srt_path).exists():
            clean_sub_path = str(Path(subtitles_srt_path).resolve()).replace("\\", "/").replace(":", "\\:")
            if clean_sub_path.endswith(".ass"):
                sub_filter = f"ass='{clean_sub_path}'"
            else:
                sub_style = "FontName=Arial,FontSize=12,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=1,Outline=1.8,Shadow=0.8,Alignment=2,MarginV=45"
                sub_filter = f"subtitles='{clean_sub_path}':force_style='{sub_style}'"

            if filter_complex_v:
                filter_complex_v += f"; {v_map}{sub_filter}[v_subbed]"
            else:
                filter_complex_v = f"[0:v]{sub_filter}[v_subbed]"
            v_map = "[v_subbed]"

        # 2. Build Audio Filter Graph
        filter_complex_a = ""
        a_map = "[0:a]"

        if has_dubbed_audio:
            # AI Dubbing Audio Mixing
            if has_audio and dubbing_mode == "voiceover":
                # Audio Ducking: Background audio at 18%, Dubbed voice at 120%
                filter_complex_a = (
                    "[0:a]volume=0.18,aformat=sample_rates=48000:channel_layouts=stereo[bg_duck]; "
                    "[1:a]volume=1.20,aformat=sample_rates=48000:channel_layouts=stereo[voice_dub]; "
                    "[bg_duck][voice_dub]amix=inputs=2:duration=first:dropout_transition=2[a_final]"
                )
            else:
                # Full replacement with dubbed voice
                filter_complex_a = "[1:a]volume=1.15,aformat=sample_rates=48000:channel_layouts=stereo[a_final]"
            a_map = "[a_final]"
        elif has_audio:
            a_chain = []
            if pitch_shift != 1.0:
                shifted_sr = int(orig_sr * pitch_shift)
                tempo_comp = 1.0 / pitch_shift
                a_chain.append(f"asetrate={shifted_sr},atempo={tempo_comp:.4f}")

            if enable_audio_eq:
                a_chain.append("equalizer=f=1000:t=q:w=1.2:g=2.0,equalizer=f=3500:t=q:w=1.2:g=-1.5")
            
            if audio_volume != 1.0:
                a_chain.append(f"volume={audio_volume:.2f}")

            a_chain.append("aformat=sample_rates=48000:channel_layouts=stereo")
            filter_complex_a = f"[0:a]{','.join(a_chain)}[a_final]"
            a_map = "[a_final]"

        # 3. Combine filter_complex
        if filter_complex_a and filter_complex_v:
            full_filter_complex = f"{filter_complex_v}; {filter_complex_a}"
        elif filter_complex_v:
            full_filter_complex = filter_complex_v
        elif filter_complex_a:
            full_filter_complex = filter_complex_a
        else:
            full_filter_complex = None

        # 4. Construct FFmpeg command
        cmd = [settings.FFMPEG_PATH, "-y"]

        if start_time is not None and start_time > 0:
            cmd.extend(["-ss", f"{start_time:.2f}"])
        if duration is not None and duration > 0:
            cmd.extend(["-t", f"{duration:.2f}"])

        cmd.extend(["-i", str(in_path)])

        if has_dubbed_audio:
            if start_time is not None and start_time > 0:
                cmd.extend(["-ss", f"{start_time:.2f}"])
            if duration is not None and duration > 0:
                cmd.extend(["-t", f"{duration:.2f}"])
            cmd.extend(["-i", str(dubbed_audio_path)])

        if full_filter_complex:
            cmd.extend(["-filter_complex", full_filter_complex])
            cmd.extend(["-map", v_map])
            if has_audio:
                cmd.extend(["-map", a_map])

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-map_metadata", "-1"
        ])

        if has_audio:
            cmd.extend([
                "-c:a", "aac",
                "-b:a", "192k"
            ])

        cmd.extend(["-progress", "pipe:1", "-nostats"])
        cmd.append(str(out_path))

        logger.info(f"Starting 1:1 Full-Length Video Transformation: {in_path.name} -> {out_path.name}")
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        # Run with live progress stream
        total_duration = duration if (duration and duration > 0) else (orig_dur if orig_dur > 0 else 1.0)

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace"
        )

        last_reported_pct = 0.0
        stdout_lines = []
        if process.stdout:
            for line in process.stdout:
                stdout_lines.append(line)
                stripped = line.strip()
                if stripped.startswith("out_time_us="):
                    try:
                        us_str = stripped.split("=")[1].strip()
                        if us_str.isdigit():
                            curr_sec = int(us_str) / 1_000_000.0
                            pct = min(1.0, curr_sec / total_duration)
                            if pct - last_reported_pct >= 0.02:
                                last_reported_pct = pct
                                if progress_callback:
                                    progress_callback(pct)
                    except Exception:
                        pass
                elif stripped == "progress=end":
                    if progress_callback:
                        progress_callback(1.0)

        process.wait()
        if process.returncode != 0:
            err_msg = "".join(stdout_lines[-30:])
            logger.error(f"FFmpeg transform failed with code {process.returncode}: {err_msg}")
            raise RuntimeError(f"FFmpeg error code: {process.returncode}")

        logger.info(f"Video Transformation completed successfully: {out_path}")
        return str(out_path)
