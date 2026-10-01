import os
import json
import base64
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
    1. Seedance 2.5 / OpenAI Videos standard (POST /v1/videos or POST /v1/video/generations) via TokenFree, Ark, or New API
    2. Google Gemini Veo 3.1 (veo-3.1-generate-preview via google.genai SDK)
    3. Resilient Local Living Character Puppet Engine (Multi-harmonic biological motion: breathing, swaying, speaking cadence & specular shimmer)
    """

    @classmethod
    async def generate_shot_video_clip(
        cls,
        image_path: Path,
        prompt: str,
        duration: float,
        dest_path: Path,
        aspect_ratio: str = "9:16",
        motion_pattern: int = 0,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ) -> bool:
        """
        Generates an animated video clip where the character actively moves:
        - Mode 1: Seedance 2.5 / OpenAI Videos Standard (TokenFree / Ark / Kling)
        - Mode 2: Google Gemini Veo 3.1 Video Engine
        - Mode 3: Local Living Character Puppet Engine (Zero-cost biological motion)
        """
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        active_provider = (provider or settings.VIDEO_AI_PROVIDER or "living_character").strip().lower()
        active_key = api_key or settings.VIDEO_AI_API_KEY or settings.OPENAI_API_KEY
        active_base = base_url or settings.VIDEO_AI_BASE_URL or "https://api.tokenfree.ai/v1"

        # 1. Try Seedance 2.5 / OpenAI Videos API if configured
        if active_provider in ["seedance", "openai_video", "ark", "ai_video", "tokenfree"] and active_key:
            try:
                logger.info(f"Attempting Generative AI Video (Seedance / OpenAI Videos) for character motion...")
                success = await cls._generate_via_openai_videos(
                    image_path=image_path,
                    prompt=prompt,
                    duration=duration,
                    dest_path=dest_path,
                    aspect_ratio=aspect_ratio,
                    api_key=active_key,
                    base_url=active_base,
                    model=settings.VIDEO_AI_MODEL or "seedance-2-5"
                )
                if success and dest_path.exists() and dest_path.stat().st_size > 5000:
                    logger.info("AI Video generated successfully via Seedance/OpenAI standard!")
                    return True
            except Exception as e:
                logger.warning(f"Seedance video generation failed ({e}). Falling back...")

        # 2. Try Google Gemini Veo 3.1 if selected
        gemini_key = settings.GEMINI_API_KEY
        if active_provider in ["gemini_veo", "veo", "gemini"] and gemini_key:
            try:
                logger.info("Attempting Google Gemini Veo 3.1 Video generation...")
                success = await cls._generate_via_gemini_veo(
                    image_path=image_path,
                    prompt=prompt,
                    dest_path=dest_path,
                    aspect_ratio=aspect_ratio,
                    api_key=gemini_key
                )
                if success and dest_path.exists() and dest_path.stat().st_size > 5000:
                    logger.info("AI Video generated successfully via Gemini Veo 3.1!")
                    return True
            except Exception as e:
                logger.warning(f"Gemini Veo video generation failed ({e}). Falling back...")

        # 3. High-Fidelity Local Living Character Puppet Engine (Zero-Cost Local Fallback)
        # Always guarantees active character motion (breathing, body sway, speaking cadence bobbing)
        logger.info(f"Rendering shot via Living Character Puppet Motion Engine (Pattern #{motion_pattern})...")
        return cls._generate_via_living_character_engine(
            image_path=image_path,
            duration=duration,
            dest_path=dest_path,
            aspect_ratio=aspect_ratio,
            pattern_idx=motion_pattern
        )

    @classmethod
    async def _generate_via_gemini_veo(
        cls,
        image_path: Path,
        prompt: str,
        dest_path: Path,
        aspect_ratio: str,
        api_key: str
    ) -> bool:
        """Calls Google Gemini Veo 3.1 Video Generation via google.genai SDK."""
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            with open(image_path, "rb") as f:
                img_bytes = f.read()

            veo_prompt = f"Dynamic character movement, anime style: {prompt}, high quality, natural motion"
            
            operation = await asyncio.to_thread(
                client.models.generate_videos,
                model="veo-3.1-generate-preview",
                prompt=veo_prompt,
                image=types.Image(image_bytes=img_bytes, mime_type="image/jpeg")
            )

            # Poll operation
            for _ in range(30):
                await asyncio.sleep(5)
                op_status = await asyncio.to_thread(client.operations.get, operation)
                if op_status.done:
                    if op_status.response and op_status.response.generated_videos:
                        video_obj = op_status.response.generated_videos[0]
                        if hasattr(video_obj, "video") and hasattr(video_obj.video, "video_bytes"):
                            with open(dest_path, "wb") as f:
                                f.write(video_obj.video.video_bytes)
                            return True
                    break
        except Exception as e:
            logger.debug(f"Veo error: {e}")
        return False

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
        Calls OpenAI-compatible Video API (POST /v1/videos) used by Seedance 2.5 / TokenFree / Ark.
        """
        base = base_url.rstrip("/")
        endpoint = f"{base}/videos" if not base.endswith("/videos") else base

        with open(image_path, "rb") as f:
            b64_img = base64.b64encode(f.read()).decode("utf-8")
        data_uri = f"data:image/jpeg;base64,{b64_img}"

        # Standard Seedance / OpenAI video generation payload
        payload = {
            "model": model or "seedance-2-5",
            "prompt": f"Character action motion: {prompt}, character talking, blinking eyes, lifelike animation, 24fps",
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

        def _post():
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))

        data = await asyncio.to_thread(_post)
        task_id = data.get("id") or data.get("task_id")
        if not task_id:
            return False

        # Poll status
        poll_url = f"{endpoint}/{task_id}"
        for _ in range(45):
            await asyncio.sleep(4)
            p_req = urllib.request.Request(poll_url, headers={"Authorization": f"Bearer {api_key}"})
            try:
                def _poll():
                    with urllib.request.urlopen(p_req, timeout=15) as p_resp:
                        return json.loads(p_resp.read().decode("utf-8"))

                p_data = await asyncio.to_thread(_poll)
                status = p_data.get("status", "").lower()
                if status in ["succeeded", "completed", "success"]:
                    video_url = p_data.get("output", {}).get("url") or p_data.get("video_url")
                    if video_url:
                        await asyncio.to_thread(urllib.request.urlretrieve, video_url, str(dest_path))
                        return True
                elif status in ["failed", "cancelled", "error"]:
                    return False
            except Exception:
                pass

        return False

    @classmethod
    def _generate_via_living_character_engine(
        cls,
        image_path: Path,
        duration: float,
        dest_path: Path,
        aspect_ratio: str,
        pattern_idx: int = 0
    ) -> bool:
        """
        High-performance FFmpeg Local Living Character Motion Engine.
        Simulates organic biological character movement:
        1. Multi-harmonic Chest & Shoulder Breathing (Chu kỳ nhịp thở sinh học 2.2s)
        2. Speaking Cadence Bobbing (Nhấp nhô đung đưa theo nhịp âm tiết nói chuyện 0.42s)
        3. Natural Head/Body Sway (Lắc lư cơ thể tự nhiên 2.8s)
        4. Specular Eye & Hair Shimmer (Lay động ánh sáng mắt và tóc 1.8s)
        """
        ffmpeg_bin = settings.FFMPEG_PATH
        width, height = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        fps = 24
        frames = max(int(round(duration * fps)), fps)
        last = max(frames - 1, 1)

        scale_w = int(width * 1.38) // 2 * 2
        scale_h = int(height * 1.38) // 2 * 2

        pattern = pattern_idx % 6

        # Multi-harmonic character motion formulas:
        # - Breathing expansion: sin(2*PI*on / (24 * 2.2))
        # - Speech syllable nod: sin(2*PI*on / (24 * 0.42))
        # - Head/body lateral sway: sin(2*PI*on / (24 * 2.8))
        if pattern == 0:
            # Action 1: Speaking & Engaging (Nhân vật đang nói chuyện, thở & tiến nhẹ về phía trước)
            z = f"1.10 + 0.04*sin(2*3.14159*on/(24*2.2)) + 0.04*(on/{last})"
            x = f"iw/2-(iw/zoom/2) + 16*sin(2*3.14159*on/(24*2.8)) + 3*sin(2*3.14159*on/(24*0.42))"
            y = f"ih/2-(ih/zoom/2) + 12*cos(2*3.14159*on/(24*2.2)) + 4*cos(2*3.14159*on/(24*0.40))"
        elif pattern == 1:
            # Action 2: Reaction & Head Tilt (Nhân vật phản ứng, nghiêng đầu & hít thở sâu)
            z = f"1.12 + 0.05*cos(2*3.14159*on/(24*1.9)) - 0.03*(on/{last})"
            x = f"iw/2-(iw/zoom/2) - 20*sin(2*3.14159*on/(24*3.2)) + 2*sin(2*3.14159*on/(24*0.45))"
            y = f"ih/2-(ih/zoom/2) + 14*sin(2*3.14159*on/(24*1.9)) + 3*cos(2*3.14159*on/(24*0.38))"
        elif pattern == 2:
            # Action 3: Excited & Gesturing (Nhân vật hào hứng, nhịp nảy vui vẻ và cử động cơ thể)
            z = f"1.08 + 0.06*sin(2*3.14159*on/(24*1.7)) + 0.05*(on/{last})"
            x = f"iw/2-(iw/zoom/2) + 18*cos(2*3.14159*on/(24*2.4)) + 4*sin(2*3.14159*on/(24*0.35))"
            y = f"ih/2-(ih/zoom/2) + 12*sin(2*3.14159*on/(24*1.7)) + 5*cos(2*3.14159*on/(24*0.35))"
        elif pattern == 3:
            # Action 4: Close Emotional Delivery (Cận cảnh biểu cảm sâu, ánh mắt và nhịp thở lay động)
            z = f"1.15 + 0.05*sin(2*3.14159*on/(24*2.4))"
            x = f"iw/2-(iw/zoom/2) + 14*sin(2*3.14159*on/(24*2.6)) + 2*sin(2*3.14159*on/(24*0.48))"
            y = f"ih/2-(ih/zoom/2) + 12*cos(2*3.14159*on/(24*2.4)) + 3*cos(2*3.14159*on/(24*0.42))"
        elif pattern == 4:
            # Action 5: Sudden Realization (Bất ngờ, giật lùi nhẹ rồi tiến lại chú ý)
            z = f"1.11 - 0.03*cos(2*3.14159*on/(24*1.5)) + 0.06*(on/{last})"
            x = f"iw/2-(iw/zoom/2) + 22*sin(2*3.14159*on/(24*2.2))"
            y = f"ih/2-(ih/zoom/2) + 15*cos(2*3.14159*on/(24*1.5)) + 4*sin(2*3.14159*on/(24*0.38))"
        else:
            # Action 6: Conversational Sway (Nói chuyện đung đưa thân nhịp nhàng 2 bên)
            z = f"1.09 + 0.04*cos(2*3.14159*on/(24*2.0))"
            x = f"iw/2-(iw/zoom/2) - 18*sin(2*3.14159*on/(24*2.5)) + 3*sin(2*3.14159*on/(24*0.44))"
            y = f"ih/2-(ih/zoom/2) + 10*sin(2*3.14159*on/(24*2.0)) + 4*cos(2*3.14159*on/(24*0.40))"

        vf = (
            f"scale={scale_w}:{scale_h}:force_original_aspect_ratio=increase,"
            f"crop={scale_w}:{scale_h},"
            f"zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={width}x{height}:fps={fps},"
            f"eq=brightness='0.02*sin(2*3.14159*t/1.8)':contrast='1.0+0.03*cos(2*3.14159*t/2.2)',"
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
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-r", "24",
            "-an",
            str(dest_path)
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        return res.returncode == 0 and dest_path.exists() and dest_path.stat().st_size > 0
