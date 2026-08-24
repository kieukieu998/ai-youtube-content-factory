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
    gender: Optional[str] = "female"
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
    # Map Unicode replacement char \ufffd or \uFFFD which often happens on Vietnamese 'đ' / 'Đ'
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
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 0:
            raise RuntimeError(f"Lỗi trích xuất audio cho AI: {res.stderr.decode('utf-8', errors='ignore')}")
        return str(out)

    @classmethod
    async def transcribe_and_translate(
        cls,
        audio_path: str,
        source_language: str = "auto"
    ) -> List[DubbingSegment]:
        """
        Extract acoustic speech boundaries using faster-whisper and translate with Gemini AI
        for 100% ground-truth millisecond synchronization and natural Vietnamese acting.
        """
        provider = GeminiProvider()
        if not provider.client:
            raise RuntimeError("Gemini AI Client không thể khởi tạo. Vui lòng kiểm tra GEMINI_API_KEY trong .env hoặc Cài Đặt.")

        audio_file = Path(audio_path).resolve()
        if not audio_file.exists():
            raise FileNotFoundError(f"Audio file not found: {audio_file}")

        loop = asyncio.get_event_loop()
        whisper_segments = []

        # 1. Acoustic speech-to-text & VAD using faster-whisper
        try:
            from faster_whisper import WhisperModel
            logger.info(f"Running faster-whisper acoustic speech detection on: {audio_file.name}...")
            
            def run_whisper():
                whisper_model = WhisperModel("base", device="cpu", compute_type="int8")
                lang = source_language if source_language not in ["auto", "", None] else None
                raw_segs, info = whisper_model.transcribe(
                    str(audio_file),
                    language=lang,
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=350)
                )
                res = []
                for s in raw_segs:
                    txt = s.text.strip()
                    if txt and len(txt) >= 1:
                        res.append({
                            "start": round(s.start, 2),
                            "end": round(s.end, 2),
                            "original_text": txt
                        })
                return res, info.language

            whisper_segments, detected_lang = await loop.run_in_executor(None, run_whisper)
            logger.info(f"faster-whisper extracted {len(whisper_segments)} acoustic segments (detected: {detected_lang}).")
        except Exception as whisper_err:
            logger.warning(f"faster-whisper local transcription failed: {whisper_err}. Falling back to Gemini audio chunking.")
            whisper_segments = []

        # 2. If faster-whisper succeeded, translate with Gemini using exact timestamps
        if whisper_segments:
            logger.info(f"Translating {len(whisper_segments)} acoustic dialogue lines with Gemini...")
            
            # Batch in groups of 30 lines to avoid token limits
            batch_size = 30
            all_segments: List[DubbingSegment] = []
            
            for i in range(0, len(whisper_segments), batch_size):
                batch = whisper_segments[i:i + batch_size]
                prompt = f"""
Bạn là chuyên gia dịch thuật và lồng tiếng phim chuyên nghiệp (Movie Dubbing Specialist).
Dưới đây là các câu thoại gốc cùng mốc thời gian âm thanh CHÍNH XÁC đến mili-giây được trích xuất từ audio phim:

{json.dumps(batch, ensure_ascii=False, indent=2)}

Nhiệm vụ:
1. Dịch từng câu thoại sang Tiếng Việt tự nhiên, truyền cảm, phù hợp với ngữ cảnh điện ảnh.
2. Nhận diện giới tính nhân vật nói câu này: "gender": "male" hoặc "female".
3. Giữ NGUYÊN mốc thời gian "start" và "end" của từng câu.

YÊU CẦU ĐỊNH DẠNG: Trả về DUY NHẤT một JSON Array hợp lệ (Không bọc text giải thích):
[
  {{
    "start": 6.67,
    "end": 7.55,
    "gender": "female",
    "original_text": "...",
    "translated_text": "..."
  }}
]
"""
                models_to_try = [provider.model_name] + [m for m in getattr(provider, "CANDIDATE_MODELS", []) if m != provider.model_name]
                res_text = None
                for m in models_to_try:
                    try:
                        res = await loop.run_in_executor(None, lambda model_name=m: provider.client.models.generate_content(
                            model=model_name,
                            contents=[prompt]
                        ))
                        if res and res.text:
                            res_text = res.text.strip()
                            break
                    except Exception as model_err:
                        logger.warning(f"Model {m} failed in batch translation: {model_err}")
                        await asyncio.sleep(0.5)

                if res_text:
                    try:
                        clean_json = res_text.strip()
                        code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
                        if code_match:
                            clean_json = code_match.group(1).strip()
                        else:
                            first_b = clean_json.find('[')
                            last_b = clean_json.rfind(']')
                            if first_b != -1 and last_b != -1:
                                clean_json = clean_json[first_b:last_b + 1]

                        parsed = json.loads(clean_json)
                        for item in parsed:
                            s_start = float(item.get("start", 0.0))
                            s_end = float(item.get("end", s_start + 1.2))
                            gender = str(item.get("gender", "female")).lower()
                            orig = str(item.get("original_text", "")).strip()
                            trans = sanitize_tts_text(str(item.get("translated_text", "")))
                            if trans:
                                all_segments.append(DubbingSegment(
                                    start=max(0.0, s_start),
                                    end=max(s_start + 0.4, s_end),
                                    gender="male" if "male" in gender and "female" not in gender else "female",
                                    original_text=orig,
                                    translated_text=trans
                                ))
                    except Exception as batch_parse_e:
                        logger.warning(f"Error parsing batch translation JSON: {batch_parse_e}")

            all_segments.sort(key=lambda s: s.start)
            logger.info(f"Successfully processed {len(all_segments)} dubbing segments with faster-whisper acoustic alignment.")
            return all_segments

        # 3. Fallback: Gemini 45s audio chunking
        logger.info(f"Using Gemini chunked audio transcription fallback...")
        probe_cmd = [
            settings.FFPROBE_PATH, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_file)
        ]
        probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        total_audio_dur = float(probe_res.stdout.strip()) if probe_res.stdout.strip() else 120.0

        lang_instruction = f"Ngôn ngữ gốc của video: {source_language}" if source_language != "auto" else "Tự động phát hiện ngôn ngữ gốc"
        chunk_len = 45.0
        chunks_info = []
        curr_t = 0.0
        while curr_t < total_audio_dur:
            dur = min(chunk_len, total_audio_dur - curr_t)
            chunks_info.append((curr_t, dur))
            curr_t += chunk_len

        all_segments: List[DubbingSegment] = []

        for chunk_idx, (c_start, c_dur) in enumerate(chunks_info):
            chunk_file = audio_file.parent / f"chunk_{chunk_idx:02d}.mp3"
            cmd_slice = [
                settings.FFMPEG_PATH, "-y",
                "-ss", f"{c_start:.3f}",
                "-t", f"{c_dur:.3f}",
                "-i", str(audio_file),
                "-c", "copy",
                str(chunk_file)
            ]
            subprocess.run(cmd_slice, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if not chunk_file.exists() or chunk_file.stat().st_size < 100:
                continue

            uploaded_file = await loop.run_in_executor(
                None,
                lambda p=chunk_file: provider.client.files.upload(file=str(p))
            )

            prompt = f"""
Bạn là chuyên gia phân tích âm thanh, dịch thuật và lồng tiếng phim chuyên nghiệp (Voice Dubbing & Lip-Sync Synchronization Expert).
Nhiệm vụ: Lắng nghe toàn bộ file âm thanh này (bắt đầu từ giây 0.0s đến {c_dur:.1f}s của đoạn cắt này).
Trích xuất TẤT CẢ các câu thoại của nhân vật xuất hiện trong đoạn này.

CÁC QUY TẮC BẮT BUỘC:
1. {lang_instruction}.
2. TÁCH TỪNG CÂU THOẠI ĐƠN LẺ (SENTENCE-BY-SENTENCE / TURN-BY-TURN):
   - Mỗi câu nói của MỘT nhân vật là MỘT mục riêng biệt.
3. ĐỘ CHÍNH XÁC MỐC THỜI GIAN (START & END):
   - "start": Giây chính xác nhân vật BẮT ĐẦU phát âm (tính từ 0.0s của đoạn này).
   - "end": Giây chính xác nhân vật KẾT THÚC phát âm (tính từ 0.0s của đoạn này).
4. BẢN DỊCH TIẾNG VIỆT TƯƠNG ĐƯƠNG ĐỘ DÀI.
5. NHẬN DIỆN GIỚI TÍNH GIỌNG NÓI (GENDER): "female" hoặc "male".

YÊU CẦU ĐỊNH DẠNG: Trả về DUY NHẤT một JSON Array hợp lệ.
"""
            try:
                models_to_try = [provider.model_name] + [m for m in getattr(provider, "CANDIDATE_MODELS", []) if m != provider.model_name]
                raw_text = None
                for model in models_to_try:
                    try:
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
                    except Exception:
                        continue

                if raw_text:
                    clean_json = raw_text.strip()
                    code_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", clean_json)
                    if code_match:
                        clean_json = code_match.group(1).strip()
                    else:
                        first_b = clean_json.find('[')
                        last_b = clean_json.rfind(']')
                        if first_b != -1 and last_b != -1:
                            clean_json = clean_json[first_b:last_b + 1]

                    parsed = json.loads(clean_json)
                    for item in parsed:
                        s_start = float(item.get("start", 0.0)) + c_start
                        s_end = float(item.get("end", s_start - c_start + 1.5)) + c_start
                        gender = str(item.get("gender", "female")).lower()
                        orig = str(item.get("original_text", "")).strip()
                        trans = sanitize_tts_text(str(item.get("translated_text", "")))
                        if trans:
                            all_segments.append(DubbingSegment(
                                start=max(0.0, s_start),
                                end=max(s_start + 0.4, s_end),
                                gender="male" if "male" in gender and "female" not in gender else "female",
                                original_text=orig,
                                translated_text=trans
                            ))
            finally:
                try:
                    await loop.run_in_executor(None, lambda: provider.client.files.delete(name=uploaded_file.name))
                    if chunk_file.exists():
                        chunk_file.unlink()
                except Exception:
                    pass

        all_segments.sort(key=lambda s: s.start)
        return all_segments

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
            if not clean_text or len(clean_text) < 1:
                return None

            clip_path = tts_clips_dir / f"clip_{idx:03d}.mp3"
            
            # Select gender-appropriate voice
            if seg.gender == "male":
                actual_voice = "vi-VN-NamMinhNeural"
            else:
                actual_voice = voice_name if "HoaiMy" in voice_name or "Nu" in voice_name else "vi-VN-HoaiMyNeural"

            async with sem:
                for attempt in range(2):
                    try:
                        communicate = edge_tts.Communicate(text=clean_text, voice=actual_voice)
                        await asyncio.wait_for(communicate.save(str(clip_path)), timeout=15.0)
                        if clip_path.exists() and clip_path.stat().st_size > 100:
                            break
                    except Exception as e:
                        if attempt == 1:
                            logger.warning(f"Could not generate TTS for segment {idx} ('{clean_text}'): {e}")
                        await asyncio.sleep(0.5)

            if not clip_path.exists() or clip_path.stat().st_size < 100:
                return None

            # Get clip duration via ffprobe
            probe_cmd = [
                settings.FFPROBE_PATH, "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(clip_path)
            ]
            probe_res = subprocess.run(probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            clip_dur = float(probe_res.stdout.strip()) if probe_res.stdout.strip() else 1.0

            target_slot = max(0.4, seg.end - seg.start)
            final_clip_path = clip_path

            # Adjust tempo so voice finishes exactly when the character stops speaking
            if clip_dur > target_slot * 1.05:
                speed_ratio = min(1.65, clip_dur / target_slot)
                speedup_clip = tts_clips_dir / f"clip_{idx:03d}_fast.wav"
                res_speed = subprocess.run([
                    settings.FFMPEG_PATH, "-y",
                    "-i", str(clip_path),
                    "-filter:a", f"atempo={speed_ratio:.3f},aformat=sample_rates=48000:channel_layouts=stereo",
                    str(speedup_clip)
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if res_speed.returncode == 0 and speedup_clip.exists() and speedup_clip.stat().st_size > 100:
                    final_clip_path = speedup_clip
                    clip_dur = clip_dur / speed_ratio

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
