import random
from typing import List
from loguru import logger

class SceneSelectorAgent:
    """Agent 5: Lựa chọn và ghép nối các phân cảnh hành động đẹp mắt, nhịp độ dồn dập."""
    
    @staticmethod
    def select_clips_for_duration(
        available_clips: List[str], 
        target_duration_seconds: float,
        avg_clip_len: float = 2.2
    ) -> List[str]:
        if not available_clips:
            raise ValueError("Không tìm thấy clip phân cảnh nào.")
            
        needed_count = max(2, int(target_duration_seconds / avg_clip_len) + 1)
        selected_clips = []
        
        # 1. First pass: chronological order of the episode's timeline
        for i in range(min(needed_count, len(available_clips))):
            selected_clips.append(available_clips[i])
            
        # 2. If narration is longer than available clips, loop with subtle shuffle for dynamism
        remaining = needed_count - len(selected_clips)
        if remaining > 0:
            extra_pool = list(available_clips)
            random.seed(42)
            random.shuffle(extra_pool)
            for i in range(remaining):
                selected_clips.append(extra_pool[i % len(extra_pool)])
            
        logger.info(f"Selected {len(selected_clips)} dynamic movie clips for {target_duration_seconds:.2f}s narration.")
        return selected_clips
