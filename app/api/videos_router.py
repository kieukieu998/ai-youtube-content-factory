import json
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from starlette.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Video, Episode, Job

router = APIRouter()

@router.get("/videos", response_class=HTMLResponse)
async def videos_page(request: Request, db: Session = Depends(get_db)):
    videos = db.query(Video).order_by(Video.created_at.desc()).all()
    approved_episodes = db.query(Episode).filter(Episode.status.in_(["approved", "draft"])).all()
    return templates.TemplateResponse(
        request=request, 
        name="videos.html",
        context={
            "videos": videos,
            "approved_episodes": approved_episodes
        }
    )

@router.post("/api/v1/videos/render")
async def trigger_render_video(
    episode_id: int = Form(...),
    db: Session = Depends(get_db)
):
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Không tìm thấy tập phim")

    job = Job(
        job_type="RenderEpisodeJob",
        status="pending",
        payload=json.dumps({"episode_id": episode_id})
    )
    db.add(job)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã thêm tác vụ render video tập {episode.episode_number} vào hàng đợi", "job_id": job.id})

@router.get("/api/v1/videos/{video_id}/stream")
async def stream_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video or not Path(video.file_path).exists():
        raise HTTPException(status_code=404, detail="Video không tồn tại")
    return FileResponse(video.file_path, media_type="video/mp4")

from typing import List
from pydantic import BaseModel

class BulkDeleteRequest(BaseModel):
    ids: List[int]

@router.post("/api/v1/videos/bulk-delete")
async def bulk_delete_videos(req: BulkDeleteRequest, db: Session = Depends(get_db)):
    if not req.ids:
        raise HTTPException(status_code=400, detail="Danh sách ID rỗng")
    
    videos = db.query(Video).filter(Video.id.in_(req.ids)).all()
    count = len(videos)
    for v in videos:
        if v.file_path and Path(v.file_path).exists():
            try:
                Path(v.file_path).unlink()
            except Exception:
                pass
        db.delete(v)
        
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã xóa thành công {count} video!"})

@router.delete("/api/v1/videos/{video_id}")
async def delete_video(video_id: int, db: Session = Depends(get_db)):
    video = db.query(Video).filter(Video.id == video_id).first()
    if not video:
        raise HTTPException(status_code=404, detail="Không tìm thấy video")
    
    # Delete physical file if exists
    if video.file_path and Path(video.file_path).exists():
        try:
            Path(video.file_path).unlink()
        except Exception:
            pass
            
    db.delete(video)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã xóa video #{video_id} thành công!"})
