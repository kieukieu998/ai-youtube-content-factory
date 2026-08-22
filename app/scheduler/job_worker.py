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

class JobWorker:
    """Background Async Poller and Dispatcher for SQLite Jobs queue."""
    
    _is_running = False
    _emergency_stop = False

    @classmethod
    def set_emergency_stop(cls, stop: bool = True):
        cls._emergency_stop = stop
        logger.warning(f"SYSTEM EMERGENCY STOP set to: {stop}")

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
            else:
                job.status = "completed"
                job.progress = 100
                db.commit()

        except Exception as e:
            logger.error(f"Job execution failed: {e}")
            if 'job' in locals() and job:
                job.status = "failed"
                job.error_message = str(e)
                db.commit()
        finally:
            db.close()

    @classmethod
    async def _handle_movie_discovery(cls, db, job: Job, payload: Dict[str, Any]):
        genre = payload.get("genre", "Hành Động, Kinh Dị")
        limit = payload.get("limit", 3)
        
        # Query existing movies to prevent duplicates
        existing_movies = db.query(Movie).all()
        existing_titles = [m.title for m in existing_movies] + [m.original_title for m in existing_movies if m.original_title]
        
        hunter = MovieHunterAgent()
        candidates = await hunter.discover_movies(genre=genre, limit=limit, existing_titles=existing_titles)
        job.progress = 50
        db.commit()

        created_movies = []
        from app.video.youtube_downloader import YouTubeTrailerDownloader

        for c in candidates:
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
                search_query = f"{c.original_title or c.title} {c.release_year or ''}"
                trailer_file = await asyncio.to_thread(
                    YouTubeTrailerDownloader.download_trailer,
                    query_or_url=search_query,
                    output_dir=str(settings.SOURCE_MEDIA_DIR),
                    filename_prefix=f"movie_{movie.id}"
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

        job.status = "completed"
        job.progress = 100
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
        job.progress = 85
        job.result = "Đang lưu kịch bản và phân cảnh vào cơ sở dữ liệu..."
        db.commit()

        # 3. Create Script entity
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
        job.status = "completed"
        job.progress = 100
        job.result = f"Hoàn thành {len(script_pkg.episodes)} tập kịch bản (Đã đưa vào danh sách chờ duyệt)"
        db.commit()
        logger.info(f"Job #{job.id} completed. Generated {len(script_pkg.episodes)} episodes for Movie {movie.title}")

    @classmethod
    async def _handle_render_episode(cls, db, job: Job, payload: Dict[str, Any]):
        episode_id = payload.get("episode_id")
        episode = db.query(Episode).filter(Episode.id == episode_id).first()
        if not episode:
            raise ValueError(f"Episode ID {episode_id} not found")

        working_dir = settings.WORKING_MEDIA_DIR / f"ep_{episode.id}"
        working_dir.mkdir(parents=True, exist_ok=True)
        
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

        # 2. Subtitle Agent (Kinetic ASS + SRT)
        job.progress = 55
        job.result = "Đang tạo phụ đề động chuẩn xác từng mili-giây..."
        db.commit()

        ass_file = str(working_dir / "subs.ass")
        srt_file = str(working_dir / "subs.srt")
        SubtitleAgent.generate_subtitles(words, ass_file, srt_file)

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
                from app.video.youtube_downloader import YouTubeTrailerDownloader
                search_query = f"{movie.original_title or movie.title} {movie.release_year or ''}"
                trailer_file = await asyncio.to_thread(
                    YouTubeTrailerDownloader.download_trailer,
                    query_or_url=search_query,
                    output_dir=str(settings.SOURCE_MEDIA_DIR),
                    filename_prefix=f"movie_{movie.id}"
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
                    "-i", f"color=c=0x0f172a:s=1080x1920:d={int(duration)+3}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", dummy_clip
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            selected_clips = [dummy_clip]

        # 4. Render 9:16 Video in background thread with versioning (v1, v2, v3...)
        job.progress = 85
        job.result = "Đang xử lý FFmpeg render video dọc 9:16 (1080x1920)..."
        db.commit()

        from app.video.youtube_downloader import slugify_filename
        clean_movie_title = slugify_filename(movie.title, movie.release_year)
        movie_output_folder = settings.OUTPUT_MEDIA_DIR / clean_movie_title
        movie_output_folder.mkdir(parents=True, exist_ok=True)

        existing_video_count = db.query(Video).filter(Video.episode_id == episode.id).count()
        render_version = existing_video_count + 1
        output_video = str(movie_output_folder / f"{clean_movie_title}_Tap_{episode.episode_number}_v{render_version}.mp4")

        output_video_path = await asyncio.to_thread(
            VideoEditorAgent.render_episode_video,
            selected_clips=selected_clips,
            voice_audio_path=final_audio_path,
            output_video_path=output_video,
            subtitle_ass_path=ass_file,
            enable_anti_shadowban=True
        )
        
        # 5. QA Check in background thread
        job.progress = 95
        job.result = "Đang kiểm định chất lượng video (QA)..."
        db.commit()

        qa_result = await asyncio.to_thread(QAAgent.inspect_video, output_video)
        
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
        job.result = f"Render video 9:16 thành công (v{render_version}, {duration:.1f}s)!"
        db.commit()
        logger.info(f"Job #{job.id} render completed successfully for Episode {episode.id} -> {output_video}")
