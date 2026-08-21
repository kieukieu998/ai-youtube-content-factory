from typing import List
from loguru import logger

class SceneSelectorAgent:
    """Agent 5: Lựa chọn và ghép nối các phân cảnh hành động đẹp nhất."""
    
    @staticmethod
    def select_clips_for_duration(
        available_clips: List[str], 
        target_duration_seconds: float,
        avg_clip_len: float = 2.5
    ) -> List[str]:
        if not available_clips:
            raise ValueError("Không tìm thấy clip phân cảnh nào.")
            
        needed_count = max(2, int(target_duration_seconds / avg_clip_len) + 1)
        selected_clips = []
        
        for i in range(needed_count):
            selected_clips.append(available_clips[i % len(available_clips)])
            
        logger.info(f"Selected {len(selected_clips)} dynamic movie clips for {target_duration_seconds:.2f}s narration.")
        return selected_clips
