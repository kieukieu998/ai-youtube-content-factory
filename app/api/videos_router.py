import json
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from starlette.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Video, Episode, Job

router = APIRouter()

@router.get("/videos", response_class=HTMLResponse)
async def videos_page(request: Request, db: Session = Depends(get_db)):
    from collections import defaultdict
    from app.database.models import Movie, Script
    
    videos = db.query(Video).order_by(Video.created_at.desc()).all()
    approved_episodes = db.query(Episode).filter(Episode.status.in_(["approved", "draft"])).all()
    
    # Group videos by Episode to determine version index
    ep_videos_map = defaultdict(list)
    for v in sorted(videos, key=lambda x: x.created_at or x.id):
        ep_videos_map[v.episode_id].append(v)
        
    for ep_id, v_sub_list in ep_videos_map.items():
        for idx, vid in enumerate(v_sub_list, 1):
            vid.render_version = idx
            vid.render_version_label = f"v{idx}"

    # Group videos by Movie Folder
    movie_dict = defaultdict(list)
    for v in videos:
        mid = v.movie_id
        if not mid and v.episode and v.episode.script and v.episode.script.movie:
            mid = v.episode.script.movie.id
            
        if mid:
            movie_dict[mid].append(v)
        else:
            movie_dict[0].append(v)
            
    movie_folders = []
    for movie_id, v_list in movie_dict.items():
        if movie_id != 0:
            movie = db.query(Movie).filter(Movie.id == movie_id).first()
            v_list_sorted = sorted(
                v_list, 
                key=lambda x: (x.episode.episode_number if x.episode else 0, getattr(x, "render_version", 1))
            )
            script = db.query(Script).filter(Script.movie_id == movie_id).first()
            total_eps = len(script.episodes) if script else len(v_list)
            
            movie_folders.append({
                "movie": movie,
                "videos": v_list_sorted,
                "rendered_count": len(v_list_sorted),
                "total_episodes": total_eps,
                "is_complete": len(v_list_sorted) >= total_eps and total_eps > 0
            })
        else:
            movie_folders.append({
                "movie": None,
                "videos": v_list,
                "rendered_count": len(v_list),
                "total_episodes": len(v_list),
                "is_complete": True
            })
            
    return templates.TemplateResponse(
        request=request, 
        name="videos.html",
        context={
            "videos": videos,
            "movie_folders": movie_folders,
            "approved_episodes": approved_episodes
        }
    )

@router.post("/api/v1/videos/render")
async def trigger_render_video(
    episode_id: int = Form(...),
    custom_instruction: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Không tìm thấy tập phim")

    payload_data = {"episode_id": episode_id}
    if custom_instruction and custom_instruction.strip():
        payload_data["custom_instruction"] = custom_instruction.strip()

    job = Job(
        job_type="RenderEpisodeJob",
        status="pending",
        payload=json.dumps(payload_data)
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
