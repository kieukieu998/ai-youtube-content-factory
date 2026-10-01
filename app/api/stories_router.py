import os
import json
from typing import Optional, List
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Story, Job, Setting
from app.story.story_service import StoryService
from app.story.audiobook_generator import AudiobookGenerator
from app.story.story_animation_engine import StoryAnimationEngine

router = APIRouter()

class StoryCreateSchema(BaseModel):
    title: Optional[str] = "Truyện chưa đặt tên"
    author: Optional[str] = "Khuyết danh"
    genre: Optional[str] = "Truyện ngắn"
    content: str
    video_aspect: Optional[str] = "16:9"

class StoryQuickVideoSchema(BaseModel):
    title: Optional[str] = "Truyện chưa đặt tên"
    author: Optional[str] = "Khuyết danh"
    content: str
    video_aspect: Optional[str] = "16:9"
    motion_mode: Optional[str] = "ken_burns"

class StoryUpdateSchema(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    genre: Optional[str] = None
    content: Optional[str] = None
    video_aspect: Optional[str] = None

def normalize_character_list(characters_raw) -> List[dict]:
    """Normalizes characters into structured items: [{"name": "Mèo con", "role": "Nhân vật", "avatar": "M"}]"""
    if not characters_raw:
        return []
    result = []
    for c in characters_raw:
        if isinstance(c, dict):
            name = c.get("name") or c.get("speaker_name") or "Nhân vật"
            role = c.get("role") or c.get("character_type") or "Nhân vật"
        elif isinstance(c, str):
            name = c.strip()
            role = "Người dẫn chuyện" if name == "Người dẫn chuyện" else "Nhân vật"
        else:
            continue
        if not name:
            continue
        avatar = name[0].upper()
        result.append({"name": name, "role": role, "avatar": avatar})
    return result

def format_file_size(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    try:
        size_bytes = os.path.getsize(path)
        if size_bytes >= 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"
        elif size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        elif size_bytes >= 1024:
            return f"{size_bytes / 1024:.0f} KB"
        return f"{size_bytes} B"
    except Exception:
        return None

def sync_story_status_with_job(story: Story, db: Session):
    """Ensure story status matches the actual background Job status."""
    related_job = db.query(Job).filter(
        Job.job_type.in_(["StoryVideoRenderJob", "StoryAudioJob", "StoryAnimationJob"]),
        Job.payload.like(f'%"story_id": {story.id}%')
    ).order_by(Job.id.desc()).first()
    if not related_job:
        return

    if related_job.status in ["pending", "processing"]:
        if story.status not in ["rendering_video", "processing_audio"]:
            story.status = "rendering_video"
            story.error_message = None
            try:
                db.commit()
            except Exception:
                db.rollback()
    elif related_job.status in ["failed", "cancelled"]:
        if story.status != "failed":
            story.status = "failed"
            story.error_message = related_job.error_message or "Tác vụ thất bại"
            try:
                db.commit()
            except Exception:
                db.rollback()
    elif related_job.status == "completed":
        if story.status != "completed":
            story.status = "completed"
            story.error_message = None
            try:
                db.commit()
            except Exception:
                db.rollback()

@router.get("/stories", response_class=HTMLResponse)
async def get_stories_page(request: Request, db: Session = Depends(get_db)):
    """Render the main Story Reader & Video Generator UI."""
    stories = db.query(Story).order_by(Story.created_at.desc()).all()
    stories_data = []
    for s in stories:
        sync_story_status_with_job(s, db)
        chars = []
        if s.characters_json:
            try:
                chars = json.loads(s.characters_json)
            except Exception:
                pass
        chars = normalize_character_list(chars)
        
        video_9x16 = f"media/output/stories/story_{s.id}_9x16.mp4"
        video_16x9 = f"media/output/stories/story_{s.id}_16x9.mp4"
        size_9x16 = format_file_size(video_9x16)
        size_16x9 = format_file_size(video_16x9)
        main_size = format_file_size(s.video_path)
        video_size = main_size or size_9x16 or size_16x9
        has_9x16 = bool(size_9x16)
        has_16x9 = bool(size_16x9)
        is_both = (s.video_aspect in ["both", "all", "2", "9:16 & 16:9", "16:9 & 9:16"]) or (has_9x16 and has_16x9)

        stories_data.append({
            "story": s,
            "characters": chars,
            "video_size": video_size,
            "video_size_9x16": size_9x16,
            "video_size_16x9": size_16x9,
            "has_9x16": has_9x16,
            "has_16x9": has_16x9,
            "is_both": is_both
        })

    latest_story_id = stories[0].id if stories else None

    return templates.TemplateResponse(
        request=request,
        name="stories.html",
        context={
            "active_page": "stories",
            "stories_data": stories_data,
            "stories": stories,
            "latest_story_id": latest_story_id
        }
    )

@router.get("/api/stories")
async def list_stories(db: Session = Depends(get_db)):
    """Get list of all stories."""
    stories = db.query(Story).order_by(Story.created_at.desc()).all()
    results = []
    for s in stories:
        sync_story_status_with_job(s, db)
        characters = []
        if s.characters_json:
            try:
                characters = json.loads(s.characters_json)
            except Exception:
                pass
        characters = normalize_character_list(characters)
        
        video_9x16 = f"media/output/stories/story_{s.id}_9x16.mp4"
        video_16x9 = f"media/output/stories/story_{s.id}_16x9.mp4"
        size_9x16 = format_file_size(video_9x16)
        size_16x9 = format_file_size(video_16x9)
        main_size = format_file_size(s.video_path)
        video_size = main_size or size_9x16 or size_16x9
        has_9x16 = bool(size_9x16)
        has_16x9 = bool(size_16x9)
        is_both = (s.video_aspect in ["both", "all", "2", "9:16 & 16:9", "16:9 & 9:16"]) or (has_9x16 and has_16x9)

        results.append({
            "id": s.id,
            "title": s.title,
            "author": s.author,
            "genre": s.genre,
            "word_count": s.word_count,
            "duration_seconds": s.duration_seconds,
            "characters": characters,
            "video_aspect": s.video_aspect,
            "is_both": is_both,
            "has_9x16": has_9x16,
            "has_16x9": has_16x9,
            "audio_path": s.audio_path,
            "video_path": s.video_path,
            "video_size": video_size,
            "video_size_9x16": size_9x16,
            "video_size_16x9": size_16x9,
            "video_path_9x16": video_9x16 if os.path.exists(video_9x16) else None,
            "video_path_16x9": video_16x9 if os.path.exists(video_16x9) else None,
            "status": s.status,
            "error_message": s.error_message,
            "created_at": s.created_at.strftime("%d/%m/%Y %H:%M") if s.created_at else ""
        })
    return results

@router.get("/api/stories/{story_id}")
async def get_story_detail(story_id: int, db: Session = Depends(get_db)):
    """Get detailed info of a single story."""
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")
    
    sync_story_status_with_job(story, db)
    paragraphs = StoryService.split_into_readable_paragraphs(story.content)
    characters = []
    if story.characters_json:
        try:
            characters = json.loads(story.characters_json)
        except Exception:
            pass
    characters = normalize_character_list(characters)
    
    video_9x16 = f"media/output/stories/story_{story.id}_9x16.mp4"
    video_16x9 = f"media/output/stories/story_{story.id}_16x9.mp4"
    size_9x16 = format_file_size(video_9x16)
    size_16x9 = format_file_size(video_16x9)
    main_size = format_file_size(story.video_path)
    video_size = main_size or size_9x16 or size_16x9
    has_9x16 = bool(size_9x16)
    has_16x9 = bool(size_16x9)
    is_both = (story.video_aspect in ["both", "all", "2", "9:16 & 16:9", "16:9 & 9:16"]) or (has_9x16 and has_16x9)

    return {
        "id": story.id,
        "title": story.title,
        "author": story.author,
        "genre": story.genre,
        "content": story.content,
        "paragraphs": paragraphs,
        "characters": characters,
        "word_count": story.word_count,
        "duration_seconds": story.duration_seconds,
        "video_aspect": story.video_aspect,
        "is_both": is_both,
        "has_9x16": has_9x16,
        "has_16x9": has_16x9,
        "audio_path": story.audio_path,
        "video_path": story.video_path,
        "video_size": video_size,
        "video_size_9x16": size_9x16,
        "video_size_16x9": size_16x9,
        "video_path_9x16": video_9x16 if os.path.exists(video_9x16) else None,
        "video_path_16x9": video_16x9 if os.path.exists(video_16x9) else None,
        "status": story.status,
        "error_message": story.error_message,
        "created_at": story.created_at.strftime("%d/%m/%Y %H:%M") if story.created_at else ""
    }

@router.post("/api/stories/create")
async def create_story(data: StoryCreateSchema, db: Session = Depends(get_db)):
    """Create a new story with word count and duration estimation."""
    cleaned_content = StoryService.clean_text(data.content)
    if not cleaned_content:
        raise HTTPException(status_code=400, detail="Nội dung truyện không được để trống")

    word_count = StoryService.get_word_count(cleaned_content)
    est_duration = StoryService.estimate_duration_seconds(cleaned_content)

    story = Story(
        title=(data.title or "Truyện chưa đặt tên").strip(),
        author=(data.author or "Khuyết danh").strip(),
        genre=(data.genre or "Truyện ngắn").strip(),
        content=cleaned_content,
        video_aspect=data.video_aspect or "16:9",
        word_count=word_count,
        duration_seconds=est_duration,
        status="draft"
    )
    db.add(story)
    db.commit()
    db.refresh(story)

    return {"status": "success", "story_id": story.id, "message": "Tạo truyện thành công"}

@router.post("/api/stories/quick-create-video")
async def quick_create_video(data: StoryQuickVideoSchema, db: Session = Depends(get_db)):
    """
    1-Click Video Creation: Save story and instantly enqueue Multi-Voice Video Rendering Job.
    """
    cleaned_content = StoryService.clean_text(data.content)
    if not cleaned_content:
        raise HTTPException(status_code=400, detail="Nội dung truyện không được để trống")

    word_count = StoryService.get_word_count(cleaned_content)
    est_duration = StoryService.estimate_duration_seconds(cleaned_content)

    story = Story(
        title=(data.title or "Truyện chưa đặt tên").strip(),
        author=(data.author or "Khuyết danh").strip(),
        genre="Truyện ngắn",
        content=cleaned_content,
        video_aspect=data.video_aspect or "16:9",
        word_count=word_count,
        duration_seconds=est_duration,
        status="rendering_video"
    )
    db.add(story)
    db.commit()
    db.refresh(story)

    # Dispatch StoryVideoRenderJob
    job = Job(
        job_type="StoryVideoRenderJob",
        status="pending",
        progress=0,
        payload=json.dumps({
            "story_id": story.id,
            "aspect_ratio": data.video_aspect or "16:9",
            "motion_mode": data.motion_mode or "ken_burns"
        })
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return {
        "status": "success",
        "story_id": story.id,
        "job_id": job.id,
        "message": "AI đã bắt đầu phân tích nhân vật và render video tự động!"
    }

@router.post("/api/stories/{story_id}/update")
async def update_story(story_id: int, data: StoryUpdateSchema, db: Session = Depends(get_db)):
    """Update story metadata or content."""
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    if data.title is not None:
        story.title = data.title.strip()
    if data.author is not None:
        story.author = data.author.strip()
    if data.genre is not None:
        story.genre = data.genre.strip()
    if data.content is not None:
        cleaned_content = StoryService.clean_text(data.content)
        story.content = cleaned_content
        story.word_count = StoryService.get_word_count(cleaned_content)
        story.duration_seconds = StoryService.estimate_duration_seconds(cleaned_content)
    if data.video_aspect is not None:
        story.video_aspect = data.video_aspect

    db.commit()
    return {"status": "success", "message": "Cập nhật thành công"}

@router.post("/api/stories/{story_id}/generate-video")
async def generate_video_job(
    story_id: int,
    aspect_ratio: Optional[str] = Form("16:9"),
    motion_mode: Optional[str] = Form("ken_burns"),
    db: Session = Depends(get_db)
):
    """Queue background job to render multi-voice audiobook listening video."""
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    story.video_aspect = aspect_ratio
    story.status = "rendering_video"
    db.commit()

    # Create background job in Job Queue
    job = Job(
        job_type="StoryVideoRenderJob",
        status="pending",
        progress=0,
        payload=json.dumps({
            "story_id": story.id,
            "aspect_ratio": aspect_ratio,
            "motion_mode": motion_mode or "ken_burns"
        })
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return {"status": "success", "job_id": job.id, "message": "Đã bắt đầu tác vụ render video nghe truyện..."}

@router.post("/api/stories/{story_id}/upload-comic-reference")
async def upload_comic_reference(
    story_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload comic/reference image for multi-shot scene breakdown and character modeling."""
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    upload_dir = Path("media/working/stories/references")
    upload_dir.mkdir(parents=True, exist_ok=True)
    ext = Path(file.filename or "image.png").suffix.lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        ext = ".png"

    dest_file = upload_dir / f"comic_ref_{story_id}{ext}"
    content = await file.read()
    with open(dest_file, "wb") as f:
        f.write(content)

    rel_path = str(dest_file).replace("\\", "/")
    return {
        "status": "success",
        "file_path": rel_path,
        "url": f"/{rel_path}",
        "message": "Tải ảnh truyện tranh tham chiếu thành công!"
    }

@router.post("/api/stories/{story_id}/breakdown-storyboard")
async def breakdown_storyboard(
    story_id: int,
    reference_image_path: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Parses story into Character Bible and discrete Storyboard Shots with camera cues and preview frames.
    """
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    ref_img = reference_image_path
    if not ref_img:
        # Check if default uploaded reference exists
        for ext in [".png", ".jpg", ".jpeg", ".webp"]:
            candidate = Path(f"media/working/stories/references/comic_ref_{story_id}{ext}")
            if candidate.exists():
                ref_img = str(candidate).replace("\\", "/")
                break

    try:
        storyboard = await StoryAnimationEngine.generate_storyboard_breakdown(
            story_id=story.id,
            title=story.title,
            content=story.content,
            reference_image_path=ref_img
        )
        # Cache characters to story model if not present
        if not story.characters_json and storyboard.get("characters"):
            story.characters_json = json.dumps(storyboard["characters"], ensure_ascii=False)
            db.commit()

        return {
            "status": "success",
            "storyboard": storyboard,
            "message": f"Đã phân rã thành công {storyboard.get('total_shots', 0)} phân cảnh Storyboard!"
        }
    except Exception as e:
        logger.error(f"Error generating storyboard for Story #{story_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Không thể tạo Storyboard: {e}")

@router.post("/api/stories/{story_id}/render-animation")
async def render_story_animation(
    story_id: int,
    aspect_ratio: Optional[str] = Form("9:16"),
    video_engine: Optional[str] = Form("motion_25d"),
    reference_image_path: Optional[str] = Form(None),
    bgm_name: Optional[str] = Form("suspense_bgm.mp3"),
    db: Session = Depends(get_db)
):
    """
    Queue background job to render AI Multi-Shot Comic/Character Animation Video.
    """
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    story.video_aspect = aspect_ratio
    story.status = "rendering_video"
    db.commit()

    ref_img = reference_image_path
    if not ref_img:
        for ext in [".png", ".jpg", ".jpeg", ".webp"]:
            candidate = Path(f"media/working/stories/references/comic_ref_{story_id}{ext}")
            if candidate.exists():
                ref_img = str(candidate).replace("\\", "/")
                break

    # Dispatch StoryAnimationJob
    job = Job(
        job_type="StoryAnimationJob",
        status="pending",
        progress=0,
        payload=json.dumps({
            "story_id": story.id,
            "aspect_ratio": aspect_ratio or "9:16",
            "video_engine": video_engine or "motion_25d",
            "reference_image_path": ref_img,
            "bgm_name": bgm_name or "suspense_bgm.mp3"
        })
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    return {
        "status": "success",
        "job_id": job.id,
        "message": "AI đã bắt đầu phân cảnh và render phim hoạt hình đa góc máy!"
    }

@router.delete("/api/stories/{story_id}")
async def delete_story(story_id: int, db: Session = Depends(get_db)):
    """Delete a story and clean up its audio and video files."""
    story = db.query(Story).filter(Story.id == story_id).first()
    if not story:
        raise HTTPException(status_code=404, detail="Story not found")

    # Clean up audio file
    if story.audio_path and os.path.exists(story.audio_path):
        try:
            os.remove(story.audio_path)
        except Exception as e:
            logger.warning(f"Could not remove audio file {story.audio_path}: {e}")

    # Clean up video file
    if story.video_path and os.path.exists(story.video_path):
        try:
            os.remove(story.video_path)
        except Exception as e:
            logger.warning(f"Could not remove video file {story.video_path}: {e}")

    db.delete(story)
    db.commit()

    return {"status": "success", "message": "Xóa truyện và file media thành công"}
