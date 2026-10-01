import os
import urllib.parse
import urllib.request
import asyncio
from pathlib import Path
from typing import Optional, List, Dict, Any
from PIL import Image, ImageDraw
from loguru import logger

from app.ai.provider_factory import get_ai_provider

class StoryImageGenerator:
    """
    Generates story-specific background illustrations and cinematic shot visuals
    using professional director-level prompting formulas (PRINTFILM standards).
    """

    CINEMATIC_PROMPT_SYSTEM = (
        "You are an acclaimed Hollywood cinematic art director and concept artist. "
        "Your task is to analyze the story title and excerpt and generate a professional, "
        "highly detailed AI image prompt (Flux / Midjourney v6 style) in English.\n\n"
        "Follow the 5-component Cinematic Formula:\n"
        "1. [Subject & Expression]: Detailed main subject, pose, action, and authentic emotional expression.\n"
        "2. [Scene & Environment]: Rich background worldbuilding, atmosphere, foreground & background depth.\n"
        "3. [Camera Framing & Motion]: Shot type (cinematic wide establishing shot, medium low-angle, extreme close-up emotional portrait, anamorphic lens).\n"
        "4. [Lighting & Palette]: Volumetric golden hour, moody chiaroscuro, cybernetic neon rim light, soft diffuse mist, 35mm film grain.\n"
        "5. [Art Style & Quality]: Masterpiece digital illustration, cinematic concept art, octane render, 8k resolution, highly detailed textures, photorealistic.\n\n"
        "STRICT RULE: Output ONLY the English prompt text directly without any preface, quotes, or markdown backticks."
    )

    @classmethod
    async def generate_visual_prompt(cls, title: str, content: str) -> str:
        """Use AI with cinematic director formula to craft an atmospheric visual prompt."""
        try:
            provider = get_ai_provider()
            story_sample = content[:1500] if len(content) > 1500 else content

            user_prompt = f"Story Title: {title}\nStory Excerpt:\n{story_sample}"
            prompt = await provider.generate_text(
                prompt=user_prompt,
                system_prompt=cls.CINEMATIC_PROMPT_SYSTEM,
                temperature=0.7
            )
            clean_prompt = prompt.strip().replace('"', '').replace('\n', ' ')
            if clean_prompt:
                return clean_prompt
        except Exception as e:
            logger.warning(f"Error generating visual prompt with AI: {e}")
        
        # Fallback cinematic prompt based on title
        return (
            f"Cinematic wide establishing shot for story '{title}', detailed character in atmospheric environment, "
            f"volumetric lighting, dramatic chiaroscuro, golden hour rim light, 35mm film still, masterpiece digital painting, 8k"
        )

    @classmethod
    async def generate_cinematic_shot_prompts(
        cls,
        title: str,
        segments: List[Dict[str, Any]],
        aspect_ratio: str = "9:16"
    ) -> List[Dict[str, str]]:
        """
        Generates individual cinematic shot prompts for each scene/segment,
        ensuring visual continuity and dynamic shot framing variation.
        """
        framing_types = [
            "wide establishing landscape shot, slow push-in",
            "medium shot focusing on character emotion and posture",
            "dynamic low-angle shot with deep environmental depth",
            "intimate close-up portrait highlighting facial expression",
            "atmospheric tracking shot with foreground silhouettes"
        ]

        shot_prompts: List[Dict[str, str]] = []
        for idx, seg in enumerate(segments):
            text = seg.get("text", "")
            speaker = seg.get("speaker_name", "Narrator")
            emotion = seg.get("emotion", "neutral")
            framing = framing_types[idx % len(framing_types)]

            prompt = (
                f"Cinematic {framing} for story '{title}'. "
                f"Character: {speaker} showing {emotion} expression. Scene context: {text[:160]}. "
                f"Volumetric atmosphere, cinematic color grade, 35mm film aesthetics, masterpiece, 8k resolution"
            )
            shot_prompts.append({
                "shot_no": idx + 1,
                "speaker": speaker,
                "prompt": prompt,
                "framing": framing
            })
        return shot_prompts

    @classmethod
    def _download_image_sync(cls, prompt: str, output_path: Path, width: int, height: int) -> bool:
        """Download generated image from Pollinations AI (Flux model)."""
        encoded_prompt = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width={width}&height={height}&nologo=true&model=flux"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 200:
                    with open(output_path, "wb") as f:
                        f.write(resp.read())
                    if output_path.exists() and os.path.getsize(output_path) > 5000:
                        logger.info(f"AI background image downloaded successfully: {output_path}")
                        return True
        except Exception as e:
            logger.warning(f"Pollinations AI image fetch failed: {e}")

        return False

    @classmethod
    def _create_fallback_gradient(cls, output_path: Path, width: int, height: int) -> Path:
        """Create a beautiful dark modern gradient background as reliable fallback."""
        img = Image.new("RGB", (width, height), color="#090d16")
        draw = ImageDraw.Draw(img)
        
        # Draw smooth radial / vertical gradient
        for y in range(height):
            ratio = y / height
            r = int(12 + ratio * 20)
            g = int(18 + ratio * 15)
            b = int(35 + ratio * 45)
            draw.line([(0, y), (width, y)], fill=(r, g, b))
            
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, format="JPEG", quality=90)
        return output_path

    @classmethod
    async def generate_story_background(
        cls,
        story_id: int,
        title: str,
        content: str,
        aspect_ratio: str = "16:9"
    ) -> str:
        """
        Generate background image for the story audiobook.
        Returns the relative path to the generated image file.
        """
        output_dir = Path("media/working/stories")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        bg_path = output_dir / f"story_{story_id}_bg_{aspect_ratio.replace(':', 'x')}.jpg"
        width, height = (1920, 1080) if aspect_ratio == "16:9" else (1080, 1920)

        # 1. Generate visual prompt using cinematic director formula
        logger.info(f"Generating cinematic visual prompt for Story #{story_id} ('{title}')...")
        prompt = await cls.generate_visual_prompt(title, content)
        logger.info(f"Visual Prompt: {prompt}")

        # 2. Try downloading AI generated image
        success = await asyncio.to_thread(
            cls._download_image_sync,
            prompt=prompt,
            output_path=bg_path,
            width=width,
            height=height
        )

        # 3. If failed, generate sleek gradient image
        if not success or not bg_path.exists():
            logger.info("Using high-quality dark gradient canvas for story background...")
            await asyncio.to_thread(
                cls._create_fallback_gradient,
                output_path=bg_path,
                width=width,
                height=height
            )

        return str(bg_path).replace("\\", "/")
