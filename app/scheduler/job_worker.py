import os
import json
import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger

from app.database.session import SessionLocal
from app.database.models import Job, Movie, MovieSource, Script, Episode, MediaFile, Video, Setting, Story, Publish
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
from app.story.audiobook_generator import AudiobookGenerator
from app.story.story_video_renderer import StoryVideoRenderer
from app.story.story_image_generator import StoryImageGenerator

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
    def prune_finished_jobs(cls, db, max_keep: int = 100) -> int:
        """
        Automatically keeps only the most recent `max_keep` jobs.
        Deletes finished jobs (all statuses except pending and processing) older than the top `max_keep`.
        Active jobs are NEVER deleted.
        """
        try:
            total_count = db.query(Job).count()
            if total_count <= max_keep:
                return 0

            # Find the cutoff ID of the max_keep-th newest job
            cutoff = db.query(Job.id).order_by(Job.id.desc()).offset(max_keep).limit(1).first()
            if not cutoff:
                return 0

            cutoff_id = cutoff[0]
            deleted_count = db.query(Job).filter(
                Job.id <= cutoff_id,
                Job.status.notin_(["pending", "processing"])
            ).delete(synchronize_session=False)
            db.commit()
            if deleted_count > 0:
                logger.info(f"Auto-pruned {deleted_count} old finished jobs beyond #{max_keep} retention limit.")
            return deleted_count
        except Exception as e:
            logger.error(f"Error during auto-pruning jobs: {e}")
            db.rollback()
            return 0

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
            elif job.job_type == "StoryAudioJob":
                await cls._handle_story_audio(db, job, payload)
            elif job.job_type == "StoryVideoRenderJob":
                await cls._handle_story_video_render(db, job, payload)
            elif job.job_type in ["YouTubePublishJob", "PublishJob"]:
                await cls._handle_youtube_publish(db, job, payload)
            elif job.job_type == "TikTokPublishJob":
                await cls._handle_tiktok_publish(db, job, payload)
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

                    # Also synchronize story status if it's a story job!
                    if job.job_type in ["StoryVideoRenderJob", "StoryAudioJob"]:
                        try:
                            payload_data = json.loads(job.payload) if job.payload else {}
                            sid = payload_data.get("story_id")
                            if sid:
                                st = db.query(Story).filter(Story.id == sid).first()
                                if st:
                                    st.status = "failed"
                                    st.error_message = str(e)
                        except Exception as sync_err:
                            logger.error(f"Error syncing story status on job failure: {sync_err}")

                    # Also synchronize publish status if it's a publish job!
                    if job.job_type in ["YouTubePublishJob", "PublishJob", "TikTokPublishJob"]:
                        try:
                            payload_data = json.loads(job.payload) if job.payload else {}
                            pub_id = payload_data.get("publish_id")
                            if pub_id:
                                pb = db.query(Publish).filter(Publish.id == pub_id).first()
                                if pb:
                                    pb.status = "failed"
                                    pb.error_message = str(e)
                        except Exception as sync_err:
                            logger.error(f"Error syncing publish status on job failure: {sync_err}")

                    db.commit()
        finally:
            try:
                cls.prune_finished_jobs(db, max_keep=100)
            except Exception as pe:
                logger.error(f"Error auto-pruning jobs in worker: {pe}")
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
        enable_dubbing = bool(payload.get("enable_dubbing", False))
        source_language = payload.get("source_language", "auto")
        vietnamese_voice = payload.get("vietnamese_voice", "vi-VN-HoaiMyNeural")
        dubbing_mode = payload.get("dubbing_mode", "voiceover")
        burn_subtitles = bool(payload.get("burn_subtitles", False))

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
        from app.audio.dubbing_engine import DubbingEngine

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

        # 2.1 AI Dubbing Pipeline (if enabled)
        dubbed_audio_track = None
        subtitles_srt_track = None
        enable_auto_subtitles = payload.get("enable_auto_subtitles", False)

        if enable_dubbing:
            job.progress = 20
            job.result = "Đang trích xuất audio để AI nhận dạng lời thoại & dịch sang Tiếng Việt..."
            db.commit()

            dub_working_dir = settings.WORKING_MEDIA_DIR / f"dubbing_{job.id}"
            dub_working_dir.mkdir(parents=True, exist_ok=True)
            extracted_ai_audio = str(dub_working_dir / "source_ai_audio.mp3")

            await asyncio.to_thread(
                DubbingEngine.extract_audio_for_ai,
                input_video_or_audio=input_source_file,
                output_audio_path=extracted_ai_audio
            )

            job.progress = 25
            job.result = "AI Gemini đang dịch thuật câu thoại sang Tiếng Việt chuẩn ngữ cảnh..."
            db.commit()

            try:
                segments = await DubbingEngine.transcribe_and_translate(
                    audio_path=extracted_ai_audio,
                    source_language=source_language
                )

                if cls._is_job_cancelled(db, job.id):
                    logger.warning(f"Job #{job.id} cancelled after AI translation.")
                    return

                if segments:
                    job.progress = 35
                    job.result = f"Đang sinh {len(segments)} câu lồng tiếng AI Tiếng Việt ({vietnamese_voice.split('-')[-1]})..."
                    db.commit()

                    dubbed_audio_track = await DubbingEngine.synthesize_dubbing_track(
                        segments=segments,
                        voice_name=vietnamese_voice,
                        total_duration=source_dur,
                        working_dir=dub_working_dir
                    )

                    if burn_subtitles:
                        subtitles_srt_track = DubbingEngine.generate_subtitles_ass(
                            segments=segments,
                            output_ass_path=str(dub_working_dir / "dubbing_subs.ass")
                        )
                else:
                    logger.info(f"Không phát hiện câu thoại nào cần lồng tiếng trong video: {input_source_file}")
            except Exception as e:
                logger.error(f"AI Dubbing error: {e}", exc_info=True)
                raise RuntimeError(f"Lỗi trong quá trình dịch & lồng tiếng AI: {e}")

        elif enable_auto_subtitles:
            job.progress = 20
            job.result = "Đang nhận diện lời thoại để tạo phụ đề tự động bằng faster-whisper..."
            db.commit()

            subs_working_dir = settings.WORKING_MEDIA_DIR / f"subs_{job.id}"
            subs_working_dir.mkdir(parents=True, exist_ok=True)
            extracted_audio = str(subs_working_dir / "source_audio.mp3")

            await asyncio.to_thread(
                DubbingEngine.extract_audio_for_ai,
                input_video_or_audio=input_source_file,
                output_audio_path=extracted_audio
            )

            job.progress = 30
            job.result = "Đang tạo file phụ đề ASS chuẩn nét cho video..."
            db.commit()

            try:
                subtitles_srt_track = await DubbingEngine.generate_auto_subtitles_ass(
                    audio_path=extracted_audio,
                    language=source_language if source_language != "auto" else "auto",
                    output_ass_path=str(subs_working_dir / "auto_subtitles.ass")
                )
                logger.info(f"Generated auto-subtitles file: {subtitles_srt_track}")
            except Exception as sub_err:
                logger.warning(f"Failed to generate auto-subtitles: {sub_err}")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"Job #{job.id} cancelled after audio processing step.")
            return

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
                    dubbed_audio_path=dubbed_audio_track,
                    dubbing_mode=dubbing_mode,
                    subtitles_srt_path=subtitles_srt_track,
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
                    qa_notes=f"Xử lý lách bản quyền 1:1 {'+ Lồng Tiếng AI' if enable_dubbing else ''} - Tập {p_idx}/{split_parts} hoàn tất"
                )
                db.add(video)
                db.commit()
                created_videos.append(Path(rendered_path).name)

            job.status = "completed"
            job.progress = 100
            job.error_message = None
            job.result = f"Xử lý video 1:1 {'+ Lồng tiếng AI ' if enable_dubbing else ''}thành công! Đã chia {split_parts} tập ({', '.join(created_videos)})"
            db.commit()
            logger.info(f"Job #{job.id} video split transform completed -> {created_videos}")

        else:
            # Single video full length transformation
            output_file_name = f"AntiCopy_{clean_name}_{aspect_ratio}.mp4"
            output_file_path = str(transform_folder / output_file_name)

            job.progress = 40
            job.result = f"Đang áp dụng bộ lọc âm thanh & biến đổi hình ảnh..."
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
                dubbed_audio_path=dubbed_audio_track,
                dubbing_mode=dubbing_mode,
                subtitles_srt_path=subtitles_srt_track,
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

    @classmethod
    async def _handle_story_audio(cls, db, job: Job, payload: Dict[str, Any]):
        story_id = payload.get("story_id")
        story = db.query(Story).filter(Story.id == story_id).first()
        if not story:
            raise ValueError(f"Story #{story_id} not found.")

        def update_audio_progress(pct: float, message: str):
            try:
                progress_val = min(98, max(5, int(pct * 100)))
                with SessionLocal() as progress_db:
                    pj = progress_db.query(Job).filter(Job.id == job.id).first()
                    if pj:
                        pj.status = "processing"
                        pj.progress = progress_val
                        pj.result = message
                        progress_db.commit()
            except Exception:
                pass

        update_audio_progress(0.1, "AI đang phân tích nhân vật và chia đoạn kịch bản đa giọng...")

        if cls._is_job_cancelled(db, job.id):
            return

        # Generate multi-voice audio & subtitles
        audio_path, duration, characters, _ = await AudiobookGenerator.generate_story_audio(
            story_id=story.id,
            content=story.content,
            aspect_ratio="16:9",
            bgm_filename=story.bgm_name or "suspense_bgm.mp3",
            progress_callback=update_audio_progress
        )

        update_audio_progress(0.95, "Đang lưu trữ dữ liệu âm thanh...")

        story.audio_path = audio_path
        story.duration_seconds = duration
        story.characters_json = json.dumps(characters, ensure_ascii=False)
        story.status = "audio_ready"
        story.error_message = None

        job.status = "completed"
        job.progress = 100
        job.error_message = None
        char_names = ", ".join(characters) if characters else "Người dẫn chuyện"
        job.result = f"Tạo âm thanh kịch đa giọng thành công ({char_names})! Thời lượng: {format_duration_str(duration)}"
        db.commit()
        logger.info(f"Story #{story_id} multi-voice audio ready -> {audio_path} ({duration:.1f}s)")

    @classmethod
    async def _handle_story_video_render(cls, db, job: Job, payload: Dict[str, Any]):
        story_id = payload.get("story_id")
        aspect_ratio = payload.get("aspect_ratio", "16:9")
        story = db.query(Story).filter(Story.id == story_id).first()
        if not story:
            raise ValueError(f"Story #{story_id} not found.")

        def update_video_progress(pct: float, message: str):
            try:
                progress_val = min(98, max(5, int(pct * 100)))
                with SessionLocal() as progress_db:
                    pj = progress_db.query(Job).filter(Job.id == job.id).first()
                    if pj:
                        pj.status = "processing"
                        pj.progress = progress_val
                        pj.result = message
                        progress_db.commit()
            except Exception:
                pass

        ass_path = f"media/working/stories/story_{story.id}_subtitles.ass"

        # 1. Ensure audio & subtitles exist
        if not story.audio_path or not os.path.exists(story.audio_path) or not os.path.exists(ass_path):
            update_video_progress(0.08, "AI đang phân tích nhân vật, lồng tiếng đa giọng & tạo phụ đề...")
            
            if cls._is_job_cancelled(db, job.id):
                return
                
            audio_path, duration, characters, generated_ass = await AudiobookGenerator.generate_story_audio(
                story_id=story.id,
                content=story.content,
                aspect_ratio=aspect_ratio,
                bgm_filename=story.bgm_name or "suspense_bgm.mp3",
                progress_callback=lambda pct, msg: update_video_progress(pct * 0.45, msg)
            )
            story.audio_path = audio_path
            story.duration_seconds = duration
            story.characters_json = json.dumps(characters, ensure_ascii=False)
            ass_path = generated_ass
            db.commit()

        if cls._is_job_cancelled(db, job.id):
            return

        ratios_to_render = ["9:16", "16:9"] if aspect_ratio in ["both", "all", "2"] else [aspect_ratio]
        rendered_paths = []

        for i, asp in enumerate(ratios_to_render):
            if cls._is_job_cancelled(db, job.id):
                return

            # 2. Automatically generate AI artwork background matching story theme
            update_video_progress(0.50 + i * 0.04, f"AI đang tạo hình nền nghệ thuật ({asp})...")
            bg_image_path = await StoryImageGenerator.generate_story_background(
                story_id=story.id,
                title=story.title,
                content=story.content,
                aspect_ratio=asp
            )

            if cls._is_job_cancelled(db, job.id):
                return

            def on_video_render_progress(render_pct: float, msg: str):
                step_weight = 0.40 / len(ratios_to_render)
                overall_pct = 0.58 + (i * step_weight) + (render_pct * step_weight)
                update_video_progress(overall_pct, f"Render video {asp}: {msg}")

            # 3. Render Video with AI background, live waveforms, and synchronized ASS subtitles
            vp = await StoryVideoRenderer.render_audiobook_video(
                story_id=story.id,
                title=story.title,
                author=story.author or "Khuyết danh",
                audio_path=story.audio_path,
                aspect_ratio=asp,
                bg_image_path=bg_image_path,
                subtitle_path=ass_path if os.path.exists(ass_path) else None,
                progress_callback=on_video_render_progress
            )
            rendered_paths.append(vp)

        # Main video path is the primary format (9:16 by default or selected)
        story.video_aspect = "9:16 & 16:9" if len(ratios_to_render) > 1 else aspect_ratio
        story.video_path = rendered_paths[0]
        story.status = "completed"
        story.error_message = None

        job.status = "completed"
        job.progress = 100
        job.error_message = None
        job.result = f"Render video truyện đa giọng ({story.video_aspect}) thành công!"
        db.commit()
        logger.info(f"Story #{story_id} video render completed -> {rendered_paths}")

    @classmethod
    async def _handle_youtube_publish(cls, db, job: Job, payload: Dict[str, Any]):
        """
        Handle asynchronous background YouTube video upload with live progress reporting.
        """
        publish_id = payload.get("publish_id")
        file_path = payload.get("file_path")
        title = payload.get("title", "Video").strip()
        description = payload.get("description", "").strip()
        tags = payload.get("tags", [])
        privacy_status = payload.get("privacy_status", "public")
        category_id = payload.get("category_id", "24")
        is_shorts = payload.get("is_shorts", False)

        publish = db.query(Publish).filter(Publish.id == publish_id).first() if publish_id else None
        if publish:
            publish.status = "publishing"
            db.commit()

        def update_pub_progress(pct: float, message: str):
            try:
                progress_val = min(98, max(5, int(pct * 100)))
                with SessionLocal() as progress_db:
                    pj = progress_db.query(Job).filter(Job.id == job.id).first()
                    if pj:
                        pj.status = "processing"
                        pj.progress = progress_val
                        pj.result = message
                        progress_db.commit()
            except Exception:
                pass

        update_pub_progress(0.08, "Đang kết nối YouTube API & khởi tạo tải video...")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"YouTubePublishJob #{job.id} cancelled before upload.")
            return

        from app.publishing.youtube_publisher import YouTubePublisher

        upload_res = await asyncio.to_thread(
            YouTubePublisher.upload_video,
            file_path=file_path,
            title=title,
            description=description,
            tags=tags,
            privacy_status=privacy_status,
            category_id=category_id,
            is_shorts=is_shorts,
            progress_callback=update_pub_progress
        )

        video_id = upload_res.get("video_id")
        video_url = upload_res.get("video_url")

        if publish:
            publish.status = "published"
            publish.platform_video_id = video_id
            publish.video_url = video_url
            publish.published_at = datetime.utcnow()
            publish.error_message = None
            db.commit()

        job.status = "completed"
        job.progress = 100
        job.error_message = None
        job.result = f"Đăng video lên YouTube thành công! Link: {video_url}"
        db.commit()
        logger.info(f"YouTubePublishJob #{job.id} completed successfully -> {video_url}")

    @classmethod
    async def _handle_tiktok_publish(cls, db: Session, job: Job, payload: Dict[str, Any]):
        """Publish vertical 9:16 video to TikTok via Content Posting API."""
        publish_id = payload.get("publish_id")
        file_path = payload.get("file_path")
        caption = payload.get("caption", "")
        privacy_level = payload.get("privacy_level", "PUBLIC_TO_EVERYONE")
        disable_duet = payload.get("disable_duet", False)
        disable_comment = payload.get("disable_comment", False)
        disable_stitch = payload.get("disable_stitch", False)

        if not file_path or not os.path.exists(file_path):
            raise FileNotFoundError(f"File video không tồn tại: {file_path}")

        publish = db.query(Publish).filter(Publish.id == publish_id).first() if publish_id else None
        if publish:
            publish.status = "publishing"
            db.commit()

        def update_pub_progress(pct: float, message: str):
            try:
                progress_val = min(98, max(5, int(pct * 100)))
                with SessionLocal() as progress_db:
                    pj = progress_db.query(Job).filter(Job.id == job.id).first()
                    if pj:
                        pj.status = "processing"
                        pj.progress = progress_val
                        pj.result = message
                        progress_db.commit()
            except Exception:
                pass

        update_pub_progress(0.08, "Đang kết nối TikTok API & khởi tạo phiên đăng tải...")

        if cls._is_job_cancelled(db, job.id):
            logger.warning(f"TikTokPublishJob #{job.id} cancelled before upload.")
            return

        from app.publishing.tiktok_publisher import TikTokPublisher

        upload_res = await asyncio.to_thread(
            TikTokPublisher.upload_video,
            file_path=file_path,
            title=caption,
            privacy_level=privacy_level,
            disable_duet=disable_duet,
            disable_comment=disable_comment,
            disable_stitch=disable_stitch,
            progress_callback=update_pub_progress
        )

        post_id = upload_res.get("post_id")
        post_url = upload_res.get("video_url") or f"https://www.tiktok.com/@creator/video/{post_id}"

        if publish:
            publish.status = "published"
            publish.tiktok_post_id = str(post_id)
            publish.platform_video_id = str(post_id)
            publish.video_url = post_url
            publish.published_at = datetime.utcnow()
            publish.error_message = None
            db.commit()

        is_inbox = upload_res.get("is_inbox", False)
        job.status = "completed"
        job.progress = 100
        job.error_message = None
        if is_inbox:
            job.result = "Đã gửi vào Hộp Thư / Bản Nháp TikTok! Hãy mở app TikTok trên điện thoại để duyệt đăng."
        else:
            job.result = f"Đăng video lên TikTok thành công! Link: {post_url}"
        db.commit()
        logger.info(f"TikTokPublishJob #{job.id} completed successfully -> {post_url}")




