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
    split_parts: int = Form(1),
    enable_dubbing: bool = Form(False),
    source_language: str = Form("auto"),
    vietnamese_voice: str = Form("vi-VN-HoaiMyNeural"),
    dubbing_mode: str = Form("voiceover"),
    burn_subtitles: bool = Form(False),
    movie_id: Optional[int] = Form(None),
    source_file_path: Optional[str] = Form(None),
    source_file_paths: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """Trigger background job(s) to transform video(s) with anti-copyright 1:1 filters and optional AI Dubbing."""
    from app.database.models import MovieSource, Movie

    target_paths = []
    if source_file_paths:
        try:
            parsed = json.loads(source_file_paths)
            if isinstance(parsed, list):
                target_paths = [p for p in parsed if p]
        except Exception:
            target_paths = [p.strip() for p in source_file_paths.split(",") if p.strip()]
    elif source_file_path:
        target_paths = [source_file_path.strip()]

    if not youtube_url and not target_paths:
        raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất 1 video nguồn từ Kho Phim hoặc nhập link YouTube.")

    movie = db.query(Movie).filter(Movie.id == movie_id).first() if movie_id else None

    # Handle YouTube URL
    if youtube_url:
        actual_title = (title or "").strip() or "Video YouTube 1:1"
        payload = {
            "youtube_url": youtube_url.strip(),
            "file_path": None,
            "movie_id": movie_id,
            "title": actual_title,
            "aspect_ratio": aspect_ratio,
            "pitch_shift": pitch_shift,
            "enable_audio_eq": enable_audio_eq,
            "enable_hflip": enable_hflip,
            "enable_color_grading": enable_color_grading,
            "enable_micro_zoom": enable_micro_zoom,
            "split_parts": split_parts,
            "enable_dubbing": enable_dubbing,
            "source_language": source_language,
            "vietnamese_voice": vietnamese_voice,
            "dubbing_mode": dubbing_mode,
            "burn_subtitles": burn_subtitles
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
            "job_ids": [job.id]
        })

    # Handle multiple or single local file paths from Movie Library
    created_jobs = []
    for idx, path_str in enumerate(target_paths, 1):
        # Resolve movie and title
        item_movie_id = movie_id
        if not item_movie_id:
            ms = db.query(MovieSource).filter(MovieSource.file_path == path_str).first()
            if ms:
                item_movie_id = ms.movie_id
                if not movie:
                    movie = ms.movie

        file_name = Path(path_str).name
        if len(target_paths) > 1:
            item_title = f"{movie.title if movie else 'Phim'} - Video {idx} ({file_name})"
        else:
            item_title = (title or "").strip() or (f"{movie.title} ({file_name})" if movie else file_name)

        payload = {
            "youtube_url": None,
            "file_path": path_str,
            "movie_id": item_movie_id,
            "title": item_title,
            "aspect_ratio": aspect_ratio,
            "pitch_shift": pitch_shift,
            "enable_audio_eq": enable_audio_eq,
            "enable_hflip": enable_hflip,
            "enable_color_grading": enable_color_grading,
            "enable_micro_zoom": enable_micro_zoom,
            "split_parts": split_parts,
            "enable_dubbing": enable_dubbing,
            "source_language": source_language,
            "vietnamese_voice": vietnamese_voice,
            "dubbing_mode": dubbing_mode,
            "burn_subtitles": burn_subtitles
        }
        job = Job(
            job_type="VideoTransformJob",
            status="pending",
            payload=json.dumps(payload)
        )
        db.add(job)
        created_jobs.append(job)

    db.commit()

    movie_name = movie.title if movie else "phim đã chọn"
    return JSONResponse({
        "status": "success",
        "message": f"Đã thêm {len(created_jobs)} video của '{movie_name}' vào hàng đợi xử lý lách bản quyền 1:1!",
        "job_ids": [j.id for j in created_jobs]
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
    split_parts: int = Form(1),
    enable_dubbing: bool = Form(False),
    source_language: str = Form("auto"),
    vietnamese_voice: str = Form("vi-VN-HoaiMyNeural"),
    dubbing_mode: str = Form("voiceover"),
    burn_subtitles: bool = Form(False),
    db: Session = Depends(get_db)
):
    """Upload MP4 file from computer and queue a 1:1 transformation job with optional AI Dubbing."""
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
        "enable_micro_zoom": enable_micro_zoom,
        "split_parts": split_parts,
        "enable_dubbing": enable_dubbing,
        "source_language": source_language,
        "vietnamese_voice": vietnamese_voice,
        "dubbing_mode": dubbing_mode,
        "burn_subtitles": burn_subtitles
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
