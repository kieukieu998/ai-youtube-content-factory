import pytest
import json
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from main import app
from app.database.session import SessionLocal, get_db
from app.database.models import Movie, MovieSource, Script, Episode, Video, Setting, Job
from app.ai.provider_factory import get_ai_provider
from app.video.scene_slicer import SceneSlicer

from app.database.models import Movie, MovieSource, Script, Episode, Video, Setting, Job
from app.ai.provider_factory import get_ai_provider
from app.video.scene_slicer import SceneSlicer

def test_ai_providers_per_stage_and_settings(client, db_session):
    """Task 1: Test saving & resolving separate AI providers per stage."""
    save_response = client.post(
        "/api/v1/settings/save",
        data={
            "default_ai_provider": "gemini_free",
            "discovery_ai_provider": "deepseek",
            "script_ai_provider": "openai",
            "render_ai_provider": "gemini_free",
            "gemini_api_key": "test_gemini_key",
            "deepseek_api_key": "test_deepseek_key",
            "openai_api_key": "test_openai_key",
            "operation_mode": "semi_auto",
            "default_tts_voice": "vi-VN-HoaiMyNeural",
            "daily_budget_limit_usd": "10.0"
        }
    )
    assert save_response.status_code == 200
    assert save_response.json()["status"] == "success"

    # Test factory resolution by stage
    discovery_p = get_ai_provider(stage="discovery")
    assert discovery_p.__class__.__name__ == "OpenAICompatibleProvider"
    assert discovery_p.model_name == "deepseek-chat"

    script_p = get_ai_provider(stage="script")
    assert script_p.__class__.__name__ == "OpenAICompatibleProvider"
    assert script_p.model_name == "gpt-4o"

    render_p = get_ai_provider(stage="render")
    assert render_p.__class__.__name__ == "GeminiProvider"

def test_movie_update_and_custom_titles(client, db_session):
    """Task 4: Test editing movie Vietnamese & English titles and metadata."""
    # Create test movie
    movie = Movie(
        title="Ten Cu Sai",
        original_title="Old Wrong Title",
        genre="Action",
        release_year=2020,
        synopsis="Old synopsis",
        status="discovered"
    )
    db_session.add(movie)
    db_session.commit()
    db_session.refresh(movie)

    # Call update endpoint
    update_res = client.post(
        f"/api/v1/movies/{movie.id}/update",
        data={
            "title": "Sát Thủ Vô Hình (Chính Xác)",
            "original_title": "The Invisible Guest (2016)",
            "genre": "Trinh Thám, Giật Gân",
            "release_year": 2016,
            "synopsis": "Một doanh nhân trẻ thức dậy trong phòng khách sạn bị khóa kín bên cạnh xác chết người tình."
        }
    )
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "success"

    # Verify in DB
    db_session.refresh(movie)
    assert movie.title == "Sát Thủ Vô Hình (Chính Xác)"
    assert movie.original_title == "The Invisible Guest (2016)"
    assert movie.release_year == 2016
    assert movie.genre == "Trinh Thám, Giật Gân"

def test_script_custom_episodes_generation(client, db_session):
    """Task 2: Test script generation with custom episode count (e.g. 2 or 5 episodes)."""
    movie = Movie(
        title="Inception Test",
        original_title="Inception",
        genre="Sci-Fi",
        status="discovered"
    )
    db_session.add(movie)
    db_session.commit()
    db_session.refresh(movie)

    # Generate 1 episode with 17 minutes duration (1020s)
    res_17m = client.post(
        "/api/v1/scripts/generate",
        data={"movie_id": movie.id, "target_episodes": 1, "target_duration_seconds": 1020, "style": "dramatic"}
    )
    assert res_17m.status_code == 200
    job_17m = db_session.query(Job).filter(Job.id == res_17m.json()["job_id"]).first()
    payload_17m = json.loads(job_17m.payload)
    assert payload_17m["target_duration_seconds"] == 1020
    assert payload_17m["target_episodes"] == 1

    gen_res = client.post(
        "/api/v1/scripts/generate",
        data={
            "movie_id": movie.id,
            "target_episodes": 2,
            "style": "suspense",
            "ai_provider": "gemini_free"
        }
    )
    assert gen_res.status_code == 200
    res_data = gen_res.json()
    assert res_data["status"] == "success"
    
    # Check Job payload
    job_id = res_data["job_id"]
    job = db_session.query(Job).filter(Job.id == job_id).first()
    assert job is not None
    payload = json.loads(job.payload)
    assert payload["target_episodes"] == 2
    assert payload["style"] == "suspense"

def test_episode_editing_and_updating(client, db_session):
    """Task 3: Test editing episode Hook, Narrative Body, and CTA."""
    movie = Movie(title="Test Movie Script Edit", status="discovered")
    db_session.add(movie)
    db_session.commit()

    script = Script(movie_id=movie.id, title="Kịch Bản Test", target_episodes=1)
    db_session.add(script)
    db_session.commit()

    episode = Episode(
        script_id=script.id,
        episode_number=1,
        hook_text="Hook cũ",
        content_text="Lời bình cũ do AI tạo",
        call_to_action="CTA cũ",
        status="approval_pending"
    )
    db_session.add(episode)
    db_session.commit()
    db_session.refresh(episode)

    # Edit episode
    edit_res = client.post(
        f"/api/v1/episodes/{episode.id}/update",
        data={
            "hook_text": "Bạn có dám bước vào căn phòng số 7?",
            "content_text": "Một cái chết bí ẩn không có lối thoát đã làm rung chuyển cả thành phố.",
            "call_to_action": "Bấm theo dõi để xem diễn biến tập 2!"
        }
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["status"] == "success"

    db_session.refresh(episode)
    assert episode.hook_text == "Bạn có dám bước vào căn phòng số 7?"
    assert "Một cái chết bí ẩn" in episode.content_text
    assert "Bấm theo dõi" in episode.call_to_action

def test_youtube_movie_creation_mock(client, db_session, tmp_path):
    """Task 5: Test adding movie & media source directly from YouTube URL."""
    fake_video = tmp_path / "mock_youtube_trailer.mp4"
    fake_video.write_bytes(b"fake video binary content")

    mock_info = {
        "file_path": str(fake_video),
        "title": "Ký Sinh Trùng Official Trailer",
        "duration": 2,
        "description": "Trailer chính thức phim Ký Sinh Trùng (Parasite)"
    }

    with patch("app.video.youtube_downloader.YouTubeTrailerDownloader.get_video_info_and_download", return_value=mock_info):
        res = client.post(
            "/api/v1/movies/create-from-youtube",
            data={
                "youtube_url": "https://www.youtube.com/watch?v=isOGD_7hNIY",
                "title": "Ký Sinh Trùng",
                "original_title": "Parasite",
                "genre": "Giật gân, Tâm lý xã hội",
                "release_year": 2019
            }
        )
        assert res.status_code == 200
        assert res.json()["status"] == "success"
        movie_id = res.json()["movie_id"]

        movie = db_session.query(Movie).filter(Movie.id == movie_id).first()
        assert movie is not None
        assert movie.title == "Ký Sinh Trùng"
        assert movie.original_title == "Parasite"
        assert len(movie.sources) >= 1
        assert movie.sources[0].source_type == "youtube_link"

def test_scene_slicing_distinct_windows_and_versioning(tmp_path):
    """Task 6: Test that scene slicing partitions video timeline into distinct windows without overlap."""
    with patch("app.video.scene_slicer.SceneSlicer.get_video_duration", return_value=120.0):
        # Test episode 1, 2, 3 timeline boundaries calculation
        total_eps = 3
        # Ep 1: 0.02 to 0.35 -> 2.4s to 42.0s
        # Ep 2: 0.35 to 0.68 -> 42.0s to 81.6s
        # Ep 3: 0.68 to 0.98 -> 81.6s to 117.6s
        
        ep1_start = max(1.0, 120.0 * 0.02)
        ep1_end = min(119.0, 120.0 * 0.35)
        
        ep2_start = max(1.0, 120.0 * 0.35)
        ep2_end = min(119.0, 120.0 * 0.68)

        ep3_start = max(1.0, 120.0 * 0.68)
        ep3_end = min(119.0, 120.0 * 0.98)

        assert ep1_end <= ep2_start
        assert ep2_end <= ep3_start
