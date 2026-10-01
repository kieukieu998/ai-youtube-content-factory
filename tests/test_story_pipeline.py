import pytest
from app.story.story_service import StoryService
from app.story.character_parser import CharacterParser
from app.database.models import Story

def test_story_service_text_and_duration():
    text = "Ngày xửa ngày xưa, ở một ngôi làng nhỏ ven sông, có một cậu bé rất yêu thích đọc sách.\n\nMỗi buổi chiều, cậu lại ngồi dưới gốc đa để ngắm hoàng hôn."
    cleaned = StoryService.clean_text(text)
    assert len(cleaned) > 0
    words = StoryService.get_word_count(cleaned)
    assert words > 20
    est_dur = StoryService.estimate_duration_seconds(cleaned)
    assert est_dur > 0

@pytest.mark.asyncio
async def test_character_parser_rule_and_dialogue():
    content = """Ngày xưa, ở làng kia có một cô bé rất hiếu thảo.
Một hôm, bà lão nói với cô: "Cháu hãy vào rừng hái nấm nhé!"
Cô bé vui vẻ đáp: "Vâng ạ, cháu đi ngay đây bà!"
Ông lão đứng gần đó cũng cười: "Nhớ về sớm kẻo trời tối cháu nhé."
"""
    parsed = await CharacterParser.parse_story(content)
    assert len(parsed.segments) >= 3
    assert len(parsed.characters) >= 2

def test_story_crud_and_quick_video_routes(client):
    # 1. Access /stories UI page
    page_res = client.get("/stories")
    assert page_res.status_code == 200
    assert "Studio Tạo Video Truyện Đa Giọng AI" in page_res.text

    # 2. 1-Click Quick Video Creation
    quick_res = client.post(
        "/api/stories/quick-create-video",
        json={
            "title": "Chuyện Cô Bé Quàng Khăn Đỏ",
            "author": "Truyện cổ Grimm",
            "content": "Ngày xưa có một cô bé rất đáng yêu. Mẹ cô may cho cô một chiếc khăn đỏ nên ai cũng gọi cô là Cô Bé Quàng Khăn Đỏ.",
            "video_aspect": "16:9"
        }
    )
    assert quick_res.status_code == 200
    data = quick_res.json()
    assert data["status"] == "success"
    assert "job_id" in data
    story_id = data["story_id"]

    # 3. Retrieve story list
    list_res = client.get("/api/stories")
    assert list_res.status_code == 200
    stories = list_res.json()
    assert any(s["id"] == story_id for s in stories)

    # 4. Get story detail
    detail_res = client.get(f"/api/stories/{story_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["title"] == "Chuyện Cô Bé Quàng Khăn Đỏ"
    assert len(detail["paragraphs"]) >= 1

    # 5. Delete story
    del_res = client.delete(f"/api/stories/{story_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"

def test_ken_burns_filter_patterns():
    from app.story.story_video_renderer import StoryVideoRenderer

    # Verify 4 distinct cinematic patterns
    for p in range(4):
        f = StoryVideoRenderer.build_ken_burns_filter(
            width=1080,
            height=1920,
            duration=5.0,
            pattern_idx=p,
            intensity=0.18,
            fps=24
        )
        assert "zoompan=" in f
        assert "s=1080x1920" in f
        assert "fps=24" in f
        assert "scale=" in f
        assert "crop=" in f

@pytest.mark.asyncio
async def test_cinematic_shot_prompts():
    from app.story.story_image_generator import StoryImageGenerator

    segments = [
        {"text": "Ngày xửa ngày xưa có một chàng tiều phu hiền lành.", "speaker_name": "Người dẫn chuyện", "emotion": "neutral"},
        {"text": "Bà ơi cháu muốn giúp bà đốn củi!", "speaker_name": "Cậu bé", "emotion": "excited"}
    ]
    shot_prompts = await StoryImageGenerator.generate_cinematic_shot_prompts("Chuyện Tiều Phu", segments, aspect_ratio="9:16")
    assert len(shot_prompts) == 2
    assert shot_prompts[0]["shot_no"] == 1
    assert "Cinematic" in shot_prompts[0]["prompt"]
    assert "Chuyện Tiều Phu" in shot_prompts[0]["prompt"]
    assert "Người dẫn chuyện" in shot_prompts[0]["speaker"]
    assert "Cậu bé" in shot_prompts[1]["speaker"]

@pytest.mark.asyncio
async def test_character_parser_with_camera_cues():
    content = 'Bà lão nhìn ra cửa sổ: "Ai ngoài đó đấy?"\nNgười lạ đáp: "Là tôi đây."'
    parsed = await CharacterParser.parse_story(content)
    assert len(parsed.segments) >= 2
    for seg in parsed.segments:
        assert seg.camera_cue in ["wide_establishing", "medium_shot", "close_up", "low_angle", "tracking_shot"]

