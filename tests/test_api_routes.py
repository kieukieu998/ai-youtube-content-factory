import pytest
from fastapi.testclient import TestClient
from main import app

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_dashboard_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "AI Movie Content Factory" in response.text

def test_movies_page(client):
    response = client.get("/movies")
    assert response.status_code == 200
    assert "Kho Phim" in response.text

def test_scripts_page(client):
    response = client.get("/scripts")
    assert response.status_code == 200
    assert "Kịch Bản" in response.text

def test_videos_page(client):
    response = client.get("/videos")
    assert response.status_code == 200
    assert "Thư Viện Video" in response.text

def test_jobs_page(client):
    response = client.get("/jobs")
    assert response.status_code == 200
    assert "Hàng Đợi" in response.text

def test_settings_page_and_save(client):
    response = client.get("/settings")
    assert response.status_code == 200

    save_response = client.post(
        "/api/v1/settings/save",
        data={
            "default_ai_provider": "gemini_free",
            "operation_mode": "semi_auto",
            "default_tts_voice": "vi-VN-HoaiMyNeural",
            "daily_budget_limit_usd": "0.0"
        }
    )
    assert save_response.status_code == 200
    assert save_response.json()["status"] == "success"

def test_emergency_stop_and_resume(client):
    stop_res = client.post("/api/v1/jobs/emergency-stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["status"] == "success"

    resume_res = client.post("/api/v1/jobs/resume")
    assert resume_res.status_code == 200
    assert resume_res.json()["status"] == "success"
