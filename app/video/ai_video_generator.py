import os
import json
import asyncio
import urllib.request
import urllib.parse
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from loguru import logger

from app.core.config import settings

class AIVideoGenerator:
    """
    Video Generative AI Engine supporting:
    1. Seedance 2.5 / OpenAI Videos standard (POST /v1/videos) via TokenFree, Ark, or New API
    2. Pollinations AI Video (free tier generative video)
    3. Resilient 2.5D FFmpeg Dynamic Motion Engine (Zero-cost local fallback)
    """

    @classmethod
    async def generate_shot_video_clip(
        cls,
        image_path: Path,
        prompt: str,
        duration: float,
        dest_path: Path,
        aspect_ratio: str = "9:16",
        motion_pattern: int = 0
    ) -> bool:
        """
        Generates an animated video clip from a character/scene image and prompt.
        """
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        provider = (settings.VIDEO_AI_PROVIDER or "motion_engine").strip().lower()
        api_key = settings.VIDEO_AI_API_KEY or settings.OPENAI_API_KEY

        # 1. Try Seedance / OpenAI Videos API if configured
        if provider in ["seedance", "openai_video", "ark"] and api_key:
            try:
                logger.info(f"Attempting Seedance 2.5 / OpenAI Video generation for shot...")
                success = await cls._generate_via_openai_videos(
                    image_path=image_path,
                    prompt=prompt,
                    duration=duration,
                    dest_path=dest_path,
                    aspect_ratio=aspect_ratio,
                    api_key=api_key,
                    base_url=settings.VIDEO_AI_BASE_URL,
                    model=settings.VIDEO_AI_MODEL
                )
                if success and dest_path.exists() and dest_path.stat().st_size > 5000:
                    return True
            except Exception as e:
                logger.warning(f"Seedance video generation failed ({e}). Falling back to Motion Engine...")

        # 2. Try Pollinations Video if requested
        if provider == "pollinations":
            try:
                success = await cls._generate_via_pollinations(
                    prompt=prompt,
                    duration=duration,
                    dest_path=dest_path,
                    aspect_ratio=aspect_ratio
                )
                if success and dest_path.exists() and dest_path.stat().st_size > 5000:
                    return True
            except Exception as e:
                logger.warning(f"Pollinations video generation failed ({e}). Falling back to Motion Engine...")

        # 3. Default: High-performance 2.5D Dynamic Motion Simulator Engine
        return cls._generate_via_motion_engine(
            image_path=image_path,
            duration=duration,
            dest_path=dest_path,
            aspect_ratio=aspect_ratio,
            pattern_idx=motion_pattern
        )

    @classmethod
    async def _generate_via_openai_videos(
        cls,
        image_path: Path,
        prompt: str,
        duration: float,
        dest_path: Path,
        aspect_ratio: str,
        api_key: str,
        base_url: str,
        model: str
    ) -> bool:
        """
        Calls OpenAI-compatible Video API (POST /v1/videos) used by Seedance 2.5 / TokenFree.
        """
        import base64
        endpoint = f"{base_url.rstrip('/')}/videos"
        
        # Read image to base64
        with open(image_path, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")
        data_uri = f"data:image/jpeg;base64,{b64_img}"

        payload = {
            "model": model or "seedance-2-5",
            "prompt": prompt,
            "image": data_uri,
            "duration": int(max(4, min(duration, 10))),
            "ratio": aspect_ratio
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
        )

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            return False

        # Poll status
        poll_url = f"{endpoint}/{task_id}"
        for _ in range(40):
            await asyncio.sleep(4)
            p_req = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {api_key}"})
            try:
                with urllib.request.urlopen(p_req, timeout=15) as p_resp:
                    p_data = json.loads(p_resp.read().decode("utf-8"))
                status = p_data.get("status", "").lower()
                if status in ["succeeded", "completed", "success"]:
                    video_url = p_data.get("output", {}).get("url") or p_data.get("video_url")
                    if video_url:
                        urllib.request.urlretrieve(video_url, str(dest_path))
                        return True
                elif status in ["failed", "cancelled", "error"]:
                    return False
            except Exception:
                pass

        return False

    @classmethod
    async def _generate_via_pollinations(
        cls,
        prompt: str,
        duration: float,
        dest_path: Path,
        aspect_ratio: str
    ) -> bool:
        """Fetch generative video from Pollinations AI."""
        encoded_prompt = urllib.parse.quote(prompt)
        w, h = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={w}&height={h}&model=video"

        def _fetch():
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=45) as resp:
                if resp.status == 200:
                    with open(dest_path, "wb") as f:
                        f.write(resp.read())
                    return True
            return False

        return await asyncio.to_thread(_fetch)

    @classmethod
    def _generate_via_motion_engine(
        cls,
        image_path: Path,
        duration: float,
        dest_path: Path,
        aspect_ratio: str,
        pattern_idx: int = 0
    ) -> bool:
        """
        High-performance FFmpeg 2.5D Dynamic Motion Engine.
        Creates fluid camera pan and zoom focusing on character actions.
        """
        ffmpeg_bin = settings.FFMPEG_PATH
        width, height = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        fps = 24
        frames = max(int(round(duration * fps)), fps)
        last = max(frames - 1, 1)

        scale_w = int(width * 1.35) // 2 * 2
        scale_h = int(height * 1.35) // 2 * 2
        amp = 0.22
        z_max = f"{1.0 + amp:.3f}"

        pattern = pattern_idx % 4
        if pattern == 0:
            # Push-in onto character focus
            z = f"min(1.0+{amp}*on/{last},{z_max})"
            x = "iw/2-(iw/zoom/2)"
            y = "ih/2-(ih/zoom/2)"
        elif pattern == 1:
            # Pull-out with upward drift
            z = f"max({z_max}-{amp}*on/{last},1.0)"
            x = "iw/2-(iw/zoom/2)"
            y = f"ih/2-(ih/zoom/2)-ih*0.08*on/{last}"
        elif pattern == 2:
            # Push-in with pan right
            z = f"min(1.0+{amp}*on/{last},{z_max})"
            x = f"(iw-iw/zoom)*on/{last}"
            y = "ih/2-(ih/zoom/2)"
        else:
            # Push-in with pan left
            z = f"min(1.0+{amp}*on/{last},{z_max})"
            x = f"(iw-iw/zoom)*(1-on/{last})"
            y = f"(ih-ih/zoom)*0.3*on/{last}"

        vf = (
            f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
            f"crop={scale_w}:{scale_h},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
            f"format=yuv420p"
        )

        cmd = [
            ffmpeg_bin, "-y",
            "-threads", "0",
            "-loop", "1",
            "-i", str(image_path.resolve()),
            "-t", f"{duration:.3f}",
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-r", "24",
            "-an",
            str(dest_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 0
