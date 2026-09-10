import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, Body
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from loguru import logger
from pydantic import BaseModel

from app.database.session import get_db, SessionLocal
from app.database.models import Story, Video, Publish, Job
from app.publishing.youtube_publisher import YouTubePublisher
from app.publishing.tiktok_publisher import TikTokPublisher
from app.publishing.seo_generator import SEOGenerator

router = APIRouter(prefix="/api/v1/publishing", tags=["publishing"])

class PublishYouTubeRequest(BaseModel):
    story_id: Optional[int] = None
    video_id: Optional[int] = None
    aspect_ratio: str = "9:16" # 9:16 (Shorts) or 16:9 (Standard)
    title: str
    description: str
    tags: Optional[List[str]] = None
    privacy_status: str = "public" # public, private, unlisted
    category_id: str = "24" # 24 = Entertainment

class PublishTikTokRequest(BaseModel):
    story_id: Optional[int] = None
    video_id: Optional[int] = None
    aspect_ratio: str = "9:16" # TikTok exclusively standard 9:16
    caption: str # Hook + summary + hashtags (under 2200 chars, ideal < 300)
    privacy_level: str = "PUBLIC_TO_EVERYONE" # PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, FOLLOWER_OF_CREATOR, SELF_ONLY
    disable_duet: bool = False
    disable_comment: bool = False
    disable_stitch: bool = False

class GenerateSEORequest(BaseModel):
    title: str
    content: str
    author: Optional[str] = "Khuyết danh"
    aspect_ratio: str = "9:16"

class GenerateTikTokSEORequest(BaseModel):
    title: str
    content: str
    author: Optional[str] = "Khuyết danh"

@router.get("/youtube/status")
async def get_youtube_status():
    """Get current YouTube channel connection state."""
    info = YouTubePublisher.get_channel_info()
    return {
        "status": "success",
        "data": info
    }

@router.post("/youtube/open-console")
async def open_google_cloud_console():
    """Launch user's default desktop browser directly to Google Cloud Credentials page."""
    import subprocess
    try:
        subprocess.Popen(["cmd", "/c", "start", "https://console.cloud.google.com/apis/credentials"], shell=True)
        return {"status": "success", "message": "Đã mở Google Cloud Console trên trình duyệt cá nhân của bạn."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@router.post("/youtube/toggle-demo")
async def toggle_youtube_demo(payload: Dict[str, Any] = Body(...)):
    """Toggle simulated demo mode for instant testing without Google Cloud setup."""
    enabled = payload.get("enabled", True)
    YouTubePublisher.set_demo_mode(enabled)
    info = YouTubePublisher.get_channel_info()
    return {
        "status": "success",
        "message": "Đã bật chế độ Kênh Thử Nghiệm (Demo Sandbox)!" if enabled else "Đã tắt chế độ Thử Nghiệm!",
        "data": info
    }

@router.post("/youtube/client-secret")
async def upload_client_secret(
    file: Optional[UploadFile] = File(None),
    json_text: Optional[str] = Form(None),
    client_id: Optional[str] = Form(None),
    client_secret: Optional[str] = Form(None)
):
    """Upload file, paste JSON content, or enter Client ID + Client Secret directly."""
    content_dict = None
    try:
        if file:
            raw_bytes = await file.read()
            content_dict = json.loads(raw_bytes.decode("utf-8"))
        elif json_text and json_text.strip():
            content_dict = json.loads(json_text.strip())
        elif client_id and client_secret and client_id.strip() and client_secret.strip():
            content_dict = {
                "web": {
                    "client_id": client_id.strip(),
                    "client_secret": client_secret.strip(),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "redirect_uris": [
                        "http://127.0.0.1:8000/api/v1/publishing/youtube/callback",
                        "http://localhost:8000/api/v1/publishing/youtube/callback"
                    ]
                }
            }
        else:
            raise HTTPException(status_code=400, detail="Vui lòng tải file JSON hoặc nhập Client ID & Client Secret.")
        
        if not ("web" in content_dict or "installed" in content_dict):
            raise HTTPException(
                status_code=400, 
                detail="Cấu hình không hợp lệ. Cần có khóa 'web' hoặc 'installed' từ Google Cloud Console."
            )

        # Ensure redirect_uris includes our callback
        target_key = "web" if "web" in content_dict else "installed"
        if "redirect_uris" in content_dict[target_key]:
            uris = content_dict[target_key]["redirect_uris"]
            cb_127 = "http://127.0.0.1:8000/api/v1/publishing/youtube/callback"
            cb_loc = "http://localhost:8000/api/v1/publishing/youtube/callback"
            if cb_127 not in uris:
                uris.append(cb_127)
            if cb_loc not in uris:
                uris.append(cb_loc)
        else:
            content_dict[target_key]["redirect_uris"] = [
                "http://127.0.0.1:8000/api/v1/publishing/youtube/callback",
                "http://localhost:8000/api/v1/publishing/youtube/callback"
            ]

        success = YouTubePublisher.save_client_secret(content_dict)
        if not success:
            raise HTTPException(status_code=500, detail="Không thể lưu file client_secrets.json")

        return {
            "status": "success",
            "message": "Đã lưu cấu hình Google OAuth thành công! Giờ bạn có thể bấm Kết Nối Kênh YouTube."
        }
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Nội dung tải lên không phải là JSON hợp lệ.")
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/youtube/auth-url")
async def get_youtube_auth_url(request: Request):
    """Generate OAuth authorization URL for connecting Google account."""
    try:
        # Build redirect uri based on request host
        host = request.headers.get("host", "127.0.0.1:8000")
        proto = "https" if request.url.scheme == "https" else "http"
        redirect_uri = f"{proto}://{host}/api/v1/publishing/youtube/callback"
        
        url = YouTubePublisher.get_auth_url(redirect_uri=redirect_uri)
        return {"status": "success", "auth_url": url}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi tạo link xác thực: {e}")

@router.get("/youtube/callback", response_class=HTMLResponse)
async def youtube_oauth_callback(request: Request, code: Optional[str] = None, error: Optional[str] = None):
    """Handle Google OAuth redirect callback."""
    if error:
        return HTMLResponse(f"""
            <html><body style="font-family:sans-serif; background:#0f172a; color:#f8fafc; text-align:center; padding:50px;">
                <h2 style="color:#ef4444;">Xác thực thất bại</h2>
                <p>Google báo lỗi: {error}</p>
                <button onclick="window.close()" style="padding:10px 20px; background:#475569; color:white; border:none; border-radius:8px; cursor:pointer;">Đóng Cửa Sổ</button>
            </body></html>
        """, status_code=400)

    if not code:
        return HTMLResponse("""
            <html><body style="font-family:sans-serif; background:#0f172a; color:#f8fafc; text-align:center; padding:50px;">
                <h2 style="color:#ef4444;">Lỗi: Thiếu mã xác thực (code)</h2>
                <button onclick="window.close()" style="padding:10px 20px; background:#475569; color:white; border:none; border-radius:8px; cursor:pointer;">Đóng Cửa Sổ</button>
            </body></html>
        """, status_code=400)

    try:
        host = request.headers.get("host", "127.0.0.1:8000")
        proto = "https" if request.url.scheme == "https" else "http"
        redirect_uri = f"{proto}://{host}/api/v1/publishing/youtube/callback"

        YouTubePublisher.exchange_code(code=code, redirect_uri=redirect_uri)
        ch_info = YouTubePublisher.get_channel_info()
        ch_title = ch_info.get("title", "Kênh YouTube")

        return HTMLResponse(f"""
            <html><body style="font-family:sans-serif; background:#0f172a; color:#f8fafc; text-align:center; padding:50px;">
                <div style="max-width:450px; margin:0 auto; background:#1e293b; padding:30px; border-radius:16px; border:1px solid #334155; box-shadow:0 10px 30px rgba(0,0,0,0.5);">
                    <h2 style="color:#10b981; margin-top:0;">🎉 Kết Nối Kênh Thành Công!</h2>
                    <p style="color:#94a3b8; font-size:14px;">Đã kết nối với kênh <strong>{ch_title}</strong></p>
                    <p style="color:#64748b; font-size:12px;">Cửa sổ này sẽ tự động đóng sau vài giây...</p>
                    <button onclick="handleDone()" style="margin-top:15px; padding:10px 24px; background:#6366f1; color:white; font-weight:bold; border:none; border-radius:10px; cursor:pointer;">Xong & Quay Lại</button>
                </div>
                <script>
                    function handleDone() {{
                        if (window.opener) {{
                            window.opener.postMessage({{ type: 'YOUTUBE_CONNECTED', channel: '{ch_title}' }}, '*');
                            window.close();
                        }} else {{
                            window.location.href = '/stories';
                        }}
                    }}
                    setTimeout(handleDone, 2500);
                </script>
            </body></html>
        """)
    except Exception as e:
        logger.error(f"OAuth exchange error: {e}")
        return HTMLResponse(f"""
            <html><body style="font-family:sans-serif; background:#0f172a; color:#f8fafc; text-align:center; padding:50px;">
                <h2 style="color:#ef4444;">Không thể lưu token xác thực</h2>
                <p style="color:#cbd5e1;">Chi tiết lỗi: {e}</p>
                <button onclick="window.close()" style="padding:10px 20px; background:#475569; color:white; border:none; border-radius:8px; cursor:pointer;">Đóng</button>
            </body></html>
        """, status_code=500)

@router.post("/youtube/disconnect")
async def disconnect_youtube():
    """Disconnect active YouTube account."""
    success = YouTubePublisher.disconnect()
    if success:
        return {"status": "success", "message": "Đã ngắt kết nối tài khoản YouTube thành công."}
    raise HTTPException(status_code=500, detail="Không thể ngắt kết nối tài khoản.")

@router.post("/seo/generate")
async def generate_seo_metadata(req: GenerateSEORequest):
    """Generate AI Title, Description, and Tags optimized for YouTube."""
    meta = await SEOGenerator.generate_youtube_seo(
        title=req.title,
        content=req.content,
        author=req.author,
        aspect_ratio=req.aspect_ratio
    )
    return meta

@router.post("/youtube/publish")
async def publish_video_to_youtube(req: PublishYouTubeRequest, db: Session = Depends(get_db)):
    """
    Submit a YouTube video publish request.
    Enqueues a YouTubePublishJob in the background queue.
    """
    if not YouTubePublisher.is_authenticated():
        raise HTTPException(
            status_code=400,
            detail="Chưa kết nối tài khoản YouTube. Vui lòng bấm 'Kết Nối Kênh' trước khi đăng video."
        )

    # 1. Determine video file path
    target_video_path = None
    story = None
    video_rec = None

    if req.story_id:
        story = db.query(Story).filter(Story.id == req.story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Không tìm thấy truyện tương ứng.")

        # Check requested format path
        if req.aspect_ratio == "9:16":
            p9 = Path(f"media/output/stories/story_{story.id}_9x16.mp4")
            if p9.exists():
                target_video_path = str(p9)
            elif story.video_path and "9x16" in story.video_path:
                target_video_path = story.video_path
        else: # 16:9
            p16 = Path(f"media/output/stories/story_{story.id}_16x9.mp4")
            if p16.exists():
                target_video_path = str(p16)
            elif story.video_path and "16x9" in story.video_path:
                target_video_path = story.video_path

        if not target_video_path or not os.path.exists(target_video_path):
            if story.video_path and os.path.exists(story.video_path):
                target_video_path = story.video_path
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Chưa có file video hoàn chỉnh cho định dạng {req.aspect_ratio}. Vui lòng bấm render video trước!"
                )

    elif req.video_id:
        video_rec = db.query(Video).filter(Video.id == req.video_id).first()
        if not video_rec or not os.path.exists(video_rec.file_path):
            raise HTTPException(status_code=404, detail="Không tìm thấy video cần đăng.")
        target_video_path = video_rec.file_path

    else:
        raise HTTPException(status_code=400, detail="Thiếu story_id hoặc video_id.")

    # 2. Create Publish Record in Database
    platform_name = "youtube_shorts" if req.aspect_ratio == "9:16" else "youtube"
    tags_str = ", ".join(req.tags) if req.tags else ""
    
    publish_rec = Publish(
        story_id=story.id if story else None,
        video_id=video_rec.id if video_rec else None,
        platform=platform_name,
        title=req.title.strip(),
        description=req.description.strip(),
        hashtags=tags_str,
        video_aspect=req.aspect_ratio,
        privacy_status=req.privacy_status,
        status="scheduled"
    )
    db.add(publish_rec)
    db.commit()
    db.refresh(publish_rec)

    # 3. Enqueue YouTubePublishJob in SQLite Queue
    job_payload = {
        "publish_id": publish_rec.id,
        "story_id": story.id if story else None,
        "video_id": video_rec.id if video_rec else None,
        "file_path": target_video_path,
        "title": req.title.strip(),
        "description": req.description.strip(),
        "tags": req.tags or [],
        "privacy_status": req.privacy_status,
        "category_id": req.category_id,
        "aspect_ratio": req.aspect_ratio,
        "is_shorts": (req.aspect_ratio == "9:16")
    }

    job = Job(
        job_type="YouTubePublishJob",
        status="pending",
        progress=0,
        payload=json.dumps(job_payload, ensure_ascii=False)
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Enqueued YouTubePublishJob #{job.id} for Publish #{publish_rec.id} ({req.title})")

    return {
        "status": "success",
        "publish_id": publish_rec.id,
        "job_id": job.id,
        "message": "Đã thêm tác vụ đăng video lên YouTube vào hàng đợi xử lý ngầm!",
        "video_format": "YouTube Shorts (9:16)" if req.aspect_ratio == "9:16" else "YouTube Video (16:9)"
    }

# =========================================================================
# TIKTOK PUBLISHING ENDPOINTS
# =========================================================================

@router.get("/tiktok/status")
async def get_tiktok_status():
    """Get current TikTok creator account connection state and stats."""
    info = TikTokPublisher.get_account_info()
    return {
        "status": "success",
        "data": info
    }

@router.post("/tiktok/toggle-demo")
async def toggle_tiktok_demo(payload: Dict[str, Any] = Body(...)):
    """Toggle simulated demo sandbox for instant TikTok testing without API approval."""
    enabled = payload.get("enabled", True)
    TikTokPublisher.set_demo_mode(enabled)
    info = TikTokPublisher.get_account_info()
    return {
        "status": "success",
        "message": "Đã bật chế độ TikTok Thử Nghiệm (Demo Sandbox)!" if enabled else "Đã tắt chế độ Thử Nghiệm!",
        "data": info
    }

@router.post("/tiktok/client-key")
async def save_tiktok_client_key(payload: Dict[str, Any] = Body(...)):
    """Save TikTok Developer App Client Key & Client Secret."""
    client_key = payload.get("client_key", "").strip()
    client_secret = payload.get("client_secret", "").strip()

    if not client_key or not client_secret:
        raise HTTPException(status_code=400, detail="Vui lòng nhập đầy đủ Client Key và Client Secret từ TikTok Developer Portal.")

    success = TikTokPublisher.save_client_key(client_key, client_secret)
    if not success:
        raise HTTPException(status_code=500, detail="Lỗi khi lưu cấu hình Client Key.")

    return {
        "status": "success",
        "message": "Đã lưu thông tin TikTok Client Key thành công! Giờ bạn có thể bấm Kết Nối Kênh."
    }

@router.get("/tiktok/auth-url")
async def get_tiktok_auth_url(request: Request):
    """Generate TikTok OAuth authorization URL."""
    try:
        host = request.headers.get("host", "127.0.0.1:8000")
        proto = "https" if (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https") else "http"
        redirect_uri = f"{proto}://{host}/api/v1/publishing/tiktok/callback"

        url = TikTokPublisher.get_auth_url(redirect_uri=redirect_uri)
        return {
            "status": "success",
            "auth_url": url,
            "redirect_uri": redirect_uri
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi tạo liên kết xác thực TikTok: {e}")

@router.get("/tiktok/callback", response_class=HTMLResponse)
async def tiktok_oauth_callback(
    request: Request,
    code: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None
):
    """Handle TikTok OAuth redirect callback."""
    if error:
        return HTMLResponse(f"""
            <html><body style="font-family:sans-serif; background:#010101; color:#f8fafc; text-align:center; padding:50px;">
                <h2 style="color:#ef4444;">Xác thực TikTok thất bại</h2>
                <p>TikTok báo lỗi: {error} - {error_description or ''}</p>
                <button onclick="window.close()" style="padding:10px 20px; background:#475569; color:white; border:none; border-radius:8px; cursor:pointer;">Đóng Cửa Sổ</button>
            </body></html>
        """, status_code=400)

    if not code:
        return HTMLResponse("""
            <html><body style="font-family:sans-serif; background:#010101; color:#f8fafc; text-align:center; padding:50px;">
                <h2 style="color:#ef4444;">Lỗi: Thiếu mã xác thực (code)</h2>
                <button onclick="window.close()" style="padding:10px 20px; background:#475569; color:white; border:none; border-radius:8px; cursor:pointer;">Đóng Cửa Sổ</button>
            </body></html>
        """, status_code=400)

    try:
        host = request.headers.get("host", "127.0.0.1:8000")
        proto = "https" if (request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https") else "http"
        redirect_uri = f"{proto}://{host}/api/v1/publishing/tiktok/callback"

        TikTokPublisher.exchange_code(code=code, redirect_uri=redirect_uri)
        acc_info = TikTokPublisher.get_account_info()
        acc_name = acc_info.get("display_name") or acc_info.get("username", "Tài khoản TikTok")

        return HTMLResponse(f"""
            <html><body style="font-family:sans-serif; background:#010101; color:#f8fafc; text-align:center; padding:50px;">
                <div style="max-width:450px; margin:0 auto; background:#121212; padding:30px; border-radius:16px; border:1px solid #27272a; box-shadow:0 10px 30px rgba(0,0,0,0.8);">
                    <h2 style="color:#25F4EE; margin-top:0;">🎵 Kết Nối TikTok Thành Công!</h2>
                    <p style="color:#94a3b8; font-size:14px;">Đã liên kết tài khoản: <strong>{acc_name}</strong></p>
                    <p style="color:#64748b; font-size:12px;">Cửa sổ này sẽ tự động đóng sau vài giây...</p>
                    <button onclick="handleDone()" style="margin-top:15px; padding:10px 24px; background:#FE2C55; color:white; font-weight:bold; border:none; border-radius:10px; cursor:pointer;">Xong & Quay Lại</button>
                </div>
                <script>
                    function handleDone() {{
                        if (window.opener) {{
                            window.opener.postMessage({{ type: 'TIKTOK_CONNECTED', account: '{acc_name}' }}, '*');
                            window.close();
                        }} else {{
                            window.location.href = '/stories';
                        }}
                    }}
                    setTimeout(handleDone, 2500);
                </script>
            </body></html>
        """)
    except Exception as e:
        logger.error(f"TikTok OAuth callback exchange error: {e}")
        return HTMLResponse(f"""
            <html><body style="font-family:sans-serif; background:#010101; color:#f8fafc; text-align:center; padding:50px;">
                <h2 style="color:#ef4444;">Lỗi lưu phiên TikTok</h2>
                <p>{e}</p>
                <button onclick="window.close()" style="padding:10px 20px; background:#475569; color:white; border:none; border-radius:8px; cursor:pointer;">Đóng Cửa Sổ</button>
            </body></html>
        """, status_code=500)

@router.post("/tiktok/disconnect")
async def disconnect_tiktok():
    """Disconnect current TikTok account."""
    success = TikTokPublisher.disconnect()
    return {
        "status": "success" if success else "error",
        "message": "Đã ngắt kết nối tài khoản TikTok thành công." if success else "Lỗi khi ngắt kết nối TikTok."
    }

@router.post("/tiktok/seo")
async def generate_tiktok_seo_metadata(req: GenerateTikTokSEORequest):
    """Generate TikTok SEO caption, viral hooks, and trending hashtags using AI."""
    seo_data = await SEOGenerator.generate_tiktok_seo(
        title=req.title,
        content=req.content,
        author=req.author
    )
    return {
        "status": "success",
        "data": seo_data
    }

@router.post("/tiktok/publish")
async def publish_video_to_tiktok(
    req: PublishTikTokRequest,
    db: Session = Depends(get_db)
):
    """
    Submit a TikTok video publish request.
    TikTok requires vertical 9:16 format (1080x1920).
    Enqueues a TikTokPublishJob in the background queue.
    """
    if not TikTokPublisher.is_authenticated():
        raise HTTPException(
            status_code=400,
            detail="Chưa kết nối tài khoản TikTok. Vui lòng bấm 'Kết Nối Kênh' trước khi đăng video."
        )

    # 1. Determine vertical video file path (9:16)
    target_video_path = None
    story = None
    video_rec = None

    if req.story_id:
        story = db.query(Story).filter(Story.id == req.story_id).first()
        if not story:
            raise HTTPException(status_code=404, detail="Không tìm thấy truyện tương ứng.")

        # Check 9:16 vertical video path first
        p9 = Path(f"media/output/stories/story_{story.id}_9x16.mp4")
        if p9.exists():
            target_video_path = str(p9)
        elif story.video_path and "9x16" in story.video_path and os.path.exists(story.video_path):
            target_video_path = story.video_path
        elif story.video_path and os.path.exists(story.video_path):
            # Fallback if only 1 video exists
            target_video_path = story.video_path

        if not target_video_path or not os.path.exists(target_video_path):
            raise HTTPException(
                status_code=400,
                detail="Chưa có file video dọc 9:16 cho câu chuyện này. TikTok yêu cầu định dạng video 9:16, vui lòng bấm render video 9:16 trước!"
            )

    elif req.video_id:
        video_rec = db.query(Video).filter(Video.id == req.video_id).first()
        if not video_rec or not os.path.exists(video_rec.file_path):
            raise HTTPException(status_code=404, detail="Không tìm thấy video cần đăng.")
        target_video_path = video_rec.file_path

    else:
        raise HTTPException(status_code=400, detail="Thiếu story_id hoặc video_id.")

    # 2. Create Publish Record in Database
    caption_text = req.caption.strip()
    title_snippet = caption_text[:80] + ("..." if len(caption_text) > 80 else "")

    publish_rec = Publish(
        story_id=story.id if story else None,
        video_id=video_rec.id if video_rec else None,
        platform="tiktok",
        title=title_snippet,
        description=caption_text,
        hashtags="",
        video_aspect="9:16",
        privacy_status=req.privacy_level,
        status="scheduled"
    )
    db.add(publish_rec)
    db.commit()
    db.refresh(publish_rec)

    # 3. Enqueue TikTokPublishJob in SQLite Queue
    job_payload = {
        "publish_id": publish_rec.id,
        "story_id": story.id if story else None,
        "video_id": video_rec.id if video_rec else None,
        "file_path": target_video_path,
        "caption": caption_text,
        "privacy_level": req.privacy_level,
        "disable_duet": req.disable_duet,
        "disable_comment": req.disable_comment,
        "disable_stitch": req.disable_stitch,
        "aspect_ratio": "9:16"
    }

    job = Job(
        job_type="TikTokPublishJob",
        status="pending",
        progress=0,
        payload=json.dumps(job_payload, ensure_ascii=False)
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(f"Enqueued TikTokPublishJob #{job.id} for Publish #{publish_rec.id} ({title_snippet})")

    return {
        "status": "success",
        "publish_id": publish_rec.id,
        "job_id": job.id,
        "message": "Đã thêm tác vụ đăng video lên TikTok vào hàng đợi xử lý ngầm!",
        "video_format": "TikTok Video (9:16 Dọc)"
    }

@router.get("/history")
async def get_publish_history(db: Session = Depends(get_db)):
    """Retrieve history of all published videos across platforms."""
    publishes = db.query(Publish).order_by(Publish.created_at.desc()).limit(50).all()
    results = []
    for p in publishes:
        story_title = p.story.title if p.story else (p.video.title if p.video else "Video")
        results.append({
            "id": p.id,
            "title": p.title or story_title,
            "platform": p.platform,
            "video_aspect": p.video_aspect,
            "privacy_status": p.privacy_status,
            "video_url": p.video_url,
            "platform_video_id": p.platform_video_id,
            "status": p.status,
            "error_message": p.error_message,
            "published_at": p.published_at.strftime("%d/%m/%Y %H:%M") if p.published_at else None,
            "created_at": p.created_at.strftime("%d/%m/%Y %H:%M") if p.created_at else None
        })
    return results
