import os
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List, Callable
import edge_tts
from loguru import logger

from app.story.character_parser import CharacterParser, DramatizedStory, StorySegment
from app.story.story_subtitle_builder import StorySubtitleBuilder, SegmentTiming
from app.audio.tts_engine import TTSEngine
from app.audio.bgm_mixer import BGMMixer
from app.core.config import settings

class AudiobookGenerator:
    """Service to automatically parse characters, synthesize multi-voice speech, and mix BGM."""

    @classmethod
    async def generate_single_segment_audio(
        cls,
        index: int,
        segment: StorySegment,
        output_dir: Path
    ) -> Optional[Path]:
        """Generate audio for a single dialogue/narration segment with specific character pitch and rate."""
        chunk_file = output_dir / f"seg_{index:04d}.mp3"
        config = CharacterParser.get_voice_config_for_type(segment.character_type)
        
        voice = config["voice"]
        pitch = config["pitch"]
        rate = config["rate"]

        try:
            communicate = edge_tts.Communicate(
                text=segment.text,
                voice=voice,
                rate=rate,
                pitch=pitch
            )
            await communicate.save(str(chunk_file))
            if chunk_file.exists() and os.path.getsize(chunk_file) > 0:
                return chunk_file
        except Exception as e:
            logger.warning(f"Error generating audio for segment #{index} ({segment.speaker_name}): {e}")
            # Fallback simple speech
            try:
                fb = edge_tts.Communicate(text=segment.text, voice="vi-VN-NamMinhNeural")
                await fb.save(str(chunk_file))
                if chunk_file.exists() and os.path.getsize(chunk_file) > 0:
                    return chunk_file
            except Exception:
                pass
        return None

    @classmethod
    def concatenate_audio_files(cls, audio_files: List[Path], output_path: Path) -> Path:
        """Concatenate multiple audio segment files into one seamless audio stream."""
        ffmpeg_bin = settings.FFMPEG_PATH
        list_file = output_path.parent / f"concat_list_{output_path.stem}.txt"

        with open(list_file, "w", encoding="utf-8") as f:
            for af in audio_files:
                escaped = str(af.resolve()).replace("\\", "/")
                f.write(f"file '{escaped}'\n")

        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(list_file),
            "-c:a", "libmp3lame",
            "-b:a", "192k",
            "-ar", "44100",
            str(output_path)
        ]

        logger.info(f"Concatenating {len(audio_files)} multi-voice audio clips...")
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="ignore")
        
        try:
            if list_file.exists():
                list_file.unlink()
        except Exception:
            pass

        if res.returncode != 0:
            logger.error(f"Audio concatenation failed: {res.stderr}")
            raise RuntimeError(f"FFmpeg audio concat error: {res.stderr}")

        return output_path

    @classmethod
    async def generate_story_audio(
        cls,
        story_id: int,
        content: str,
        aspect_ratio: str = "16:9",
        bgm_filename: Optional[str] = "suspense_bgm.mp3",
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Tuple[str, float, List[str], str]:
        """
        Auto-analyze characters, generate multi-voice dramatization audio, build synchronized subtitles, and mix BGM.
        Returns: (relative_audio_path, duration_seconds, characters_list, relative_ass_path)
        """
        work_dir = Path(f"media/working/stories/story_{story_id}")
        work_dir.mkdir(parents=True, exist_ok=True)

        final_dir = Path("media/working/stories")
        final_dir.mkdir(parents=True, exist_ok=True)
        
        raw_voice_path = final_dir / f"story_{story_id}_drama_raw.mp3"
        final_audio_path = final_dir / f"story_{story_id}_audio.mp3"
        final_ass_path = final_dir / f"story_{story_id}_subtitles.ass"

        if progress_callback:
            progress_callback(0.12, "AI đang đọc hiểu & phân tích dàn nhân vật...")

        # 1. AI Character & Dialogue Parsing
        logger.info(f"Analyzing characters and dramatizing Story #{story_id}...")
        drama_data: DramatizedStory = await CharacterParser.parse_story(content)
        
        char_count = len(drama_data.characters)
        seg_count = len(drama_data.segments)
        logger.info(f"Identified {char_count} characters: {', '.join(drama_data.characters)}")
        logger.info(f"Generating {seg_count} multi-voice dialogue tracks in parallel...")

        if progress_callback:
            progress_callback(0.25, f"AI nhận diện {char_count} nhân vật, đang bắt đầu tạo giọng đọc ({seg_count} đoạn)...")

        # 2. Parallel TTS Generation with Concurrency Control & Progress tracking
        semaphore = asyncio.Semaphore(6) # Up to 6 parallel Edge-TTS streams
        completed_count = 0

        async def _generate_task(idx, seg):
            nonlocal completed_count
            async with semaphore:
                chunk_res = await cls.generate_single_segment_audio(idx, seg, work_dir)
                completed_count += 1
                if progress_callback and seg_count > 0:
                    pct = 0.25 + (completed_count / seg_count) * 0.25
                    progress_callback(pct, f"Đang sinh giọng nhân vật ({completed_count}/{seg_count} đoạn thoại)...")
                return idx, seg, chunk_res

        tasks = [_generate_task(i, seg) for i, seg in enumerate(drama_data.segments)]
        results = await asyncio.gather(*tasks)
        
        # Sort results in original order
        results.sort(key=lambda x: x[0])
        valid_items = [(idx, seg, p) for idx, seg, p in results if p is not None and p.exists()]
        if not valid_items:
            raise RuntimeError("Failed to generate audio segments for story.")

        # 3. Calculate accurate timestamps for each dialogue segment
        timings: List[SegmentTiming] = []
        current_time = 0.0
        valid_chunks: List[Path] = []

        for idx, seg, chunk_path in valid_items:
            chunk_dur = await asyncio.to_thread(TTSEngine.get_audio_duration, str(chunk_path))
            if chunk_dur <= 0:
                chunk_dur = 1.0
            timings.append(
                SegmentTiming(
                    speaker_name=seg.speaker_name,
                    character_type=seg.character_type,
                    text=seg.text,
                    start_sec=current_time,
                    end_sec=current_time + chunk_dur
                )
            )
            current_time += chunk_dur
            valid_chunks.append(chunk_path)

        # 4. Generate synchronized ASS subtitle file
        await asyncio.to_thread(
            StorySubtitleBuilder.generate_story_ass,
            timings=timings,
            output_ass_path=final_ass_path,
            aspect_ratio=aspect_ratio
        )

        if progress_callback:
            progress_callback(0.52, "Đang ghép nối toàn bộ các đoạn thoại kịch...")

        # 5. Concatenate all audio segments into one continuous track
        await asyncio.to_thread(cls.concatenate_audio_files, valid_chunks, raw_voice_path)

        # 6. Clean up temporary segment files
        for chunk in valid_chunks:
            try:
                chunk.unlink()
            except Exception:
                pass
        try:
            work_dir.rmdir()
        except Exception:
            pass

        # 7. Get base duration
        duration = await asyncio.to_thread(TTSEngine.get_audio_duration, str(raw_voice_path))

        # 8. Mix with Background Music (if available)
        if bgm_filename and bgm_filename.strip() and bgm_filename != "none":
            bgm_full_path = Path("media/bgm") / bgm_filename
            if bgm_full_path.exists():
                if progress_callback:
                    progress_callback(0.56, "Đang hòa âm nhạc nền kịch tính (BGM Ducking)...")
                logger.info(f"Mixing BGM {bgm_filename} into multi-voice audio track for Story #{story_id}...")
                try:
                    await asyncio.to_thread(
                        BGMMixer.mix_voice_and_bgm,
                        voice_audio_path=str(raw_voice_path),
                        bgm_audio_path=str(bgm_full_path),
                        output_audio_path=str(final_audio_path),
                        ducking_ratio=4.5,
                        ducking_threshold=0.12,
                        bgm_base_volume=0.22
                    )
                    duration = await asyncio.to_thread(TTSEngine.get_audio_duration, str(final_audio_path))
                except Exception as e:
                    logger.warning(f"BGM mixing failed ({e}), using raw voice audio.")
                    if raw_voice_path.exists():
                        if final_audio_path.exists():
                            final_audio_path.unlink()
                        raw_voice_path.rename(final_audio_path)
            else:
                if raw_voice_path.exists():
                    if final_audio_path.exists():
                        final_audio_path.unlink()
                    raw_voice_path.rename(final_audio_path)
        else:
            if raw_voice_path.exists():
                if final_audio_path.exists():
                    final_audio_path.unlink()
                raw_voice_path.rename(final_audio_path)

        if progress_callback:
            progress_callback(0.60, f"Đã hoàn tất âm thanh kịch ({duration:.1f}s) & phụ đề!")

        rel_path = str(final_audio_path).replace("\\", "/")
        rel_ass = str(final_ass_path).replace("\\", "/")
        return rel_path, duration, drama_data.characters, rel_ass
