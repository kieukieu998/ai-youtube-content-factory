import json
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from starlette.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Script, Episode, Movie, Job

router = APIRouter()

@router.get("/scripts", response_class=HTMLResponse)
async def scripts_page(request: Request, db: Session = Depends(get_db)):
    movies = db.query(Movie).order_by(Movie.created_at.desc()).all()
    scripts = db.query(Script).order_by(Script.created_at.desc()).all()
    episodes_pending = db.query(Episode).filter(Episode.status == "approval_pending").all()
    
    return templates.TemplateResponse(
        request=request, 
        name="scripts.html",
        context={
            "movies": movies,
            "scripts": scripts,
            "episodes_pending": episodes_pending
        }
    )

@router.post("/api/v1/scripts/generate")
async def trigger_script_generation(
    movie_id: int = Form(...),
    target_episodes: int = Form(3),
    style: str = Form("dramatic"),
    ai_provider: str = Form(None),
    db: Session = Depends(get_db)
):
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")

    job = Job(
        job_type="ScriptGenerationJob",
        status="pending",
        payload=json.dumps({
            "movie_id": movie_id,
            "target_episodes": target_episodes,
            "style": style,
            "ai_provider": ai_provider
        })
    )
    db.add(job)
    db.commit()
    return JSONResponse({
        "status": "success", 
        "message": f"Đã thêm tác vụ viết {target_episodes} tập kịch bản cho phim '{movie.title}' vào hàng đợi", 
        "job_id": job.id
    })

@router.post("/api/v1/episodes/{episode_id}/update")
async def update_episode(
    episode_id: int,
    hook_text: str = Form(None),
    content_text: str = Form(None),
    call_to_action: str = Form(None),
    db: Session = Depends(get_db)
):
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Không tìm thấy tập phim")

    if hook_text is not None:
        episode.hook_text = hook_text.strip()
    if content_text is not None:
        episode.content_text = content_text.strip()
    if call_to_action is not None:
        episode.call_to_action = call_to_action.strip()

    db.commit()
    return JSONResponse({
        "status": "success", 
        "message": f"Đã cập nhật kịch bản Tập {episode.episode_number} thành công!",
        "episode": {
            "id": episode.id,
            "hook_text": episode.hook_text,
            "content_text": episode.content_text,
            "call_to_action": episode.call_to_action
        }
    })

@router.post("/api/v1/scripts/{script_id}/update")
async def update_script(
    script_id: int,
    title: str = Form(...),
    style: str = Form(None),
    db: Session = Depends(get_db)
):
    script = db.query(Script).filter(Script.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")

    script.title = title.strip()
    if style:
        script.style = style.strip()

    db.commit()
    return JSONResponse({"status": "success", "message": "Đã cập nhật tiêu đề kịch bản thành công!"})

@router.post("/api/v1/episodes/{episode_id}/approve")
async def approve_episode(
    episode_id: int,
    hook_text: str = Form(None),
    content_text: str = Form(None),
    call_to_action: str = Form(None),
    db: Session = Depends(get_db)
):
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Không tìm thấy tập phim")

    if hook_text is not None:
        episode.hook_text = hook_text.strip()
    if content_text is not None:
        episode.content_text = content_text.strip()
    if call_to_action is not None:
        episode.call_to_action = call_to_action.strip()

    episode.status = "approved"
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã duyệt tập {episode.episode_number} thành công!"})

from typing import List
from pydantic import BaseModel

class BulkDeleteScriptRequest(BaseModel):
    ids: List[int]

@router.delete("/api/v1/scripts/{script_id}")
async def delete_script(script_id: int, db: Session = Depends(get_db)):
    script = db.query(Script).filter(Script.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
    
    # Delete episodes associated with script
    episodes = db.query(Episode).filter(Episode.script_id == script_id).all()
    for ep in episodes:
        db.delete(ep)
        
    db.delete(script)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã xóa kịch bản #{script_id} thành công!"})

@router.post("/api/v1/scripts/bulk-delete")
async def bulk_delete_scripts(req: BulkDeleteScriptRequest, db: Session = Depends(get_db)):
    if not req.ids:
        raise HTTPException(status_code=400, detail="Danh sách ID rỗng")
    
    scripts = db.query(Script).filter(Script.id.in_(req.ids)).all()
    count = len(scripts)
    for s in scripts:
        episodes = db.query(Episode).filter(Episode.script_id == s.id).all()
        for ep in episodes:
            db.delete(ep)
        db.delete(s)
        
@router.post("/api/v1/scripts/{script_id}/render-all")
async def render_all_script_episodes(script_id: int, db: Session = Depends(get_db)):
    import json
    script = db.query(Script).filter(Script.id == script_id).first()
    if not script:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản")
        
    episodes = db.query(Episode).filter(Episode.script_id == script_id).all()
    if not episodes:
        raise HTTPException(status_code=400, detail="Kịch bản không có tập nào")
        
    queued_count = 0
    for ep in episodes:
        job = Job(
            job_type="RenderEpisodeJob",
            status="pending",
            payload=json.dumps({"episode_id": ep.id})
        )
        db.add(job)
        queued_count += 1
        
    db.commit()
    return JSONResponse({
        "status": "success", 
        "message": f"Đã thêm thành công trọn bộ {queued_count} tập vào hàng đợi render video 9:16!"
    })
