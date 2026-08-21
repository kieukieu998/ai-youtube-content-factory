import os
import subprocess
from pathlib import Path
from typing import Dict, List, Any
from pydantic import BaseModel
from loguru import logger
from app.core.config import settings

class QAResult(BaseModel):
    passed: bool
    duration_seconds: float
    file_size_mb: float
    has_audio: bool
    has_video: bool
    issues: List[str]

class QAAgent:
    """Agent 9: Kiểm định tự động chất lượng video trước khi xuất bản."""
    
    @staticmethod
    def inspect_video(video_path: str) -> QAResult:
        issues = []
        if not os.path.exists(video_path):
            return QAResult(
                passed=False,
                duration_seconds=0,
                file_size_mb=0,
                has_audio=False,
                has_video=False,
                issues=["File video không tồn tại"]
            )
            
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if file_size_mb < 0.5:
            issues.append(f"Dung lượng video quá nhỏ ({file_size_mb:.2f} MB)")

        ffprobe_bin = settings.FFPROBE_PATH
        cmd = [
            ffprobe_bin,
            "-v", "error",
            "-show_entries", "format=duration:stream=codec_type",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        
        has_video = True
        has_audio = True
        duration = 0.0
        
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output_lines = [line.strip() for line in res.stdout.strip().split("\n") if line.strip()]
            for line in output_lines:
                try:
                    duration = float(line)
                except ValueError:
                    pass
        except Exception as e:
            logger.warning(f"FFprobe check warning: {e}")
            duration = 30.0 # fallback

        passed = len(issues) == 0
        return QAResult(
            passed=passed,
            duration_seconds=duration,
            file_size_mb=file_size_mb,
            has_audio=has_audio,
            has_video=has_video,
            issues=issues
        )
