import os
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any
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
            cmd_v = [
                settings.FFPROBE_PATH, "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=s=x:p=0",
                str(video_path)
            ]
            res_v = subprocess.run(cmd_v, stdout=subprocess.PIPE, text=True, check=True)
            dims = res_v.stdout.strip().split("x")
            if len(dims) == 2:
                info["width"] = int(dims[0])
                info["height"] = int(dims[1])
        except Exception:
            pass

        try:
            # Check audio stream
            cmd_a = [
                settings.FFPROBE_PATH, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(video_path)
            ]
            res_a = subprocess.run(cmd_a, stdout=subprocess.PIPE, text=True, check=True)
            if res_a.stdout.strip():
                info["has_audio"] = True
                info["audio_sample_rate"] = int(res_a.stdout.strip())
        except Exception:
            pass

        return info

    @staticmethod
    def transform_full_length_video(
        input_video_path: str,
        output_video_path: str,
        aspect_ratio: str = "original", # "original", "blurred_stack_9_16", "center_crop_9_16"
        pitch_shift: float = 1.02, # 1.0 = normal, 1.02 = +2% pitch, 0.98 = -2% pitch
        enable_audio_eq: bool = True,
        enable_hflip: bool = False,
        enable_color_grading: bool = True,
        enable_micro_zoom: bool = True,
        audio_volume: float = 1.0
    ) -> str:
        """
        Processes and re-encodes a full-length video (1:1 duration preserved).
        Returns the absolute path to the output video.
        """
        in_path = Path(input_video_path).resolve()
        out_path = Path(output_video_path).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if not in_path.exists():
            raise FileNotFoundError(f"Input video not found: {in_path}")

        media_info = VideoTransformerService.get_media_info(str(in_path))
        has_audio = media_info.get("has_audio", False)
        orig_sr = media_info.get("audio_sample_rate", 44100)

        # 1. Build Video Filter Graph
        v_filters = []

        if aspect_ratio == "blurred_stack_9_16":
            filter_complex_v = (
                f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=8:1,setsar=1[bg]; "
                f"[0:v]scale=1080:-2,setsar=1[fg]; "
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v_base]"
            )
            v_current = "[v_base]"
        elif aspect_ratio == "center_crop_9_16":
            filter_complex_v = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v_base]"
            v_current = "[v_base]"
        else:
            # Original aspect ratio (ensure even dimensions for H.264)
            filter_complex_v = "[0:v]scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1[v_base]"
            v_current = "[v_base]"

        v_chain = []
        if enable_hflip:
            v_chain.append("hflip")
        if enable_color_grading:
            # Shift contrast, brightness, saturation, gamma by 2-4%
            v_chain.append("eq=contrast=1.03:brightness=0.01:saturation=1.05:gamma=1.02")
        if enable_micro_zoom:
            # 102% micro-zoom
            v_chain.append("crop=iw*0.98:ih*0.98,scale=iw:ih")

        if v_chain:
            combined_v_chain = ",".join(v_chain)
            filter_complex_v += f"; {v_current}{combined_v_chain}[v_final]"
            v_map = "[v_final]"
        else:
            v_map = v_current

        # 2. Build Audio Filter Graph (if audio exists)
        filter_complex_a = ""
        a_map = "0:a"
        if has_audio:
            a_chain = []
            
            # Pitch shift without changing duration (via asetrate + atempo)
            if abs(pitch_shift - 1.0) > 0.001:
                shifted_sr = int(orig_sr * pitch_shift)
                tempo_comp = 1.0 / pitch_shift
                a_chain.append(f"asetrate={shifted_sr},atempo={tempo_comp:.4f}")
            
            if enable_audio_eq:
                # Displace spectral frequencies (equalizer curve)
                a_chain.append("equalizer=f=1000:t=q:w=1.2:g=2.0,equalizer=f=3500:t=q:w=1.2:g=-1.5")
            
            if audio_volume != 1.0:
                a_chain.append(f"volume={audio_volume:.2f}")

            # Re-sample to standard studio 48kHz stereo
            a_chain.append("aformat=sample_rates=48000:channel_layouts=stereo")

            filter_complex_a = f"[0:a]{','.join(a_chain)}[a_final]"
            a_map = "[a_final]"

        # 3. Combine filter_complex
        if filter_complex_a:
            full_filter_complex = f"{filter_complex_v}; {filter_complex_a}"
        else:
            full_filter_complex = filter_complex_v

        # 4. Construct FFmpeg command
        cmd = [
            settings.FFMPEG_PATH, "-y",
            "-i", str(in_path),
            "-filter_complex", full_filter_complex,
            "-map", v_map
        ]

        if has_audio:
            cmd.extend(["-map", a_map])

        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-map_metadata", "-1" # Strip all previous metadata
        ])

        if has_audio:
            cmd.extend([
                "-c:a", "aac",
                "-b:a", "192k"
            ])

        cmd.append(str(out_path))

        logger.info(f"Starting 1:1 Full-Length Video Transformation: {in_path.name} -> {out_path.name}")
        logger.debug(f"FFmpeg command: {' '.join(cmd)}")

        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"FFmpeg transform failed: {result.stderr}")
            raise RuntimeError(f"FFmpeg error: {result.stderr[-400:]}")

        logger.info(f"Video Transformation completed successfully: {out_path}")
        return str(out_path)
