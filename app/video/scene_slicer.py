import os
import subprocess
from pathlib import Path
from typing import List, Optional
from loguru import logger
from app.core.config import settings

class SceneSlicer:
    """Extracts crisp, keyframe-aligned, timeline-aware scene clips from source movie video."""
    
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
        target_clip_len: float = 2.2,
        max_clips: int = 25,
        episode_number: int = 1,
        total_episodes: int = 3
    ) -> List[str]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        total_duration = cls.get_video_duration(source_video_path)
        
        # Calculate timeline window matching the story arc of the current episode
        if total_episodes <= 1:
            start_ratio, end_ratio = 0.05, 0.95
        elif total_episodes == 3:
            if episode_number == 1:
                # Act 1: Introduction & Inciting incident
                start_ratio, end_ratio = 0.05, 0.38
            elif episode_number == 2:
                # Act 2: Rising action & Conflict
                start_ratio, end_ratio = 0.35, 0.70
            else:
                # Act 3: Climax & Grand Twist Resolution
                start_ratio, end_ratio = 0.65, 0.95
        else:
            seg_len = 0.90 / total_episodes
            start_ratio = max(0.02, 0.05 + (episode_number - 1) * seg_len - 0.03)
            end_ratio = min(0.98, start_ratio + seg_len + 0.05)

        start_sec = max(2.0, total_duration * start_ratio)
        end_sec = min(total_duration - 2.0, total_duration * end_ratio)
        if end_sec <= start_sec + 5.0:
            start_sec = 2.0
            end_sec = total_duration - 2.0

        core_duration = end_sec - start_sec
        step = max(target_clip_len, core_duration / max_clips)
        generated_clips = []
        
        logger.info(
            f"[Episode {episode_number}/{total_episodes}] Slicing distinct timeline scenes "
            f"from {start_sec:.1f}s to {end_sec:.1f}s (duration: {core_duration:.1f}s) of {source_video_path}..."
        )
        
        current_time = start_sec
        idx = 0
        while current_time + target_clip_len <= end_sec and idx < max_clips:
            clip_file = str(output_path / f"ep_{episode_number}_scene_{idx:03d}.mp4")
            
            cmd = [
                settings.FFMPEG_PATH,
                "-y",
                "-ss", f"{current_time:.2f}",
                "-t", f"{target_clip_len:.2f}",
                "-i", str(source_video_path),
                "-c:v", "libx264",
                "-preset", "veryfast",
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

        logger.info(f"Successfully generated {len(generated_clips)} distinct action clips for Episode {episode_number}")
        return generated_clips
