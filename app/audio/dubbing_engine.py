import os
import re
import json
import asyncio
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from loguru import logger
import edge_tts

from app.core.config import settings
from app.ai.gemini_provider import GeminiProvider

class DubbingSegment(BaseModel):
    start: float
    end: float
    original_text: str = ""
    translated_text: str

class DubbingResult(BaseModel):
    dubbed_audio_path: str
    segments: List[DubbingSegment]
    subtitles_srt_path: Optional[str] = None
    total_segments: int = 0


def sanitize_tts_text(text: str) -> str:
    """Clean and sanitize Vietnamese text to prevent edge-tts WebSocket errors."""
    if not text:
        return ""
    # Map Unicode replacement char \ufffd or  which often happens on Vietnamese 'đ' / 'Đ'
    # Check if followed by capital vowel (Đóng, Đây, Đồng...)
    text = re.sub(r'[\ufffd\uFFFD\u0080-\u009F](?=[A-ZÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐĨŨƠƯ])', 'Đ', text)
    text = re.sub(r'[\ufffd\uFFFD\u0080-\u009F]', 'đ', text)
    # Remove control characters and strange symbols
    text = re.sub(r'[^\w\s.,?!;:…–—\'"“”‘’\-\(\)]', ' ', text, flags=re.UNICODE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class DubbingEngine:
    """
    AI Video Dubbing Engine (Dịch & Lồng Tiếng AI Đa Ngôn Ngữ -> Tiếng Việt).
    Pipeline:
    1. Extract Audio from Video.
    2. AI Speech-to-Text & Contextual Translation to Vietnamese with Timestamps.
    3. Generate Synchronized Vietnamese TTS Clips (edge-tts).
    4. Fit and Align Audio Clips to Time Intervals (atempo + timeline padding).
    5. Mix Voiceover / Full Dubbing with Original Background.
    """

    @classmethod
    def extract_audio_for_ai(cls, input_video_or_audio: str, output_audio_path: str) -> str:
        """Extract optimized lightweight 16kHz mono audio for AI transcription."""
        out = Path(output_audio_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        
        cmd = [
            settings.FFMPEG_PATH, "-y",
            "-i", str(input_video_or_audio),
            "-vn",
            "-ac", "1",
            "-ar", "16000",
            "-b:a", "64k",
            str(out)
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode != 0:
            logger.error(f"Failed to extract audio for AI: {res.stderr}")
            raise RuntimeError("Không thể trích xuất âm thanh từ video.")
        return str(out)

    @classmethod
    async def transcribe_and_translate(
        cls, 
        audio_path: str, 
        source_language: str = "auto",
        gemini_provider: Optional[GeminiProvider] = None
    ) -> List[DubbingSegment]:
        """
        Send audio to Gemini Multimodal AI to transcribe spoken speech and translate to Vietnamese
        with exact timestamp intervals.
        """
        provider = gemini_provider or GeminiProvider()
        provider._ensure_configured()

        audio_file = Path(audio_path).resolve()
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        logger.info(f"Uploading audio to Gemini for dubbing transcription: {audio_file.name} ({source_language})...")
        loop = asyncio.get_event_loop()

        # 1. Upload audio file to Google AI File API
        uploaded_file = await loop.run_in_executor(
            None,
            lambda: provider.client.files.upload(file=str(audio_file))
        )
        logger.info(f"Audio file uploaded to Gemini: {uploaded_file.name}")

        lang_instruction = f"Ngôn ngữ gốc của video: {source_language}" if source_language != "auto" else "Tự động phát hiện ngôn ngữ gốc (Tiếng Trung, Tiếng Anh, Tiếng Hàn, Tiếng Nhật...)"

        prompt = f"""
Bạn là chuyên gia dịch thuật và lồng tiếng phim chuyên nghiệp.
Nhiệm vụ: Lắng nghe toàn bộ file âm thanh được cung cấp.
1. {lang_instruction}.
2. Trích xuất toàn bộ các câu thoại / lời nói của nhân vật với mốc thời gian chính xác (start và end tính bằng giây, ví dụ: 1.25, 4.50).
3. Dịch từng câu thoại sang Tiếng Việt tự nhiên, truyền cảm, phù hợp với ngữ cảnh điện ảnh và có độ dài câu tương đương câu thoại gốc để lồng tiếng.
4. Bỏ qua các đoạn chỉ có nhạc nền hoặc khoảng lặng không có lời nói.
5. Tuyệt đối KHÔNG sử dụng ký tự lạ, ký tự lỗi unicode hoặc emoji trong câu dịch tiếng Việt.

YÊU CẦU ĐỊNH DẠNG:
Trả về DUY NHẤT một JSON Array hợp lệ (Không bọc text giải thích):
[
  {{
    "start": 0.5,
    "end": 3.2,
    "original_text": "Câu thoại gốc",
    "translated_text": "Câu dịch tiếng Việt tự nhiên"
  }}
]
"""

        try:
            models_to_try = [provider.model_name, "gemini-3.6-flash", "gemini-3.7-flash", "gemini-3.5-flash"]
            raw_text = None
            last_err = None

            for model in models_to_try:
                try:
                    logger.info(f"Transcribing audio with Gemini model: {model}...")
                    response = await loop.run_in_executor(
                        None,
                        lambda m=model: provider.client.models.generate_content(
                            model=m,
                            contents=[uploaded_file, prompt]
                        )
                    )
                    if response and response.text:
                        raw_text = response.text.strip()
                        break
                except Exception as e:
                    last_err = e
                    logger.warning(f"Model {model} failed on audio: {e}")
                    await asyncio.sleep(1.0)
                    continue

            if not raw_text:
                raise RuntimeError(f"Gemini AI không thể xử lý âm thanh: {last_err}")

            # Clean JSON text
            clean_json = raw_text.strip()
            code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
            if code_match:
                clean_json = code_match.group(1).strip()
            else:
                first_bracket = clean_json.find('[')
                last_bracket = clean_json.rfind(']')
                if first_bracket != -1 and last_bracket != -1:
                    clean_json = clean_json[first_bracket:last_bracket + 1]

            parsed_list = json.loads(clean_json)
            segments: List[DubbingSegment] = []
            for item in parsed_list:
                s_start = float(item.get("start", 0.0))
                s_end = float(item.get("end", s_start + 2.0))
                orig = str(item.get("original_text", "")).strip()
                trans = sanitize_tts_text(str(item.get("translated_text", "")))
                if trans and len(trans) >= 2:
                    segments.append(DubbingSegment(
                        start=max(0.0, s_start),
                        end=max(s_start + 0.5, s_end),
                        original_text=orig,
                        translated_text=trans
                    ))

            # Sort segments by start time
            segments.sort(key=lambda s: s.start)
            logger.info(f"Successfully transcribed & translated {len(segments)} dubbing segments.")
            return segments

        finally:
            try:
                await loop.run_in_executor(
                    None,
                    lambda: provider.client.files.delete(name=uploaded_file.name)
                )
            except Exception as e:
                logger.debug(f"File delete notice: {e}")

    @classmethod
    async def synthesize_dubbing_track(
        cls,
        segments: List[DubbingSegment],
        voice_name: str,
        total_duration: float,
        working_dir: Path
    ) -> str:
        """
        Generate TTS for each segment in parallel and assemble them onto an aligned audio track
        with exact timestamp placement using pydub.
        """
        working_dir.mkdir(parents=True, exist_ok=True)
        tts_clips_dir = working_dir / "tts_clips"
        tts_clips_dir.mkdir(parents=True, exist_ok=True)

        if not segments:
            silent_track = str(working_dir / "dubbed_silent.wav")
            subprocess.run([
                settings.FFMPEG_PATH, "-y", "-f", "lavfi",
                "-i", f"anullsrc=r=48000:cl=stereo:d={max(1.0, total_duration)}",
                "-c:a", "pcm_s16le", silent_track
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return silent_track

        sem = asyncio.Semaphore(2)

        async def process_clip(idx: int, seg: DubbingSegment):
            clean_text = sanitize_tts_text(seg.translated_text)
            if not clean_text or len(clean_text) < 2:
                return None

            clip_path = tts_clips_dir / f"clip_{idx:03d}.mp3"
            async with sem:
                for attempt in range(2):
                    try:
                        communicate = edge_tts.Communicate(text=clean_text, voice=voice_name)
                        await asyncio.wait_for(communicate.save(str(clip_path)), timeout=15.0)
                        if clip_path.exists() and clip_path.stat().st_size > 100:
                            break
                    except Exception as e:
                        if attempt == 1:
                            logger.warning(f"Could not generate TTS for segment {idx} ('{clean_text}'): {e}")
                        await asyncio.sleep(0.5)

            if not clip_path.exists() or clip_path.stat().st_size < 100:
                return None

            probe_cmd = [
                settings.FFPROBE_PATH, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(clip_path)
            ]
            probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            clip_dur = float(probe_res.stdout.strip()) if probe_res.stdout.strip() else 1.0

            target_slot = max(0.5, seg.end - seg.start)
            final_clip_path = clip_path

            if clip_dur > target_slot * 1.08:
                speed_ratio = min(1.35, clip_dur / target_slot)
                speedup_clip = tts_clips_dir / f"clip_{idx:03d}_fast.wav"
                res_speed = subprocess.run([
                    settings.FFMPEG_PATH, "-y",
                    "-i", str(clip_path),
                    "-filter:a", f"atempo={speed_ratio:.3f},aformat=sample_rates=48000:channel_layouts=stereo",
                    str(speedup_clip)
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res_speed.returncode == 0 and speedup_clip.exists() and speedup_clip.stat().st_size > 100:
                    final_clip_path = speedup_clip

            return {
                "path": str(final_clip_path),
                "start": seg.start,
                "duration": clip_dur
            }

        tasks = [process_clip(i, s) for i, s in enumerate(segments)]
        results = await asyncio.gather(*tasks)
        generated_clips = [r for r in results if r is not None]
        generated_clips.sort(key=lambda x: x["start"])

        # Construct continuous master track with pydub
        from pydub import AudioSegment
        
        master_duration_ms = max(int(total_duration * 1000) + 2000, 2000)
        master_audio = AudioSegment.silent(duration=master_duration_ms, frame_rate=48000)
        
        for clip in generated_clips:
            clip_p = Path(clip["path"])
            if clip_p.exists() and clip_p.stat().st_size > 100:
                try:
                    sound = AudioSegment.from_file(str(clip_p))
                    pos_ms = max(0, int(clip["start"] * 1000))
                    master_audio = master_audio.overlay(sound, position=pos_ms)
                except Exception as e:
                    logger.warning(f"Could not overlay audio clip {clip_p.name}: {e}")

        dubbed_master = str(working_dir / "dubbed_master_voice.wav")
        master_audio.export(dubbed_master, format="wav")
        logger.info(f"Successfully generated dubbed master audio timeline: {dubbed_master} ({len(generated_clips)} clips)")

        return dubbed_master

    @classmethod
    def generate_subtitles_ass(cls, segments: List[DubbingSegment], output_ass_path: str) -> str:
        """
        Export Vietnamese translated subtitles as modern TikTok-styled ASS subtitle file.
        PlayResX=1080, PlayResY=1920 with crisp font, black outline, placed at lower-third.
        """
        def format_ass_time(seconds: float) -> str:
            hrs = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            cs = int(round((seconds - int(seconds)) * 100))
            return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"

        out = Path(output_ass_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        ass_header = """[Script Info]
Title: AI Dubbing Subtitles
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: DubbingStyle,Arial,46,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,3.2,1.2,2,60,60,260,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        dialogue_lines = []
        for seg in segments:
            clean_text = seg.translated_text.strip()
            if not clean_text:
                continue

            # Auto-wrap long lines (max 6-7 words per line, max 2 lines)
            words = clean_text.split()
            if len(words) > 6:
                mid = len(words) // 2
                wrapped_text = " ".join(words[:mid]) + "\\N" + " ".join(words[mid:])
            else:
                wrapped_text = clean_text

            start_str = format_ass_time(seg.start)
            end_str = format_ass_time(seg.end)
            dialogue_lines.append(f"Dialogue: 0,{start_str},{end_str},DubbingStyle,,0,0,0,,{wrapped_text}")

        with open(out, "w", encoding="utf-8") as f:
            f.write(ass_header + "\n".join(dialogue_lines) + "\n")

        return str(out)

    @classmethod
    def generate_subtitles_srt(cls, segments: List[DubbingSegment], output_srt_path: str) -> str:
        """Export Vietnamese translated subtitles as standard SRT file with 2-line wrapping."""
        def format_srt_time(seconds: float) -> str:
            hrs = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            millis = int(round((seconds - int(seconds)) * 1000))
            return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

        out = Path(output_srt_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        lines = []
        for idx, seg in enumerate(segments, 1):
            clean_text = seg.translated_text.strip()
            if not clean_text:
                continue

            words = clean_text.split()
            if len(words) > 6:
                mid = len(words) // 2
                wrapped_text = " ".join(words[:mid]) + "\n" + " ".join(words[mid:])
            else:
                wrapped_text = clean_text

            lines.append(str(idx))
            lines.append(f"{format_srt_time(seg.start)} --> {format_srt_time(seg.end)}")
            lines.append(wrapped_text)
            lines.append("")

        with open(out, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return str(out)
