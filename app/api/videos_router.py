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

import re

def enrich_video_display(v: Video, movie_title: str = ""):
    """Enrich video object with display_label, display_sub_badge, play_title, and sort_order."""
    if v.video_type == "transformed_1_1":
        title = (v.title or Path(v.file_path).stem).strip()
        mv_t = (movie_title or "").strip()
        
        # Check if title has double episode notation like "Tập 01 – Tập 1" or "Tập 01 - Tập 2"
        match_combo = re.search(r'(Tập\s*\d+\s*[-–—]\s*Tập\s*\d+)', title, re.IGNORECASE)
        match_single = re.search(r'(Tập\s*\d+)', title, re.IGNORECASE)
        
        is_split_part = False
        part_num = 1
        if match_combo:
            is_split_part = True
            v.display_label = match_combo.group(1)
            p_match = re.search(r'[-–—]\s*Tập\s*(\d+)$', match_combo.group(1), re.IGNORECASE)
            if p_match:
                part_num = int(p_match.group(1))
        elif mv_t and title.lower().startswith(mv_t.lower()) and title.lower() != mv_t.lower():
            suffix = title[len(mv_t):].strip()
            match_suffix = re.search(r'^[-–—_]\s*(?:Tập|Tap|Part)\s*(\d+)$', suffix, re.IGNORECASE)
            if match_suffix:
                is_split_part = True
                part_num = int(match_suffix.group(1))
                if match_single:
                    v.display_label = f"{match_single.group(1)} – Tập {part_num}"
                else:
                    v.display_label = f"Tập {part_num}"
        
        if not is_split_part:
            # Full 1:1 original
            if match_single:
                v.display_label = f"{match_single.group(1)} - Full"
                main_ep = int(re.search(r'\d+', match_single.group(1)).group(0))
                v.sort_order = (main_ep, 0, str(v.created_at or ""))
            else:
                v.display_label = "Bản 1:1 - Full"
                v.sort_order = (0, 0, str(v.created_at or ""))
        else:
            main_ep = 0
            if match_single:
                main_ep = int(re.search(r'\d+', match_single.group(1)).group(0))
            v.sort_order = (main_ep, part_num, str(v.created_at or ""))
            
        v.display_sub_badge = None
        v.play_title = title
    else:
        ep_num = v.episode.episode_number if v.episode else 1
        v.display_label = f"Tập {ep_num}"
        v.display_sub_badge = None
        v.sort_order = (ep_num, 0, str(v.created_at or ""))
        v.play_title = f"{movie_title} - Tập {ep_num}"


def process_movie_videos_with_versions(v_list: List[Video], movie_title: str = "") -> List[Video]:
    """Enrich all videos and assign version badges (v1, v2, v3...) per unique episode/part label."""
    from collections import defaultdict

    # 1. Base enrichment
    for v in v_list:
        enrich_video_display(v, movie_title)

    # 2. Group by display_label to assign version index
    label_map = defaultdict(list)
    for v in sorted(v_list, key=lambda x: (x.created_at or x.id or 0)):
        label_map[v.display_label].append(v)

    for label, group in label_map.items():
        for idx, vid in enumerate(group, 1):
            vid.render_version = idx
            vid.render_version_label = f"v{idx}"
            vid.display_sub_badge = f"v{idx}"
            if vid.video_type == "transformed_1_1":
                clean_t = vid.title or Path(vid.file_path).stem
                vid.play_title = f"{clean_t} (v{idx})"
            else:
                vid.play_title = f"{movie_title} - {vid.display_label} (v{idx})"
            base_order = getattr(vid, "sort_order", (0, 0, ""))
            vid.sort_order = (base_order[0], base_order[1], idx, str(vid.created_at or ""))

    return sorted(v_list, key=lambda x: getattr(x, "sort_order", (0, 0, 0, "")))


@router.get("/videos", response_class=HTMLResponse)
async def videos_page(request: Request, db: Session = Depends(get_db)):
    from collections import defaultdict
    from app.database.models import Movie, Script
    
    videos = db.query(Video).order_by(Video.created_at.desc()).all()
    approved_episodes = db.query(Episode).filter(Episode.status.in_(["approved", "draft"])).all()

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
            mv_title = movie.title if movie else ""
            v_list_sorted = process_movie_videos_with_versions(v_list, mv_title)

            script = db.query(Script).filter(Script.movie_id == movie_id).first()
            total_eps = len(script.episodes) if script else len(v_list_sorted)
            
            movie_folders.append({
                "movie": movie,
                "videos": v_list_sorted,
                "rendered_count": len(v_list_sorted),
                "total_episodes": total_eps,
                "is_complete": len(v_list_sorted) >= total_eps and total_eps > 0
            })
        else:
            v_list_sorted = process_movie_videos_with_versions(v_list, "Video Khác")
            movie_folders.append({
                "movie": None,
                "videos": v_list_sorted,
                "rendered_count": len(v_list_sorted),
                "total_episodes": len(v_list_sorted),
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
def stream_video(video_id: int):
    with SessionLocal() as db:
        video = db.query(Video).filter(Video.id == video_id).first()
        if not video:
            raise HTTPException(status_code=404, detail="Video không tồn tại")
        file_path = video.file_path

    if not file_path or not Path(file_path).exists():
        raise HTTPException(status_code=404, detail="File video không tồn tại trên ổ cứng")
    return FileResponse(file_path, media_type="video/mp4")

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
