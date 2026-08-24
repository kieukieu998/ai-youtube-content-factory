import os
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger

from app.database.session import SessionLocal
from app.database.models import Job, Movie, MovieSource, Script, Episode, MediaFile, Video, Setting
from app.core.config import settings

# Agents and Services
from app.agents.hunter import MovieHunterAgent
from app.agents.analyst import MovieAnalystAgent
from app.agents.script_writer import ScriptWriterAgent
from app.agents.hook_generator import HookGeneratorAgent
from app.agents.voice_agent import VoiceAgent
from app.agents.subtitle_agent import SubtitleAgent
from app.agents.scene_selector import SceneSelectorAgent
from app.agents.video_editor import VideoEditorAgent
from app.agents.qa_agent import QAAgent
from app.agents.seo_agent import SEOAgent
from app.video.scene_slicer import SceneSlicer

def format_duration_str(seconds: float | int | None) -> str:
    """Format duration into digital timecode format: MM:SS or H:MM:SS (e.g. 01:06, 17:51, 3:35:36)"""
    if seconds is None or seconds <= 0:
        return "00:00"
    secs = int(round(seconds))
    mins = secs // 60
    rem_secs = secs % 60
    hours = mins // 60
    rem_mins = mins % 60
    if hours > 0:
        return f"{hours}:{rem_mins:02d}:{rem_secs:02d}"
    else:
        return f"{rem_mins:02d}:{rem_secs:02d}"


class JobWorker:
    """Background Async Poller and Dispatcher for SQLite Jobs queue."""
    
    _is_running = False
    _emergency_stop = False

    @classmethod
    def set_emergency_stop(cls, stop: bool = True):
        cls._emergency_stop = stop
        logger.warning(f"SYSTEM EMERGENCY STOP set to: {stop}")

    @classmethod
    def _is_job_cancelled(cls, db, job_id: int) -> bool:
        """Check if job was cancelled by user or emergency stop triggered."""
        if cls._emergency_stop:
            return True
        try:
            db.expire_all()
            status = db.query(Job.status).filter(Job.id == job_id).scalar()
            return status == "cancelled"
        except Exception:
            return False

    @classmethod
    async def start_worker_loop(cls):
        """Infinite loop polling pending jobs from database."""
        cls._is_running = True
        logger.info("Starting Background Job Worker Loop...")
        while cls._is_running:
            try:
                if not cls._emergency_stop:
                    await cls._process_next_job()
            except Exception as e:
                logger.error(f"Error in job worker loop: {e}")
            await asyncio.sleep(2.0)

    @classmethod
    async def _process_next_job(cls):
        db = SessionLocal()
        try:
            job = db.query(Job).filter(Job.status == "pending").order_by(Job.created_at.asc()).first()
            if not job:
                return

            job.status = "processing"
            job.progress = 10
            job.updated_at = datetime.utcnow()
            db.commit()

            logger.info(f"Processing Job #{job.id} [{job.job_type}]...")
            payload = json.loads(job.payload) if job.payload else {}

            if job.job_type == "MovieDiscoveryJob":
                await cls._handle_movie_discovery(db, job, payload)
            elif job.job_type == "ScriptGenerationJob":
                await cls._handle_script_generation(db, job, payload)
            elif job.job_type == "RenderEpisodeJob":
                await cls._handle_render_episode(db, job, payload)
            elif job.job_type == "VideoTransformJob":
                await cls._handle_video_transform(db, job, payload)
            else:
                job.status = "completed"
                job.progress = 100
                db.commit()

        except Exception as e:
            logger.error(f"Job execution failed: {e}")
            if 'job' in locals() and job:
                if not cls._is_job_cancelled(db, job.id):
                    job.status = "failed"
                    job.error_message = str(e)
                    db.commit()
        finally:
            db.close()

    @classmethod
    async def _handle_movie_discovery(cls, db, job: Job, payload: Dict[str, Any]):
        genre = payload.get("genre", "Hành Động, Kinh Dị")
        limit = payload.get("limit", 3)
        
        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before starting discovery.")
            return

        # Query existing movies to prevent duplicates
        existing_movies = db.query(Movie).all()
        existing_titles = [m.title for m in existing_movies] + [m.original_title for m in existing_movies if m.original_title]
        
        hunter = MovieHunterAgent()
        candidates = await hunter.discover_movies(genre=genre, limit=limit, existing_titles=existing_titles)
        
        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after movie discovery.")
            return

        job.progress = 50
        db.commit()

        created_movies = []

        for c in candidates:
            if cls._is_job_cancelled(db, job.id):
                logger.warning(f"Job #{job.id} cancelled during movie trailer downloads.")
                return

            movie = Movie(
                title=c.title,
                original_title=c.original_title,
                release_year=c.release_year,
                genre=c.genre,
                duration_minutes=c.duration_minutes,
                synopsis=c.synopsis,
                potential_score=c.potential_score,
                status="discovered"
            )
            db.add(movie)
            db.flush()

            # Auto-fetch trailer from YouTube asynchronously in worker thread
            try:
                from app.video.youtube_downloader import YouTubeTrailerDownloader, slugify_filename
                search_query = f"{c.original_title or c.title} {c.release_year or ''}"
                clean_prefix = slugify_filename(c.title, c.release_year, fallback_title=c.original_title)
                trailer_file = await asyncio.to_thread(
                    YouTubeTrailerDownloader.download_trailer,
                    query_or_url=search_query,
                    output_dir=str(settings.SOURCE_MEDIA_DIR),
                    filename_prefix=clean_prefix
                )
                if trailer_file:
                    source = MovieSource(
                        movie_id=movie.id,
                        source_type="youtube_trailer",
                        file_path=trailer_file,
                        is_verified=True
                    )
                    db.add(source)
            except Exception as e:
                logger.warning(f"Could not auto-fetch trailer for {c.title}: {e}")

            created_movies.append(f"{movie.title} ({movie.original_title})")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before final save.")
            return

        job.status = "completed"
        job.progress = 100
        job.error_message = None
        job.result = f"Đã tìm thấy {len(created_movies)} phim mới kèm Trailer: {', '.join(created_movies)}"
        db.commit()
        logger.info(f"Job #{job.id} completed. Added {len(created_movies)} movies.")

    @classmethod
    async def _handle_script_generation(cls, db, job: Job, payload: Dict[str, Any]):
        movie_id = payload.get("movie_id")
        target_episodes = int(payload.get("target_episodes", 3))
        target_duration_seconds = int(payload.get("target_duration_seconds", 60))
        style = payload.get("style", "dramatic")
        ai_provider = payload.get("ai_provider")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before script generation.")
            return

        movie = db.query(Movie).filter(Movie.id == movie_id).first()
        if not movie:
            raise ValueError(f"Movie ID {movie_id} not found")

        # 1. Analyst
        job.progress = 20
        job.result = "Đang phân tích cốt truyện & cao trào phim..."
        db.commit()

        analyst = MovieAnalystAgent(provider_type=ai_provider)
        analysis = await analyst.analyze_movie(
            title=movie.title, 
            synopsis=movie.synopsis or "", 
            genre=movie.genre or "",
            target_episodes=target_episodes
        )

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after movie analysis.")
            return

        job.progress = 50
        job.result = f"Đang viết {target_episodes} tập kịch bản ({target_duration_seconds // 60} phút)..."
        db.commit()

        # 2. Script Writer
        writer = ScriptWriterAgent(provider_type=ai_provider)
        script_pkg = await writer.generate_scripts(
            movie_title=movie.title, 
            analysis=analysis,
            style=style,
            target_episodes=target_episodes,
            target_duration_seconds=target_duration_seconds
        )

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after script writing.")
            return

        job.progress = 85
        job.result = "Đang lưu kịch bản và phân cảnh vào cơ sở dữ liệu..."
        db.commit()

        # 3. Clean up any existing old scripts for this movie (1 movie = 1 script folder)
        old_scripts = db.query(Script).filter(Script.movie_id == movie.id).all()
        for old_s in old_scripts:
            db.delete(old_s)
        db.flush()

        # Create new Script entity
        script = Script(
            movie_id=movie.id,
            title=f"Kịch Bản Review – {movie.title}",
            style=style,
            target_episodes=len(script_pkg.episodes)
        )
        db.add(script)
        db.flush()

        mode_setting = db.query(Setting).filter(Setting.key == "operation_mode").first()
        auto_mode = (mode_setting.value == "full_auto") if mode_setting else False
        episode_status = "approved" if auto_mode else "approval_pending"

        for ep_data in script_pkg.episodes:
            episode = Episode(
                script_id=script.id,
                episode_number=ep_data.episode_number,
                hook_text=ep_data.hook_draft,
                content_text=ep_data.narrative_body,
                call_to_action=ep_data.call_to_action,
                status=episode_status
            )
            db.add(episode)

        movie.status = "scripted"

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before script completion.")
            return

        job.status = "completed"
        job.progress = 100
        job.error_message = None
        job.result = f"Hoàn thành {len(script_pkg.episodes)} tập kịch bản (Đã đưa vào danh sách chờ duyệt)"
        db.commit()
        logger.info(f"Job #{job.id} completed. Generated {len(script_pkg.episodes)} episodes for Movie {movie.title}")

    @classmethod
    async def _handle_render_episode(cls, db, job: Job, payload: Dict[str, Any]):
        episode_id = payload.get("episode_id")
        episode = db.query(Episode).filter(Episode.id == episode_id).first()
        if not episode:
            raise ValueError(f"Episode ID {episode_id} not found")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before render start.")
            return

        working_dir = settings.WORKING_MEDIA_DIR / f"ep_{episode.id}"
        working_dir.mkdir(parents=True, exist_ok=True)

        # 0. Optional AI Script Refinement if user provided custom instruction
        custom_instruction = payload.get("custom_instruction")
        if custom_instruction and custom_instruction.strip():
            job.progress = 10
            short_inst = custom_instruction.strip()[:50]
            job.result = f"AI đang tinh chỉnh kịch bản: \"{short_inst}...\""
            db.commit()

            try:
                from app.agents.script_writer import ScriptWriterAgent
                writer = ScriptWriterAgent()
                movie_title = episode.script.movie.title if (episode.script and episode.script.movie) else "Bộ Phim"
                total_episodes = len(episode.script.episodes) if (episode.script and episode.script.episodes) else 1
                rewritten = await writer.rewrite_single_episode(
                    movie_title=movie_title,
                    episode_number=episode.episode_number,
                    total_episodes=total_episodes,
                    current_hook=episode.hook_text or "",
                    current_content=episode.content_text or "",
                    style="dramatic",
                    custom_instruction=custom_instruction.strip()
                )
                episode.hook_text = rewritten.hook_draft
                episode.content_text = rewritten.narrative_body
                if rewritten.call_to_action:
                    episode.call_to_action = rewritten.call_to_action
                db.commit()
                logger.info(f"AI refined episode {episode.id} script successfully based on instruction: {custom_instruction}")
            except Exception as e:
                logger.warning(f"Could not refine script with AI, proceeding with existing script: {e}")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after AI script refinement.")
            return
        
        # 1. Voiceover Generation
        job.progress = 20
        job.result = "Đang tạo giọng đọc AI (TTS) truyền cảm..."
        db.commit()

        full_narration = f"{episode.hook_text}. {episode.content_text} {episode.call_to_action or ''}".strip()
        voice_path, words, duration = await VoiceAgent.create_voiceover(
            text=full_narration,
            output_audio_path=str(working_dir / "voice_raw.mp3"),
            voice=settings.DEFAULT_TTS_VOICE
        )

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after TTS generation.")
            return

        job.progress = 40
        job.result = "Đang hòa âm nhạc nền kịch tính (Audio Ducking)..."
        db.commit()

        # 1.1 Mix with Background Music (Audio Ducking) in thread
        bgm_path = Path("media/bgm/suspense_bgm.mp3")
        final_audio_path = str(working_dir / "voice.mp3")
        
        if bgm_path.exists():
            try:
                from app.audio.bgm_mixer import BGMMixer
                await asyncio.to_thread(
                    BGMMixer.mix_voice_and_bgm,
                    voice_audio_path=voice_path,
                    bgm_audio_path=str(bgm_path),
                    output_audio_path=final_audio_path,
                    bgm_base_volume=0.25
                )
                logger.info(f"Mixed voice and suspense BGM for episode {episode.id}")
            except Exception as e:
                logger.warning(f"Could not mix BGM, using raw voice: {e}")
                final_audio_path = voice_path
        else:
            final_audio_path = voice_path

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after audio mixing.")
            return

        # 2. Subtitle Agent (Kinetic ASS + SRT)
        job.progress = 55
        job.result = "Đang tạo phụ đề động chuẩn xác từng mili-giây..."
        db.commit()

        ass_file = str(working_dir / "subs.ass")
        srt_file = str(working_dir / "subs.srt")
        SubtitleAgent.generate_subtitles(words, ass_file, srt_file)

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after subtitle creation.")
            return

        # 3. Scene slicing & selection
        job.progress = 70
        job.result = "Đang chọn lọc phân cảnh video hành động ăn khớp..."
        db.commit()

        movie = episode.script.movie
        source_media = movie.sources[0].file_path if (movie.sources and os.path.exists(movie.sources[0].file_path)) else None
        
        if not source_media:
            # Auto-download trailer from YouTube asynchronously!
            logger.info(f"Movie {movie.title} has no source video. Auto-fetching YouTube trailer on-the-fly...")
            try:
                from app.video.youtube_downloader import YouTubeTrailerDownloader, slugify_filename
                search_query = f"{movie.original_title or movie.title} {movie.release_year or ''}"
                clean_prefix = slugify_filename(movie.title, movie.release_year, fallback_title=movie.original_title)
                trailer_file = await asyncio.to_thread(
                    YouTubeTrailerDownloader.download_trailer,
                    query_or_url=search_query,
                    output_dir=str(settings.SOURCE_MEDIA_DIR),
                    filename_prefix=clean_prefix
                )
                if trailer_file and os.path.exists(trailer_file):
                    source = MovieSource(
                        movie_id=movie.id,
                        source_type="youtube_trailer",
                        file_path=trailer_file,
                        is_verified=True
                    )
                    db.add(source)
                    db.commit()
                    source_media = trailer_file
                    logger.info(f"Auto-fetched trailer successfully: {source_media}")
            except Exception as e:
                logger.warning(f"Could not auto-fetch trailer on-the-fly: {e}")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before scene slicing.")
            return

        if source_media and os.path.exists(source_media):
            logger.info(f"Using source video for timeline scene slicing: {source_media}")
            total_eps = len(episode.script.episodes) if (episode.script and episode.script.episodes) else 3
            sliced_clips = await asyncio.to_thread(
                SceneSlicer.slice_scenes_with_ffmpeg,
                source_video_path=source_media, 
                output_dir=str(working_dir / "slices"),
                target_clip_len=2.2,
                max_clips=25,
                episode_number=episode.episode_number,
                total_episodes=total_eps
            )
            selected_clips = SceneSelectorAgent.select_clips_for_duration(sliced_clips, duration, avg_clip_len=2.2)
        else:
            # Fallback dynamic motion cinematic background
            logger.info("Generating dynamic cinematic background...")
            dummy_clip = str(working_dir / "cinema_bg.mp4")
            import subprocess
            await asyncio.to_thread(
                subprocess.run,
                [
                    settings.FFMPEG_PATH, "-y", "-f", "lavfi",
                    "-i", f"gradients=s=1080x1920:c0=0x6366f1:c1=0x1e1b4b:c2=0x4338ca:c3=0x0f172a:speed=0.005:d={int(duration)+3}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", dummy_clip
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            selected_clips = [dummy_clip]

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before FFmpeg render.")
            return

        # 4. Render 9:16 Video in background thread with versioning (v1, v2, v3...)
        job.progress = 85
        job.result = "Đang xử lý FFmpeg render video dọc 9:16 (1080x1920)..."
        db.commit()

        from app.video.youtube_downloader import slugify_filename
        clean_movie_title = slugify_filename(movie.title, movie.release_year, fallback_title=movie.original_title)
        movie_output_folder = settings.OUTPUT_MEDIA_DIR / clean_movie_title
        movie_output_folder.mkdir(parents=True, exist_ok=True)

        existing_video_count = db.query(Video).filter(Video.episode_id == episode.id).count()
        render_version = existing_video_count + 1
        version_label = f"v{render_version}"
        output_video = str(movie_output_folder / f"{clean_movie_title}_Tap_{episode.episode_number}_{version_label}.mp4")

        output_video_path = await asyncio.to_thread(
            VideoEditorAgent.render_episode_video,
            selected_clips=selected_clips,
            voice_audio_path=final_audio_path,
            output_video_path=output_video,
            subtitle_ass_path=ass_file,
            enable_anti_shadowban=True
        )

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after video render.")
            return
        
        # 5. QA Check in background thread
        job.progress = 95
        job.result = "Đang kiểm định chất lượng video (QA)..."
        db.commit()

        qa_result = await asyncio.to_thread(QAAgent.inspect_video, output_video)
        
        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before saving video record.")
            return

        # 6. Save Video record
        video = Video(
            episode_id=episode.id,
            file_path=output_video,
            duration_seconds=duration,
            file_size_bytes=os.path.getsize(output_video) if os.path.exists(output_video) else 0,
            qa_status="passed" if qa_result.passed else "failed",
            qa_notes="; ".join(qa_result.issues) if qa_result.issues else "QA Passed"
        )
        db.add(video)
        episode.status = "rendered"
        
        job.status = "completed"
        job.progress = 100
        job.error_message = None
        job.result = f"Render video 9:16 thành công ({version_label}, {format_duration_str(duration)})!"
        db.commit()
        logger.info(f"Job #{job.id} render completed successfully for Episode {episode.id} -> {output_video}")

    @classmethod
    async def _handle_video_transform(cls, db, job: Job, payload: Dict[str, Any]):
        """
        Handle 1:1 Full-Length Video Transformation (Anti-Copyright & Frequency Shift).
        Preserves 100% original video duration without splitting or AI voiceover.
        """
        youtube_url = payload.get("youtube_url")
        file_path = payload.get("file_path")
        title = payload.get("title", "Video_1_1").strip()
        aspect_ratio = payload.get("aspect_ratio", "original") # "original", "blurred_stack_9_16", "center_crop_9_16"
        pitch_shift = float(payload.get("pitch_shift", 1.02))
        enable_audio_eq = bool(payload.get("enable_audio_eq", True))
        enable_hflip = bool(payload.get("enable_hflip", False))
        enable_color_grading = bool(payload.get("enable_color_grading", True))
        enable_micro_zoom = bool(payload.get("enable_micro_zoom", True))

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled before starting transformation.")
            return

        # 1. Obtain input video file
        input_source_file = None
        if file_path and os.path.exists(file_path):
            input_source_file = file_path
        elif youtube_url:
            job.progress = 15
            job.result = "Đang tải video gốc từ YouTube chất lượng cao..."
            db.commit()

            from app.video.youtube_downloader import YouTubeTrailerDownloader, slugify_filename
            clean_title = slugify_filename(title)
            downloaded = await asyncio.to_thread(
                YouTubeTrailerDownloader.download_trailer,
                query_or_url=youtube_url,
                output_dir=str(settings.SOURCE_MEDIA_DIR),
                filename_prefix=f"source_1_1_{clean_title}"
            )
            if not downloaded or not os.path.exists(downloaded):
                raise ValueError("Không thể tải video từ đường link YouTube đã cung cấp.")
            input_source_file = downloaded
        else:
            raise ValueError("Không tìm thấy nguồn video (Thiếu link YouTube hoặc file MP4).")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after video acquisition.")
            return

        # 2. Prepare output folder and check splitting
        from app.video.youtube_downloader import slugify_filename
        from app.video.video_transformer import VideoTransformerService

        clean_name = slugify_filename(title)
        transform_folder = settings.OUTPUT_MEDIA_DIR / "transformed"
        transform_folder.mkdir(parents=True, exist_ok=True)
        
        split_parts = int(payload.get("split_parts", 1))
        if split_parts not in [1, 2, 3]:
            split_parts = 1

        source_info = VideoTransformerService.get_media_info(input_source_file)
        source_dur = source_info.get("duration", 0.0)

        # Resolve movie_id if not explicitly in payload
        movie_id = payload.get("movie_id")
        if not movie_id and input_source_file:
            from app.database.models import MovieSource
            ms = db.query(MovieSource).filter(MovieSource.file_path == input_source_file).first()
            if ms:
                movie_id = ms.movie_id

        if split_parts > 1 and source_dur > 5.0:
            part_dur = source_dur / split_parts
            created_videos = []
            
            for p_idx in range(1, split_parts + 1):
                if cls._is_job_cancelled(db, job.id):
                    logger.warning(f"Job #{job.id} cancelled during split processing at part {p_idx}.")
                    return

                part_start = (p_idx - 1) * part_dur
                output_file_name = f"AntiCopy_{clean_name}_Tap_{p_idx}_{aspect_ratio}.mp4"
                output_file_path = str(transform_folder / output_file_name)

                def on_part_progress(pct: float, current_p=p_idx, total_p=split_parts):
                    try:
                        overall_pct = ((current_p - 1) + pct) / total_p
                        progress_val = min(92, int(40 + overall_pct * 52))
                        with SessionLocal() as progress_db:
                            pj = progress_db.query(Job).filter(Job.id == job.id).first()
                            if pj:
                                pj.status = "processing"
                                pj.progress = progress_val
                                pj.result = f"Đang xử lý Tập {current_p}/{total_p} ({int(pct*100)}%): Áp dụng bộ lọc âm thanh & hình ảnh..."
                                progress_db.commit()
                    except Exception:
                        pass

                job.progress = int(40 + ((p_idx - 1) / split_parts) * 52)
                job.result = f"Đang bắt đầu xử lý Tập {p_idx}/{split_parts}..."
                db.commit()

                rendered_path = await asyncio.to_thread(
                    VideoTransformerService.transform_full_length_video,
                    input_video_path=input_source_file,
                    output_video_path=output_file_path,
                    aspect_ratio=aspect_ratio,
                    pitch_shift=pitch_shift,
                    enable_audio_eq=enable_audio_eq,
                    enable_hflip=enable_hflip,
                    enable_color_grading=enable_color_grading,
                    enable_micro_zoom=enable_micro_zoom,
                    start_time=part_start,
                    duration=part_dur,
                    progress_callback=on_part_progress
                )

                media_info = VideoTransformerService.get_media_info(rendered_path)
                dur = media_info.get("duration", part_dur)
                res_str = f"{media_info.get('width', 1080)}x{media_info.get('height', 1920)}"

                part_title = f"{title} - Tập {p_idx}" if title else f"Video 1:1 - Tập {p_idx}"
                video = Video(
                    movie_id=movie_id,
                    episode_id=None,
                    title=part_title,
                    video_type="transformed_1_1",
                    file_path=rendered_path,
                    resolution=res_str,
                    duration_seconds=dur,
                    file_size_bytes=os.path.getsize(rendered_path) if os.path.exists(rendered_path) else 0,
                    qa_status="passed",
                    qa_notes=f"Xử lý lách bản quyền 1:1 - Tập {p_idx}/{split_parts} hoàn tất"
                )
                db.add(video)
                db.commit()
                created_videos.append(Path(rendered_path).name)

            job.status = "completed"
            job.progress = 100
            job.error_message = None
            job.result = f"Xử lý video 1:1 lách bản quyền thành công! Đã chia {split_parts} tập ({', '.join(created_videos)})"
            db.commit()
            logger.info(f"Job #{job.id} video split transform completed -> {created_videos}")

        else:
            # Single video full length transformation
            output_file_name = f"AntiCopy_{clean_name}_{aspect_ratio}.mp4"
            output_file_path = str(transform_folder / output_file_name)

            job.progress = 40
            job.result = f"Đang áp dụng bộ lọc âm thanh (Pitch {pitch_shift:+.2f}, EQ 48kHz) & biến đổi hình ảnh..."
            db.commit()

            if cls._is_job_cancelled(db, job.id):
                logger.warning(f"Job #{job.id} cancelled before FFmpeg processing.")
                return

            def on_transform_progress(pct: float):
                try:
                    progress_val = min(92, int(40 + pct * 52))
                    with SessionLocal() as progress_db:
                        pj = progress_db.query(Job).filter(Job.id == job.id).first()
                        if pj:
                            pj.status = "processing"
                            pj.progress = progress_val
                            pj.result = f"Đang biến đổi video 1:1 ({int(pct*100)}%): Áp dụng bộ lọc âm thanh & hình ảnh..."
                            progress_db.commit()
                except Exception:
                    pass

            rendered_path = await asyncio.to_thread(
                VideoTransformerService.transform_full_length_video,
                input_video_path=input_source_file,
                output_video_path=output_file_path,
                aspect_ratio=aspect_ratio,
                pitch_shift=pitch_shift,
                enable_audio_eq=enable_audio_eq,
                enable_hflip=enable_hflip,
                enable_color_grading=enable_color_grading,
                enable_micro_zoom=enable_micro_zoom,
                progress_callback=on_transform_progress
            )

            if cls._is_job_cancelled(db, job.id):
                logger.warning(f"Job #{job.id} cancelled after video transformation.")
                return

            # 4. Probe result and save to Database
            media_info = VideoTransformerService.get_media_info(rendered_path)
            dur = media_info.get("duration", 0.0)
            res_str = f"{media_info.get('width', 1080)}x{media_info.get('height', 1920)}"

            job.progress = 95
            job.result = "Đang lưu trữ bản ghi video hoàn tất..."
            db.commit()

            video = Video(
                movie_id=movie_id,
                episode_id=None,
                title=title or "Video 1:1 Biến Đổi",
                video_type="transformed_1_1",
                file_path=rendered_path,
                resolution=res_str,
                duration_seconds=dur,
                file_size_bytes=os.path.getsize(rendered_path) if os.path.exists(rendered_path) else 0,
                qa_status="passed",
                qa_notes="Xử lý lách bản quyền 1:1 Full Length hoàn tất"
            )
            db.add(video)

            if cls._is_job_cancelled(db, job.id):
                logger.warning(f"Job #{job.id} cancelled before final commit.")
                return

            job.status = "completed"
            job.progress = 100
            job.error_message = None
            job.result = f"Xử lý video 1:1 lách bản quyền thành công! Thời lượng: {format_duration_str(dur)} (File: {Path(rendered_path).name})"
            db.commit()
            logger.info(f"Job #{job.id} full-length video transform completed -> {rendered_path}")
