from fastapi import APIRouter, Depends, Request, Form
from starlette.responses import HTMLResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Setting
from app.core.config import settings

router = APIRouter()

@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    db_settings = {s.key: s.value for s in db.query(Setting).all()}
    gemini_key = db_settings.get("gemini_api_key") or settings.GEMINI_API_KEY or ""
    return templates.TemplateResponse(
        request=request, 
        name="settings.html",
        context={
            "settings": db_settings,
            "gemini_api_key": gemini_key
        }
    )

@router.post("/api/v1/settings/save")
async def save_settings(
    default_ai_provider: str = Form("gemini_free"),
    gemini_api_key: str = Form(None),
    operation_mode: str = Form("semi_auto"),
    default_tts_voice: str = Form("vi-VN-HoaiMyNeural"),
    daily_budget_limit_usd: str = Form("0.0"),
    db: Session = Depends(get_db)
):
    updates = {
        "default_ai_provider": default_ai_provider,
        "operation_mode": operation_mode,
        "default_tts_voice": default_tts_voice,
        "daily_budget_limit_usd": daily_budget_limit_usd,
    }
    
    if gemini_api_key and gemini_api_key.strip():
        updates["gemini_api_key"] = gemini_api_key.strip()
        settings.GEMINI_API_KEY = gemini_api_key.strip()

    for k, v in updates.items():
        item = db.query(Setting).filter(Setting.key == k).first()
        if item:
            item.value = v
        else:
            db.add(Setting(key=k, value=v))
            
    db.commit()
    return JSONResponse({"status": "success", "message": "Đã lưu cấu hình thành công!"})
