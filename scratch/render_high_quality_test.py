import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os
import json
import asyncio
from datetime import datetime

from app.database.session import SessionLocal
from app.database.models import Movie, MovieSource, Script, Episode, Video
from app.core.config import settings
from app.agents.voice_agent import VoiceAgent
from app.agents.subtitle_agent import SubtitleAgent
from app.agents.scene_selector import SceneSelectorAgent
from app.agents.video_editor import VideoEditorAgent
from app.agents.qa_agent import QAAgent
from app.audio.bgm_mixer import BGMMixer
from app.video.scene_slicer import SceneSlicer

async def main():
    db = SessionLocal()
    try:
        # 1. Get or create high quality movie
        movie = db.query(Movie).filter(Movie.title.like("%Inception%")).first()
        if not movie:
            movie = Movie(
                title="Inception (Kẻ Trộm Giấc Mơ)",
                original_title="Inception",
                release_year=2010,
                genre="Khoa Học Viễn Tưởng, Trinh Thám, Gay Cấn",
                duration_minutes=148,
                synopsis="Dom Cobb là một kẻ trộm bậc thầy chuyên đánh cắp các bí mật sâu kín nhất trong tiềm thức của mục tiêu khi họ đang mơ.",
                potential_score=98.5,
                status="scripted"
            )
            db.add(movie)
            db.flush()

        source_file = "media/source/test_movie_YoHD9XEInc0.mp4"
        if not os.path.exists(source_file):
            source_file = "media/source/movie_1_YoHD9XEInc0.mp4"

        # Ensure source attached
        existing_source = db.query(MovieSource).filter(MovieSource.movie_id == movie.id).first()
        if not existing_source:
            source = MovieSource(
                movie_id=movie.id,
                source_type="youtube_trailer",
                file_path=source_file,
                is_verified=True
            )
            db.add(source)
            db.commit()

        # 2. Create high-octane script
        script = db.query(Script).filter(Script.movie_id == movie.id).first()
        if not script:
            script = Script(
                movie_id=movie.id,
                title="Kịch Bản Review - Inception Cực Phẩm",
                target_episodes=1,
                full_script="{}",
                style="dramatic"
            )
            db.add(script)
            db.flush()

        hook_text = "Bạn có tin: Chỉ một ý niệm gieo vào giấc mơ có thể hủy diệt cả một đế chế?"
        narrative_body = (
            "Dom Cobb, một tên trộm bậc thầy có khả năng xâm nhập vào tầng sâu nhất của tiềm thức. "
            "Nhưng lần này, nhiệm vụ không phải là đánh cắp, mà là 'Cấy ý niệm' vào não bộ kẻ thù! "
            "Càng đi sâu vào các tầng mơ, ranh giới giữa thực và ảo hoàn toàn sụp đổ. "
            "Liệu anh có thể thoát khỏi mê cung tâm trí hay sẽ mắc kẹt vĩnh viễn trong địa ngục vô thức?"
        )
        cta_text = "Thả tim và theo dõi ngay để đón xem cú lừa thế kỷ ở Tập 2!"

        episode = Episode(
            script_id=script.id,
            episode_number=1,
            hook_text=hook_text,
            hook_score=96.0,
            content_text=narrative_body,
            call_to_action=cta_text,
            status="approved"
        )
        db.add(episode)
        db.commit()
        db.refresh(episode)

        print(f"Creating High Quality 9:16 Video for Episode #{episode.id}...")
        working_dir = settings.WORKING_MEDIA_DIR / f"ep_{episode.id}_hq"
        working_dir.mkdir(parents=True, exist_ok=True)

        # 3. Voiceover
        full_text = f"{hook_text} {narrative_body} {cta_text}"
        voice_raw = str(working_dir / "voice_raw.mp3")
        voice_path, words, duration = await VoiceAgent.create_voiceover(
            text=full_text,
            output_audio_path=voice_raw,
            voice="vi-VN-HoaiMyNeural",
            speed=1.08
        )
        print(f"Voiceover generated: duration={duration:.2f}s, words={len(words)}")

        # 4. Mix BGM with Ducking
        bgm_file = "media/bgm/suspense_bgm.mp3"
        mixed_voice = str(working_dir / "voice_mixed.mp3")
        if os.path.exists(bgm_file):
            print("Mixing suspense BGM with Audio Ducking...")
            BGMMixer.mix_voice_and_bgm(
                voice_audio_path=voice_path,
                bgm_audio_path=bgm_file,
                output_audio_path=mixed_voice,
                bgm_base_volume=0.35,
                ducking_ratio=5.0
            )
            final_audio = mixed_voice
        else:
            final_audio = voice_path

        # 5. Subtitles
        ass_file = str(working_dir / "subs.ass")
        srt_file = str(working_dir / "subs.srt")
        SubtitleAgent.generate_subtitles(words, ass_file, srt_file)
        print("Kinetic Subtitles generated.")

        # 6. Slice actual movie footage!
        print(f"Slicing crisp movie clips from {source_file}...")
        slices_dir = working_dir / "slices"
        sliced_clips = SceneSlicer.slice_scenes_with_ffmpeg(
            source_video_path=source_file,
            output_dir=str(slices_dir),
            target_clip_len=2.5,
            max_clips=20
        )
        print(f"Generated {len(sliced_clips)} movie scene clips.")

        selected_clips = SceneSelectorAgent.select_clips_for_duration(sliced_clips, duration)
        print(f"Selected {len(selected_clips)} clips matching narration duration.")

        # 7. Render 9:16 vertical video with FFmpeg
        output_video = str(settings.OUTPUT_MEDIA_DIR / f"inception_hq_ep_{episode.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4")
        print(f"Rendering 9:16 TikTok Vertical Video to {output_video}...")
        
        from app.video.ffmpeg_service import FFmpegService
        concat_video_path = str(working_dir / "concat.mp4")
        FFmpegService.concatenate_clips(selected_clips, concat_video_path)

        final_rendered = FFmpegService.render_vertical_video(
            video_input_path=concat_video_path,
            audio_input_path=final_audio,
            output_video_path=output_video,
            subtitle_ass_path=ass_file,
            enable_anti_shadowban=True,
            preset_mode="blurred_stack"
        )

        # 8. QA Agent Inspection
        print("Running QA inspection...")
        qa_result = QAAgent.inspect_video(final_rendered)
        print(f"QA Passed: {qa_result.passed}, Issues: {qa_result.issues}")

        # 9. Register in Database
        video_rec = Video(
            episode_id=episode.id,
            file_path=final_rendered,
            duration_seconds=duration,
            file_size_bytes=os.path.getsize(final_rendered),
            qa_status="passed" if qa_result.passed else "failed",
            qa_notes="; ".join(qa_result.issues) if qa_result.issues else "QA Passed (1080x1920 9:16)"
        )
        db.add(video_rec)
        episode.status = "rendered"
        db.commit()

        print(f"\nSUCCESS! Video #{video_rec.id} created at: {final_rendered}")
        print(f"Size: {video_rec.file_size_bytes / 1024 / 1024:.2f} MB, Duration: {duration:.1f}s")

    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(main())
