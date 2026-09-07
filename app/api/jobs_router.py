import json
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from starlette.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Job, Movie, Episode, Story
from app.scheduler.job_worker import JobWorker

router = APIRouter()

def enrich_job_info(jobs, db: Session):
    enriched = []
    for j in jobs:
        display_name = j.job_type
        sub_info = ""
        target_url = None
        try:
            payload = json.loads(j.payload) if j.payload else {}
            if j.job_type == "MovieDiscoveryJob":
                genre = payload.get("genre", "")
                display_name = "🔍 Khám Phá Phim Mới"
                sub_info = f"Thể loại: {genre}"
                target_url = "/movies"
            elif j.job_type == "ScriptGenerationJob":
                movie_id = payload.get("movie_id")
                movie = db.query(Movie).filter(Movie.id == movie_id).first()
                display_name = f"✍️ Viết Kịch Bản Phim: {movie.title if movie else f'Movie #{movie_id}'}"
                sub_info = f"{movie.genre or ''}" if movie else ""
                target_url = f"/scripts?movie_id={movie_id}" if movie_id else "/scripts"
            elif j.job_type == "RenderEpisodeJob":
                episode_id = payload.get("episode_id")
                ep = db.query(Episode).filter(Episode.id == episode_id).first()
                if ep and ep.script and ep.script.movie:
                    movie_id = ep.script.movie.id
                    display_name = f"🎬 Render Video 9:16: {ep.script.movie.title}"
                    sub_info = f"Tập {ep.episode_number} — Hook: \"{ep.hook_text or ''}\""
                    target_url = f"/videos?movie_id={movie_id}"
                else:
                    display_name = f"🎬 Render Video (Tập #{episode_id})"
                    target_url = "/videos"
            elif j.job_type == "VideoTransformJob":
                video_title = payload.get("title") or "Video 1:1"
                ratio = payload.get("aspect_ratio", "original")
                ratio_label = "16:9 gốc" if ratio == "original" else ("9:16 Nền mờ" if ratio == "blurred_stack_9_16" else "9:16 Crop")
                pitch = float(payload.get("pitch_shift", 1.02))
                display_name = f"🛡️ Lách Bản Quyền 1:1: {video_title}"
                sub_info = f"Tỉ lệ: {ratio_label} — Pitch: {pitch:+.2f}x"
                target_url = "/transform"
            elif j.job_type in ["StoryVideoRenderJob", "StoryAudioJob"]:
                from app.database.models import Story
                story_id = payload.get("story_id")
                story = db.query(Story).filter(Story.id == story_id).first() if story_id else None
                aspect = payload.get("aspect_ratio", "16:9")
                if j.job_type == "StoryVideoRenderJob":
                    display_name = f"📖 Render Video Truyện: {story.title if story else f'Truyện #{story_id}'}"
                else:
                    display_name = f"🎙️ Lồng Tiếng Đa Giọng: {story.title if story else f'Truyện #{story_id}'}"
                author_str = f"Tác giả: {story.author}" if (story and story.author) else "Tác giả: Khuyết danh"
                sub_info = f"{author_str} — Tỉ lệ: {aspect}"
                target_url = "/stories"
            elif j.job_type == "TestJob":
                display_name = "🧪 Kiểm Thử Hệ Thống (TestJob)"
        except Exception:
            pass

        enriched.append({
            "id": j.id,
            "job_type": j.job_type,
            "display_name": display_name,
            "sub_info": sub_info,
            "status": j.status,
            "progress": j.progress,
            "error_message": j.error_message,
            "result": j.result,
            "target_url": target_url,
            "created_at": j.created_at
        })
    return enriched

@router.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request, db: Session = Depends(get_db)):
    jobs = db.query(Job).order_by(Job.created_at.desc()).limit(50).all()
    enriched_jobs = enrich_job_info(jobs, db)
    return templates.TemplateResponse(
        request=request, 
        name="jobs.html",
        context={
            "jobs": enriched_jobs,
            "emergency_stopped": JobWorker._emergency_stop
        }
    )

@router.post("/api/v1/jobs/emergency-stop")
async def trigger_emergency_stop(db: Session = Depends(get_db)):
    JobWorker.set_emergency_stop(True)
    pending_jobs = db.query(Job).filter(Job.status.in_(["pending", "processing"])).all()
    for j in pending_jobs:
        j.status = "cancelled"
        j.error_message = "Cancelled by Emergency STOP ALL"
    db.commit()
    return JSONResponse({"status": "success", "message": "Đã kích hoạt ngắt khẩn cấp. Mọi tác vụ đã dừng lại."})

@router.post("/api/v1/jobs/resume")
async def trigger_resume(db: Session = Depends(get_db)):
    JobWorker.set_emergency_stop(False)
    return JSONResponse({"status": "success", "message": "Đã khôi phục hoạt động bình thường cho Worker."})

@router.post("/api/v1/jobs/{job_id}/cancel")
async def cancel_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ")
    
    job.status = "cancelled"
    job.error_message = "Đã hủy bởi người dùng"

    if job.job_type in ["StoryVideoRenderJob", "StoryAudioJob"]:
        try:
            payload_data = json.loads(job.payload) if job.payload else {}
            sid = payload_data.get("story_id")
            if sid:
                st = db.query(Story).filter(Story.id == sid).first()
                if st:
                    st.status = "failed"
                    st.error_message = "Đã hủy bởi người dùng"
        except Exception:
            pass

    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã hủy tác vụ #{job.id}!"})

@router.delete("/api/v1/jobs/{job_id}")
async def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ")
    
    db.delete(job)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã xóa tác vụ #{job_id} khỏi hệ thống!"})

from typing import List
from pydantic import BaseModel

class BulkDeleteJobRequest(BaseModel):
    ids: List[int]

@router.post("/api/v1/jobs/bulk-delete")
async def bulk_delete_jobs(req: BulkDeleteJobRequest, db: Session = Depends(get_db)):
    if not req.ids:
        raise HTTPException(status_code=400, detail="Danh sách ID rỗng")
    
    jobs = db.query(Job).filter(Job.id.in_(req.ids)).all()
    count = len(jobs)
    for j in jobs:
        db.delete(j)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã xóa thành công {count} tác vụ!"})

@router.post("/api/v1/jobs/clear-finished")
async def clear_finished_jobs(db: Session = Depends(get_db)):
    finished = db.query(Job).filter(Job.status.in_(["completed", "cancelled", "failed"])).all()
    count = len(finished)
    for j in finished:
        db.delete(j)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã dọn dẹp {count} tác vụ đã xong/hủy!"})

@router.post("/api/v1/jobs/{job_id}/retry")
async def retry_job(job_id: int, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy tác vụ")

    job.status = "pending"
    job.progress = 0
    job.error_message = None

    if job.job_type in ["StoryVideoRenderJob", "StoryAudioJob"]:
        try:
            payload_data = json.loads(job.payload) if job.payload else {}
            sid = payload_data.get("story_id")
            if sid:
                st = db.query(Story).filter(Story.id == sid).first()
                if st:
                    st.status = "rendering_video" if job.job_type == "StoryVideoRenderJob" else "processing_audio"
                    st.error_message = None
        except Exception:
            pass

    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã đưa tác vụ #{job.id} trở lại hàng đợi xử lý!"})

@router.get("/api/v1/jobs/worker-status")
async def get_worker_status(db: Session = Depends(get_db)):
    pending_count = db.query(Job).filter(Job.status == "pending").count()
    processing_count = db.query(Job).filter(Job.status == "processing").count()
    return JSONResponse({
        "is_running": JobWorker._is_running,
        "emergency_stop": JobWorker._emergency_stop,
        "pending_count": pending_count,
        "processing_count": processing_count
    })
