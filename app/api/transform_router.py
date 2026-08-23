import os
import json
import shutil
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from starlette.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Video, Job, Movie

router = APIRouter()

@router.get("/transform", response_class=HTMLResponse)
async def transform_page(request: Request, db: Session = Depends(get_db)):
    """Render the 1:1 Anti-Copyright Video Transformer page."""
    transformed_videos = db.query(Video).filter(Video.video_type == "transformed_1_1").order_by(Video.created_at.desc()).all()
    existing_movies = db.query(Movie).order_by(Movie.created_at.desc()).all()

    return templates.TemplateResponse(
        request=request,
        name="transform.html",
        context={
            "transformed_videos": transformed_videos,
            "existing_movies": existing_movies
        }
    )

@router.post("/api/v1/videos/transform")
async def trigger_video_transform(
    youtube_url: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    aspect_ratio: str = Form("original"), # "original", "blurred_stack_9_16", "center_crop_9_16"
    pitch_shift: float = Form(1.02),
    enable_audio_eq: bool = Form(True),
    enable_hflip: bool = Form(False),
    enable_color_grading: bool = Form(True),
    enable_micro_zoom: bool = Form(True),
    source_file_path: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Trigger a background job to transform video with anti-copyright 1:1 filters."""
    if not youtube_url and not source_file_path:
        raise HTTPException(status_code=400, detail="Vui lòng cung cấp link YouTube hoặc chọn file video nguồn.")

    from app.database.models import MovieSource

    # Auto-resolve title if not explicitly entered by user
    actual_title = (title or "").strip()
    if not actual_title or actual_title == "Video Chuyển Đổi":
        if source_file_path:
            ms = db.query(MovieSource).filter(MovieSource.file_path == source_file_path.strip()).first()
            if ms and ms.movie:
                actual_title = ms.movie.title
            else:
                actual_title = Path(source_file_path.strip()).stem
        elif youtube_url:
            actual_title = "Video YouTube 1:1"
        else:
            actual_title = "Video 1:1"

    payload = {
        "youtube_url": youtube_url.strip() if youtube_url else None,
        "file_path": source_file_path.strip() if source_file_path else None,
        "title": actual_title,
        "aspect_ratio": aspect_ratio,
        "pitch_shift": pitch_shift,
        "enable_audio_eq": enable_audio_eq,
        "enable_hflip": enable_hflip,
        "enable_color_grading": enable_color_grading,
        "enable_micro_zoom": enable_micro_zoom
    }

    job = Job(
        job_type="VideoTransformJob",
        status="pending",
        payload=json.dumps(payload)
    )
    db.add(job)
    db.commit()

    return JSONResponse({
        "status": "success",
        "message": f"Đã thêm tác vụ xử lý lách bản quyền 1:1 cho '{actual_title}' vào hàng đợi!",
        "job_id": job.id
    })

@router.post("/api/v1/videos/upload-and-transform")
async def upload_and_transform(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    aspect_ratio: str = Form("original"),
    pitch_shift: float = Form(1.02),
    enable_audio_eq: bool = Form(True),
    enable_hflip: bool = Form(False),
    enable_color_grading: bool = Form(True),
    enable_micro_zoom: bool = Form(True),
    db: Session = Depends(get_db)
):
    """Upload MP4 file from computer and queue a 1:1 transformation job."""
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="Vui lòng chọn file video hợp lệ.")

    upload_folder = settings.SOURCE_MEDIA_DIR / "uploads"
    upload_folder.mkdir(parents=True, exist_ok=True)

    dest_path = upload_folder / f"raw_{file.filename}"
    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    actual_title = title.strip() if title and title.strip() else Path(file.filename).stem

    payload = {
        "youtube_url": None,
        "file_path": str(dest_path),
        "title": actual_title,
        "aspect_ratio": aspect_ratio,
        "pitch_shift": pitch_shift,
        "enable_audio_eq": enable_audio_eq,
        "enable_hflip": enable_hflip,
        "enable_color_grading": enable_color_grading,
        "enable_micro_zoom": enable_micro_zoom
    }

    job = Job(
        job_type="VideoTransformJob",
        status="pending",
        payload=json.dumps(payload)
    )
    db.add(job)
    db.commit()

    return JSONResponse({
        "status": "success",
        "message": f"Đã tải file '{file.filename}' lên và thêm tác vụ xử lý 1:1 vào hàng đợi!",
        "job_id": job.id
    })
