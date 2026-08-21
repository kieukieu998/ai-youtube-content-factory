from fastapi import APIRouter, Depends, Request
from starlette.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Movie, Script, Episode, Video, Job, Setting

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, db: Session = Depends(get_db)):
    movies_count = db.query(Movie).count()
    scripts_count = db.query(Script).count()
    episodes_count = db.query(Episode).count()
    videos_count = db.query(Video).count()
    pending_jobs_count = db.query(Job).filter(Job.status == "pending").count()
    
    recent_jobs = db.query(Job).order_by(Job.created_at.desc()).limit(5).all()
    from app.api.jobs_router import enrich_job_info
    enriched_recent_jobs = enrich_job_info(recent_jobs, db)
    recent_videos = db.query(Video).order_by(Video.created_at.desc()).limit(4).all()
    
    mode_setting = db.query(Setting).filter(Setting.key == "operation_mode").first()
    operation_mode = mode_setting.value if mode_setting else "semi_auto"
    
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "movies_count": movies_count,
            "scripts_count": scripts_count,
            "episodes_count": episodes_count,
            "videos_count": videos_count,
            "pending_jobs_count": pending_jobs_count,
            "recent_jobs": enriched_recent_jobs,
            "recent_videos": recent_videos,
            "operation_mode": operation_mode
        }
    )
