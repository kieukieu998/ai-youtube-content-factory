import os
from pathlib import Path
from app.audio.tts_engine import WordTimestamp
from app.subtitle.ass_generator import SubtitleGenerator

def test_kinetic_ass_and_srt_generation(tmp_path):
    words = [
        WordTimestamp(word="Bộ", start_ms=0, end_ms=200),
        WordTimestamp(word="phim", start_ms=200, end_ms=500),
        WordTimestamp(word="này", start_ms=500, end_ms=800),
        WordTimestamp(word="quá", start_ms=800, end_ms=1100),
        WordTimestamp(word="kinh", start_ms=1100, end_ms=1400),
        WordTimestamp(word="dị", start_ms=1400, end_ms=1700),
    ]

    ass_output = str(tmp_path / "test.ass")
    srt_output = str(tmp_path / "test.srt")

    SubtitleGenerator.generate_kinetic_ass(words, ass_output, words_per_line=3)
    SubtitleGenerator.generate_srt(words, srt_output, words_per_line=3)

    assert os.path.exists(ass_output)
    assert os.path.exists(srt_output)

    with open(ass_output, "r", encoding="utf-8") as f:
        ass_content = f.read()
        assert "[Script Info]" in ass_content
        assert "TikTokDefault" in ass_content
        assert "\\kf" in ass_content

    with open(srt_output, "r", encoding="utf-8") as f:
        srt_content = f.read()
        assert "-->" in srt_content
        assert "Bộ phim này" in srt_content
