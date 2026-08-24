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
    def is_clip_mostly_black(cls, clip_path: str) -> bool:
        """Probe clip with FFmpeg blackdetect to ensure it is not a pure black screen or dark studio intro."""
        try:
            cmd = [
                settings.FFMPEG_PATH,
                "-v", "error",
                "-i", str(clip_path),
                "-vf", "blackdetect=d=0.8:pix_th=0.12",
                "-f", "null",
                "-"
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if "black_start: 0" in res.stderr or "black_start:0" in res.stderr:
                return True
        except Exception:
            pass
        return False

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
        
        # Clean stale clips in slice folder to prevent mixing old scenes
        for old_f in output_path.glob("*.mp4"):
            try:
                old_f.unlink()
            except Exception:
                pass

        total_duration = cls.get_video_duration(source_video_path)
        
        # Always skip dark studio intros / rating screens in the first 4-6 seconds of trailers
        intro_skip = min(5.5, total_duration * 0.08) if total_duration > 15.0 else 0.5

        # Calculate distinct timeline window matching the story arc of the current episode
        if total_episodes <= 1:
            start_ratio, end_ratio = 0.05, 0.98
        elif total_episodes == 3:
            if episode_number == 1:
                # Act 1: Introduction & Inciting incident (skip studio cards)
                start_ratio, end_ratio = 0.05, 0.38
            elif episode_number == 2:
                # Act 2: Rising action & Conflict
                start_ratio, end_ratio = 0.38, 0.70
            else:
                # Act 3: Climax & Grand Twist Resolution
                start_ratio, end_ratio = 0.70, 0.98
        else:
            seg_len = 0.95 / total_episodes
            start_ratio = max(0.04, 0.05 + (episode_number - 1) * seg_len)
            end_ratio = min(0.99, start_ratio + seg_len)

        start_sec = max(intro_skip, total_duration * start_ratio)
        end_sec = min(total_duration - 1.0, total_duration * end_ratio)
        if end_sec <= start_sec + 4.0:
            start_sec = intro_skip
            end_sec = total_duration - 1.0

        core_duration = end_sec - start_sec
        step = max(target_clip_len, core_duration / max(1, max_clips))
        generated_clips = []
        
        logger.info(
            f"[Episode {episode_number}/{total_episodes}] Slicing distinct non-black timeline scenes "
            f"from {start_sec:.1f}s to {end_sec:.1f}s (duration: {core_duration:.1f}s) of {source_video_path}..."
        )
        
        current_time = start_sec
        idx = 0
        attempts = 0
        max_attempts = max_clips * 2

        while current_time + target_clip_len <= end_sec and idx < max_clips and attempts < max_attempts:
            attempts += 1
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
                # Check if clip is black screen, if so discard and jump ahead
                if cls.is_clip_mostly_black(clip_file):
                    logger.warning(f"Detected black intro frame at {current_time:.2f}s, discarding and advancing...")
                    try:
                        os.remove(clip_file)
                    except Exception:
                        pass
                    current_time += max(1.5, step * 0.7)
                    continue

                generated_clips.append(clip_file)
                idx += 1
                
            current_time += step

        logger.info(f"Successfully generated {len(generated_clips)} crisp action clips (zero black frames) for Episode {episode_number}")
        return generated_clips
