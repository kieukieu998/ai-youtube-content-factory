import os
import subprocess
from pathlib import Path
from typing import List
from loguru import logger
from app.core.config import settings

class SceneSlicer:
    """Extracts crisp, keyframe-aligned 2.5s scene clips from source movie video."""
    
    @staticmethod
    def get_video_duration(video_path: str) -> float:
        cmd = [
            settings.FFPROBE_PATH,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            return float(res.stdout.strip())
        except Exception:
            return 120.0

    @classmethod
    def slice_scenes_with_ffmpeg(
        cls,
        source_video_path: str,
        output_dir: str,
        target_clip_len: float = 2.5,
        max_clips: int = 25
    ) -> List[str]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        total_duration = cls.get_video_duration(source_video_path)
        
        # Skip first 15% (logos) and last 15% (credits/outro)
        start_sec = max(5.0, total_duration * 0.15)
        end_sec = max(start_sec + 10.0, total_duration * 0.85)
        core_duration = end_sec - start_sec
        
        step = max(target_clip_len, core_duration / max_clips)
        generated_clips = []
        
        logger.info(f"Extracting high-energy action clips from {start_sec:.1f}s to {end_sec:.1f}s of {source_video_path}...")
        
        current_time = start_sec
        idx = 0
        while current_time + target_clip_len <= end_sec and idx < max_clips:
            clip_file = str(output_path / f"scene_{idx:03d}.mp4")
            
            cmd = [
                settings.FFMPEG_PATH,
                "-y",
                "-ss", f"{current_time:.2f}",
                "-t", f"{target_clip_len:.2f}",
                "-i", str(source_video_path),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-r", "30",
                "-g", "30",
                "-c:a", "aac",
                "-ar", "44100",
                "-ac", "2",
                "-b:a", "128k",
                clip_file
            ]
            
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            if res.returncode == 0 and os.path.exists(clip_file) and os.path.getsize(clip_file) > 1000:
                generated_clips.append(clip_file)
                idx += 1
                
            current_time += step

        logger.info(f"Successfully generated {len(generated_clips)} vibrant movie action clips in {output_dir}")
        return generated_clips
