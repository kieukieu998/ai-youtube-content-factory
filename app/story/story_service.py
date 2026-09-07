import re
from typing import List, Dict, Any

class StoryService:
    """Utilities for processing story text, paragraph chunking, and duration estimation."""
    
    WORDS_PER_MINUTE = 175 # Average natural Vietnamese speech rate
    
    @staticmethod
    def clean_text(text: str) -> str:
        """Clean and normalize story text while preserving paragraph breaks."""
        if not text:
            return ""
        # Normalize newlines
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Remove consecutive duplicate blank lines
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    @classmethod
    def get_word_count(cls, text: str) -> int:
        """Calculate total words in the text."""
        words = re.findall(r'\b\w+\b', text, re.UNICODE)
        return len(words)

    @classmethod
    def estimate_duration_seconds(cls, text: str, speed_multiplier: float = 1.0) -> float:
        """Estimate listening duration in seconds based on word count and speed multiplier."""
        words = cls.get_word_count(text)
        if words == 0:
            return 0.0
        minutes = words / (cls.WORDS_PER_MINUTE * max(0.5, speed_multiplier))
        return round(minutes * 60, 1)

    @staticmethod
    def split_into_readable_paragraphs(text: str, max_words_per_section: int = 250) -> List[str]:
        """
        Split narrative text into logical reading paragraphs/sections.
        Ensures smooth sentence boundaries for both UI display and TTS synthesis.
        """
        raw_paras = [p.strip() for p in text.split("\n") if p.strip()]
        sections = []
        current_section = []
        current_words = 0

        for p in raw_paras:
            words_in_p = len(p.split())
            if current_words + words_in_p > max_words_per_section and current_section:
                sections.append("\n\n".join(current_section))
                current_section = [p]
                current_words = words_in_p
            else:
                current_section.append(p)
                current_words += words_in_p

        if current_section:
            sections.append("\n\n".join(current_section))

        return sections if sections else [text]
