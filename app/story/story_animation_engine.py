import os
import re
import json
import asyncio
import subprocess
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
from PIL import Image
from loguru import logger

from app.core.config import settings
from app.audio.tts_engine import TTSEngine
from app.story.character_parser import CharacterParser, DramatizedStory, StorySegment
from app.story.story_image_generator import StoryImageGenerator
from app.story.story_video_renderer import StoryVideoRenderer
from app.video.ai_video_generator import AIVideoGenerator

class StoryAnimationEngine:
    """
    AI Multi-Shot Story & Comic Animation Pipeline (inspired by PRINTFILM architecture).
    Translates stories and comics into sequential animated shot clips:
    1. Character Bible & World Extraction (Dựng nhân vật & phong cách nhất quán)
    2. Scene & Shot Breakdown (Phân rã cảnh, hành động & lời thoại nhân vật)
    3. Per-Shot Visual Extraction / AI Generation (Tạo khung hình riêng biệt cho từng hành động)
    4. Per-Shot Character Voice & Lip-sync Audio Synthesis
    5. Motion & Camera Animation (Dynamic Pan, Zoom & Seedance 2.5/OpenAI Videos)
    6. Episode Composition & BGM Mixing (Ghép nối thành phim hoạt hình hoàn chỉnh)
    """

    @classmethod
    async def generate_character_bible(
        cls,
        title: str,
        content: str
    ) -> List[Dict[str, Any]]:
        """
        Extracts Character Bible from story content: names, character types, roles,
        visual appearance descriptions, and TTS voice settings.
        """
        parsed: DramatizedStory = await CharacterParser.parse_story(content)
        characters_dict: Dict[str, Dict[str, Any]] = {}

        # Collect speakers and their roles
        for seg in parsed.segments:
            name = seg.speaker_name
            if name not in characters_dict:
                vcfg = CharacterParser.get_voice_config_for_type(seg.character_type)
                role = "Người dẫn chuyện" if seg.character_type == "narrator" else f"Nhân vật ({seg.character_type})"
                
                # Visual prompt formula for character consistency
                visual_prompt = (
                    f"Character portrait of {name}, {role}, cinematic lighting, "
                    f"highly expressive face, digital anime art style, 8k resolution, masterpiece"
                )

                characters_dict[name] = {
                    "name": name,
                    "character_type": seg.character_type,
                    "role": role,
                    "dialogue_count": 1,
                    "voice": vcfg["voice"],
                    "pitch": vcfg["pitch"],
                    "rate": vcfg["rate"],
                    "visual_prompt": visual_prompt
                }
            else:
                characters_dict[name]["dialogue_count"] += 1

        return list(characters_dict.values())

    @classmethod
    async def breakdown_story_to_shots(
        cls,
        title: str,
        content: str
    ) -> List[Dict[str, Any]]:
        """
        Parses story into discrete cinematic shots/scenes.
        """
        parsed: DramatizedStory = await CharacterParser.parse_story(content)
        shots: List[Dict[str, Any]] = []

        camera_motions = [
            "Push-in (Cận cảnh đẩy chậm)",
            "Pull-out (Toàn cảnh lùi dần)",
            "Pan-right (Lướt máy sang phải)",
            "Pan-left & Tilt (Lướt máy sang trái & hất góc)"
        ]

        for idx, seg in enumerate(parsed.segments):
            text = seg.text.strip()
            if not text:
                continue

            voice_cfg = CharacterParser.get_voice_config_for_type(seg.character_type)
            cam_motion = camera_motions[idx % len(camera_motions)]
            
            shots.append({
                "shot_no": idx + 1,
                "speaker_name": seg.speaker_name,
                "character_type": seg.character_type,
                "emotion": seg.emotion,
                "camera_cue": seg.camera_cue or "medium_shot",
                "camera_motion": cam_motion,
                "scene_context": seg.scene_context or f"Cảnh {idx + 1}",
                "text": text,
                "voice_cfg": voice_cfg
            })

        return shots

    @classmethod
    def slice_comic_reference(
        cls,
        comic_path: Path,
        output_dir: Path,
        target_shots: int
    ) -> List[Path]:
        """
        Smartly slices a multi-panel comic or strip into individual character action frames.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        img = Image.open(comic_path).convert("RGB")
        w, h = img.size

        slices: List[Path] = []
        is_vertical_split = h > w * 0.7  # Has multiple vertical tiers (like 2-panel comic)

        if is_vertical_split:
            # 4 primary focus regions for 2-panel comic:
            # 1. Top-left (Action 1)
            # 2. Top-right (Reaction 1)
            # 3. Bottom-left (Action 2)
            # 4. Bottom-right (Reaction 2)
            regions = [
                (0, 0, int(w * 0.65), int(h * 0.50)),
                (int(w * 0.40), 0, w, int(h * 0.50)),
                (0, int(h * 0.48), int(w * 0.68), h),
                (int(w * 0.42), int(h * 0.48), w, h),
            ]
            for i in range(target_shots):
                box = regions[i % len(regions)]
                cropped = img.crop(box)
                dest = output_dir / f"comic_slice_{i + 1:02d}.jpg"
                cropped.save(dest, format="JPEG", quality=95)
                slices.append(dest)
        else:
            # Horizontal strip: slice left-to-right
            for i in range(target_shots):
                step = w / target_shots
                box = (int(i * step), 0, int((i + 1) * step), h)
                cropped = img.crop(box)
                dest = output_dir / f"comic_slice_{i + 1:02d}.jpg"
                cropped.save(dest, format="JPEG", quality=95)
                slices.append(dest)

        return slices

    @classmethod
    def fit_image_to_canvas(
        cls,
        img_path: Path,
        dest_path: Path,
        width: int,
        height: int,
        bg_color: str = "#111827"
    ) -> Path:
        """
        Fits a sliced image onto a vertical (9:16) or horizontal (16:9) frame with blur background.
        """
        img = Image.open(img_path).convert("RGB")
        iw, ih = img.size

        canvas = Image.new("RGB", (width, height), color=bg_color)
        scale = min(width / iw, height / ih)
        nw, nh = max(int(iw * scale), 1), max(int(ih * scale), 1)
        resized = img.resize((nw, nh), Image.Resampling.LANCZOS)

        ox = (width - nw) // 2
        oy = (height - nh) // 2
        canvas.paste(resized, (ox, oy))
        canvas.save(dest_path, format="JPEG", quality=95)
        return dest_path

    @classmethod
    async def generate_storyboard_breakdown(
        cls,
        story_id: int,
        title: str,
        content: str,
        reference_image_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Produces complete Storyboard Package for Studio Review (PRINTFILM 分镜列表 Architecture):
        - Character Bible
        - Detailed Shot Breakdown: titles, durations, camera motion tags, dialogue tags, clip readiness
        """
        work_dir = Path(f"media/working/stories/storyboard_{story_id}")
        work_dir.mkdir(parents=True, exist_ok=True)
        anim_work_dir = Path(f"media/working/stories/anim_{story_id}")
        anim_work_dir.mkdir(parents=True, exist_ok=True)

        characters = await cls.generate_character_bible(title, content)
        shots = await cls.breakdown_story_to_shots(title, content)

        ref_path = Path(reference_image_path) if reference_image_path else None
        comic_slices: List[Path] = []
        if ref_path and ref_path.exists():
            comic_slices = cls.slice_comic_reference(ref_path, work_dir / "slices", len(shots))

        shot_templates = [
            "Mở đầu / Hook",
            "Bối cảnh & Khám phá",
            "Diễn biến 1",
            "Diễn biến 2",
            "Cao trào & Kịch tính",
            "Kêu gọi & Kết thúc"
        ]

        storyboard_shots: List[Dict[str, Any]] = []
        for idx, shot in enumerate(shots):
            shot_no = shot["shot_no"]
            thumb_rel = f"media/working/stories/storyboard_{story_id}/thumb_{shot_no:02d}.jpg"
            thumb_path = Path(thumb_rel)

            if comic_slices and idx < len(comic_slices):
                cls.fit_image_to_canvas(comic_slices[idx], thumb_path, 540, 960)
            else:
                if not thumb_path.exists():
                    StoryImageGenerator._create_fallback_gradient(thumb_path, 540, 960)

            # Estimate duration based on word count (~3 words per second)
            word_count = len(shot["text"].split())
            dur_sec = max(4, min(14, int(round(word_count / 3.0 + 2))))
            dur_str = f"00:{dur_sec:02d}"

            # Check if this shot clip has already been rendered
            clip_file = anim_work_dir / f"clip_{shot_no:02d}.mp4"
            is_ready = clip_file.exists() and clip_file.stat().st_size > 2000
            status = "ready" if is_ready else "need_clip"
            clip_url = f"/media/working/stories/anim_{story_id}/clip_{shot_no:02d}.mp4?t={int(clip_file.stat().st_mtime)}" if is_ready else None

            # Sub-segment breakdown tags (like PRINTFILM 逐段分镜: [3s] Camera motion, [5s] Dialogue)
            motion_dur = max(2, int(dur_sec * 0.4))
            speech_dur = dur_sec - motion_dur
            v_voice_clean = shot["voice_cfg"]["voice"].split("-")[-1]

            camera_tag = f"[{motion_dur}s] {shot['camera_cue']}: {shot['camera_motion']}"
            dialogue_tag = f"[{speech_dur}s] 【{shot['speaker_name']} · Giọng {v_voice_clean} · Subtitle đồng bộ】"

            title_label = shot_templates[idx % len(shot_templates)]
            visual_prompt = (
                f"Cinematic {shot['camera_cue']} of {shot['speaker_name']}, emotion: {shot['emotion']}. "
                f"Action: {shot['text'][:120]}"
            )

            storyboard_shots.append({
                **shot,
                "section_title": title_label,
                "duration_str": dur_str,
                "duration_sec": dur_sec,
                "status": status,
                "clip_url": clip_url,
                "camera_tag": camera_tag,
                "dialogue_tag": dialogue_tag,
                "thumbnail_url": f"/{thumb_rel.replace('\\', '/')}",
                "visual_prompt": visual_prompt
            })

        return {
            "story_id": story_id,
            "title": title,
            "total_shots": len(storyboard_shots),
            "characters": characters,
            "shots": storyboard_shots
        }

    @classmethod
    async def render_single_shot(
        cls,
        story_id: int,
        shot_no: int,
        title: str,
        content: str,
        aspect_ratio: str = "9:16",
        video_engine: str = "motion_25d",
        reference_image_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Renders an individual shot clip (corresponding to PRINTFILM '出视频' / '重生视频' button).
        """
        shots = await cls.breakdown_story_to_shots(title, content)
        target_shot = next((s for s in shots if s["shot_no"] == shot_no), None)
        if not target_shot:
            raise ValueError(f"Không tìm thấy phân cảnh #{shot_no}")

        work_dir = Path(f"media/working/stories/anim_{story_id}")
        work_dir.mkdir(parents=True, exist_ok=True)
        sb_dir = Path(f"media/working/stories/storyboard_{story_id}")

        width, height = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        ffmpeg_bin = settings.FFMPEG_PATH

        # 1. Frame Image
        shot_frame_path = work_dir / f"frame_{shot_no:02d}.jpg"
        thumb_source = sb_dir / f"thumb_{shot_no:02d}.jpg"
        if thumb_source.exists():
            cls.fit_image_to_canvas(thumb_source, shot_frame_path, width, height)
        else:
            StoryImageGenerator._create_fallback_gradient(shot_frame_path, width, height)

        # 2. Character Audio
        audio_shot_path = work_dir / f"audio_{shot_no:02d}.mp3"
        vcfg = target_shot["voice_cfg"]
        _, _, shot_dur = await TTSEngine.generate_speech_with_timestamps(
            text=target_shot["text"],
            output_audio_path=str(audio_shot_path),
            voice=vcfg["voice"],
            pitch=vcfg["pitch"],
            rate=vcfg["rate"]
        )
        if shot_dur <= 0:
            shot_dur = 3.5

        # 3. Subtitle
        txt_path = work_dir / f"text_{shot_no:02d}.txt"
        speaker_label = f"[{target_shot['speaker_name']}]: " if target_shot['character_type'] != "narrator" else ""
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(f"{speaker_label}{target_shot['text']}")
        escaped_txt = str(txt_path.resolve()).replace("\\", "/").replace(":", "\\:")

        font_path = StoryVideoRenderer._find_usable_font()
        font_opt = f":fontfile='{font_path.replace(':', chr(92) + ':')}'" if font_path else ""

        # 4. Render Clip
        shot_vid_dest = work_dir / f"clip_{shot_no:02d}.mp4"
        raw_shot_motion = work_dir / f"raw_motion_{shot_no:02d}.mp4"
        use_ai_video = (video_engine in ["seedance", "ai_video", "openai_video"])

        ai_video_success = False
        if use_ai_video:
            prompt_motion = f"Character {target_shot['speaker_name']} {target_shot['emotion']}, {target_shot['text'][:100]}"
            ai_video_success = await AIVideoGenerator.generate_shot_video_clip(
                image_path=shot_frame_path,
                prompt=prompt_motion,
                duration=shot_dur,
                dest_path=raw_shot_motion,
                aspect_ratio=aspect_ratio,
                motion_pattern=shot_no - 1
            )

        sub_y = int(height * 0.82) if aspect_ratio == "9:16" else int(height * 0.85)
        font_size = 32 if aspect_ratio == "9:16" else 36
        box_h = int(height * 0.16) if aspect_ratio == "9:16" else int(height * 0.14)

        if ai_video_success and raw_shot_motion.exists():
            caption_vf = (
                f"[0:v]drawbox=x=0:y={sub_y - 20}:w=iw:h={box_h}:color=black@0.60:t=fill,"
                f"drawtext=textfile='{escaped_txt}'{font_opt}:fontsize={font_size}:fontcolor=yellow:"
                f"x=(w-text_w)/2:y={sub_y}:shadowcolor=black@0.9:shadowx=2:shadowy=2[v]"
            )
            cmd = [
                ffmpeg_bin, "-y", "-threads", "0",
                "-i", str(raw_shot_motion.resolve()),
                "-i", str(audio_shot_path.resolve()),
                "-filter_complex", caption_vf,
                "-map", "[v]", "-map", "1:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                "-c:a", "aac", "-pix_fmt", "yuv420p", "-t", f"{shot_dur:.3f}",
                str(shot_vid_dest)
            ]
        else:
            kb_filter = StoryVideoRenderer.build_ken_burns_filter(
                width=width, height=height, duration=shot_dur,
                pattern_idx=shot_no - 1, intensity=0.18, fps=24
            )
            caption_vf = (
                f"[0:v]{kb_filter},"
                f"drawbox=x=0:y={sub_y - 20}:w=iw:h={box_h}:color=black@0.60:t=fill,"
                f"drawtext=textfile='{escaped_txt}'{font_opt}:fontsize={font_size}:fontcolor=yellow:"
                f"x=(w-text_w)/2:y={sub_y}:shadowcolor=black@0.9:shadowx=2:shadowy=2[v]"
            )
            cmd = [
                ffmpeg_bin, "-y", "-threads", "0",
                "-loop", "1", "-i", str(shot_frame_path.resolve()),
                "-i", str(audio_shot_path.resolve()),
                "-filter_complex", caption_vf,
                "-map", "[v]", "-map", "1:a",
                "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                "-c:a", "aac", "-pix_fmt", "yuv420p", "-t", f"{shot_dur:.3f}",
                str(shot_vid_dest)
            ]

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        clip_rel = f"/media/working/stories/anim_{story_id}/clip_{shot_no:02d}.mp4?t={int(shot_vid_dest.stat().st_mtime)}"
        return {
            "status": "success",
            "shot_no": shot_no,
            "clip_url": clip_rel,
            "duration": shot_dur,
            "message": f"Render phân cảnh #{shot_no} thành công!"
        }

    @classmethod
    async def concat_shots_to_movie(
        cls,
        story_id: int,
        aspect_ratio: str = "9:16",
        bgm_name: str = "suspense_bgm.mp3"
    ) -> str:
        """
        Concatenates all rendered shot clips into a seamless master video (PRINTFILM '拼接成片' button).
        """
        work_dir = Path(f"media/working/stories/anim_{story_id}")
        output_dir = Path("media/output/stories")
        output_dir.mkdir(parents=True, exist_ok=True)
        final_video_path = output_dir / f"story_{story_id}_{aspect_ratio.replace(':', 'x')}_anim.mp4"
        ffmpeg_bin = settings.FFMPEG_PATH

        # Find all shot clips sorted by shot_no
        shot_clips = sorted(work_dir.glob("clip_*.mp4"), key=lambda p: p.name)
        if not shot_clips:
            raise RuntimeError("Chưa có phân cảnh nào được render. Vui lòng tạo video cho các phân cảnh trước.")

        concat_list_file = work_dir / "concat_final.txt"
        concat_list_file.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in shot_clips),
            encoding="utf-8"
        )
        merged_video = work_dir / "merged_final.mp4"

        concat_cmd = [
            ffmpeg_bin, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(merged_video)
        ]
        subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        # Mix BGM
        bgm_path = Path("media/bgm") / bgm_name
        if bgm_path.exists():
            mix_cmd = [
                ffmpeg_bin, "-y",
                "-i", str(merged_video),
                "-stream_loop", "-1",
                "-i", str(bgm_path.resolve()),
                "-filter_complex", "[1:a]volume=0.18[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(final_video_path)
            ]
            subprocess.run(mix_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        else:
            if final_video_path.exists():
                final_video_path.unlink()
            merged_video.rename(final_video_path)

        return str(final_video_path).replace("\\", "/")

    @classmethod
    async def render_story_animation(
        cls,
        story_id: int,
        title: str,
        content: str,
        author: str = "Tác giả",
        reference_image_path: Optional[str] = None,
        aspect_ratio: str = "9:16",
        video_engine: str = "motion_25d",
        bgm_name: str = "suspense_bgm.mp3",
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> str:
        """
        End-to-end execution of the Multi-Shot Animation Engine.
        Supports both 2.5D Motion and Generative AI Video (Seedance / OpenAI Videos).
        """
        output_dir = Path("media/output/stories")
        output_dir.mkdir(parents=True, exist_ok=True)
        final_video_path = output_dir / f"story_{story_id}_{aspect_ratio.replace(':', 'x')}_anim.mp4"

        work_dir = Path(f"media/working/stories/anim_{story_id}")
        work_dir.mkdir(parents=True, exist_ok=True)

        width, height = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        ffmpeg_bin = settings.FFMPEG_PATH

        if progress_callback:
            progress_callback(0.05, "Đang phân tích kịch bản thành từng cảnh quay nhân vật (Shot Breakdown)...")

        # 1. Shot Breakdown
        shots = await cls.breakdown_story_to_shots(title, content)
        if not shots:
            raise ValueError("Kịch bản không có nội dung phân cảnh hợp lệ.")
        total_shots = len(shots)
        logger.info(f"Story #{story_id} split into {total_shots} animated shots using engine '{video_engine}'.")

        # 2. Prepare visual frame for each shot
        if progress_callback:
            progress_callback(0.15, "Đang chuẩn bị khung hình cho từng phân cảnh...")

        ref_path = Path(reference_image_path) if reference_image_path else None
        comic_slices: List[Path] = []
        if ref_path and ref_path.exists():
            comic_slices = cls.slice_comic_reference(ref_path, work_dir / "slices", total_shots)

        shot_clips: List[Path] = []
        for idx, shot in enumerate(shots):
            shot_no = shot["shot_no"]
            if progress_callback:
                pct = 0.20 + (idx / total_shots) * 0.60
                progress_callback(pct, f"Đang diễn hoạt phân cảnh #{shot_no}/{total_shots}: {shot['speaker_name']}...")

            # 2a. Visual Image for shot
            shot_frame_path = work_dir / f"frame_{shot_no:02d}.jpg"
            if comic_slices and idx < len(comic_slices):
                cls.fit_image_to_canvas(comic_slices[idx], shot_frame_path, width, height)
            else:
                # Generate AI illustration for this specific shot action
                prompt = (
                    f"Cinematic {shot['camera_cue']} for '{title}'. "
                    f"Character: {shot['speaker_name']} showing {shot['emotion']} expression. "
                    f"Action: {shot['text'][:140]}. Highly detailed 8k, digital anime art masterpiece"
                )
                success = await asyncio.to_thread(
                    StoryImageGenerator._download_image_sync,
                    prompt=prompt,
                    output_path=shot_frame_path,
                    width=width,
                    height=height
                )
                if not success or not shot_frame_path.exists():
                    StoryImageGenerator._create_fallback_gradient(shot_frame_path, width, height)

            # 2b. Synthesize Character Audio for this shot
            audio_shot_path = work_dir / f"audio_{shot_no:02d}.mp3"
            vcfg = shot["voice_cfg"]
            _, _, shot_dur = await TTSEngine.generate_speech_with_timestamps(
                text=shot["text"],
                output_audio_path=str(audio_shot_path),
                voice=vcfg["voice"],
                pitch=vcfg["pitch"],
                rate=vcfg["rate"]
            )

            if shot_dur <= 0:
                shot_dur = 3.5

            # 2c. Subtitle / Dialogue Caption text file
            txt_path = work_dir / f"text_{shot_no:02d}.txt"
            speaker_label = f"[{shot['speaker_name']}]: " if shot['character_type'] != "narrator" else ""
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(f"{speaker_label}{shot['text']}")
            escaped_txt = str(txt_path.resolve()).replace("\\", "/").replace(":", "\\:")

            font_path = StoryVideoRenderer._find_usable_font()
            font_opt = f":fontfile='{font_path.replace(':', chr(92) + ':')}'" if font_path else ""

            # 2d. Render Animated Shot Video Clip
            shot_vid_dest = work_dir / f"clip_{shot_no:02d}.mp4"
            
            # If AI Video Generator is chosen (Seedance / OpenAI Videos), try it
            raw_shot_motion = work_dir / f"raw_motion_{shot_no:02d}.mp4"
            use_ai_video = (video_engine in ["seedance", "ai_video", "openai_video"])
            
            ai_video_success = False
            if use_ai_video:
                prompt_motion = f"Character {shot['speaker_name']} {shot['emotion']}, {shot['text'][:100]}"
                ai_video_success = await AIVideoGenerator.generate_shot_video_clip(
                    image_path=shot_frame_path,
                    prompt=prompt_motion,
                    duration=shot_dur,
                    dest_path=raw_shot_motion,
                    aspect_ratio=aspect_ratio,
                    motion_pattern=idx
                )

            # Styled bottom subtitle box
            sub_y = int(height * 0.82) if aspect_ratio == "9:16" else int(height * 0.85)
            font_size = 32 if aspect_ratio == "9:16" else 36
            box_h = int(height * 0.16) if aspect_ratio == "9:16" else int(height * 0.14)

            if ai_video_success and raw_shot_motion.exists():
                # Overlay audio & subtitles on AI Video clip
                caption_vf = (
                    f"[0:v]drawbox=x=0:y={sub_y - 20}:w=iw:h={box_h}:color=black@0.60:t=fill,"
                    f"drawtext=textfile='{escaped_txt}'{font_opt}:fontsize={font_size}:fontcolor=yellow:"
                    f"x=(w-text_w)/2:y={sub_y}:shadowcolor=black@0.9:shadowx=2:shadowy=2[v]"
                )
                cmd = [
                    ffmpeg_bin, "-y",
                    "-threads", "0",
                    "-i", str(raw_shot_motion.resolve()),
                    "-i", str(audio_shot_path.resolve()),
                    "-filter_complex", caption_vf,
                    "-map", "[v]",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-pix_fmt", "yuv420p",
                    "-t", f"{shot_dur:.3f}",
                    str(shot_vid_dest)
                ]
            else:
                # Resilient 2.5D Ken Burns Dynamic Camera Engine
                kb_filter = StoryVideoRenderer.build_ken_burns_filter(
                    width=width,
                    height=height,
                    duration=shot_dur,
                    pattern_idx=idx,
                    intensity=0.18,
                    fps=24
                )
                caption_vf = (
                    f"[0:v]{kb_filter},"
                    f"drawbox=x=0:y={sub_y - 20}:w=iw:h={box_h}:color=black@0.60:t=fill,"
                    f"drawtext=textfile='{escaped_txt}'{font_opt}:fontsize={font_size}:fontcolor=yellow:"
                    f"x=(w-text_w)/2:y={sub_y}:shadowcolor=black@0.9:shadowx=2:shadowy=2[v]"
                )
                cmd = [
                    ffmpeg_bin, "-y",
                    "-threads", "0",
                    "-loop", "1",
                    "-i", str(shot_frame_path.resolve()),
                    "-i", str(audio_shot_path.resolve()),
                    "-filter_complex", caption_vf,
                    "-map", "[v]",
                    "-map", "1:a",
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "20",
                    "-c:a", "aac",
                    "-pix_fmt", "yuv420p",
                    "-t", f"{shot_dur:.3f}",
                    str(shot_vid_dest)
                ]

            res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            if res.returncode == 0 and shot_vid_dest.exists() and shot_vid_dest.stat().st_size > 0:
                shot_clips.append(shot_vid_dest)

        if not shot_clips:
            raise RuntimeError("Không thể tạo các video phân cảnh cho truyện.")

        # 3. Concatenate all shot clips together
        if progress_callback:
            progress_callback(0.85, "Đang ghép nối các phân cảnh thành phim hoạt hình...")

        concat_list_file = work_dir / "concat.txt"
        concat_list_file.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in shot_clips),
            encoding="utf-8"
        )
        merged_video = work_dir / "merged_anim.mp4"

        concat_cmd = [
            ffmpeg_bin, "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_list_file),
            "-c", "copy",
            "-movflags", "+faststart",
            str(merged_video)
        ]
        subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)

        # 4. Mix BGM if available
        bgm_path = Path("media/bgm") / bgm_name
        if bgm_path.exists():
            if progress_callback:
                progress_callback(0.92, "Đang hòa âm nhạc nền cảm xúc...")
            mix_cmd = [
                ffmpeg_bin, "-y",
                "-i", str(merged_video),
                "-stream_loop", "-1",
                "-i", str(bgm_path.resolve()),
                "-filter_complex", "[1:a]volume=0.18[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=2[a]",
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac",
                "-movflags", "+faststart",
                str(final_video_path)
            ]
            subprocess.run(mix_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        else:
            if final_video_path.exists():
                final_video_path.unlink()
            merged_video.rename(final_video_path)

        if progress_callback:
            progress_callback(1.0, "Hoàn tất tạo video hoạt hình đa phân cảnh!")

        logger.info(f"Story Animation #{story_id} rendered successfully -> {final_video_path}")
        return str(final_video_path).replace("\\", "/")
