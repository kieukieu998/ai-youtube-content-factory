import os
import urllib.parse
import urllib.request
import asyncio
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw
from loguru import logger

from app.ai.provider_factory import get_ai_provider

class StoryImageGenerator:
    """Generates story-specific background illustrations using AI."""

    @classmethod
    async def generate_visual_prompt(cls, title: str, content: str) -> str:
        """Use AI to craft an atmospheric visual art prompt from the story."""
        try:
            provider = get_ai_provider()
            story_sample = content[:1500] if len(content) > 1500 else content

            sys_prompt = (
                "You are an expert art director. Read the Vietnamese story title and excerpt below, "
                "then generate a single concise image prompt in English for AI image generation (Flux/Midjourney style). "
                "Describe the scene, mood, lighting, color palette, and artistic style (e.g. cinematic digital painting, anime watercolor, moody atmospheric, photorealistic, 8k). "
                "Only return the English image prompt text without any explanation, quotes or markdown."
            )
            
            user_prompt = f"Story Title: {title}\nStory Excerpt:\n{story_sample}"
            prompt = await provider.generate_text(
                prompt=user_prompt,
                system_prompt=sys_prompt,
                temperature=0.7
            )
            clean_prompt = prompt.strip().replace('"', '').replace('\n', ' ')
            if clean_prompt:
                return clean_prompt
        except Exception as e:
            logger.warning(f"Error generating visual prompt with AI: {e}")
        
        # Fallback prompt based on title
        return f"Cinematic atmospheric digital art illustration for story '{title}', moody lighting, emotional anime wallpaper, masterpiece, 8k resolution"

    @classmethod
    def _download_image_sync(cls, prompt: str, output_path: Path, width: int, height: int) -> bool:
        """Download generated image from Pollinations AI (Flux/Turbo model)."""
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

        # 1. Generate visual prompt
        logger.info(f"Generating visual background prompt for Story #{story_id} ('{title}')...")
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
