import os
import json
import shutil
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Request, Form, UploadFile, File, HTTPException
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.templates import templates
from app.database.session import get_db
from app.database.models import Movie, MovieSource, Job
from app.core.config import settings

router = APIRouter()

def extract_youtube_url(movie: Movie) -> str:
    """Extract full YouTube link from license_info or filename."""
    if not movie.sources:
        return ""
    for s in movie.sources:
        if s.license_info and ("youtube.com" in s.license_info or "youtu.be" in s.license_info):
            return s.license_info
        if s.file_path:
            p = Path(s.file_path)
            parts = p.stem.split("_")
            if len(parts) >= 3 and len(parts[-1]) == 11:
                return f"https://www.youtube.com/watch?v={parts[-1]}"
    return ""

@router.get("/movies", response_class=HTMLResponse)
async def movies_list_page(request: Request, db: Session = Depends(get_db)):
    movies = db.query(Movie).order_by(Movie.created_at.desc()).all()
    for m in movies:
        m.youtube_url = extract_youtube_url(m)
    return templates.TemplateResponse(
        request=request,
        name="movies.html",
        context={"movies": movies}
    )

@router.post("/api/v1/movies/discover")
async def trigger_movie_discovery(
    genre: str = Form("Hành Động, Kinh Dị"),
    limit: int = Form(3),
    db: Session = Depends(get_db)
):
    job = Job(
        job_type="MovieDiscoveryJob",
        status="pending",
        payload=json.dumps({"genre": genre, "limit": limit})
    )
    db.add(job)
    db.commit()
    return JSONResponse({"status": "success", "message": "Đã thêm tác vụ tìm kiếm phim vào hàng đợi", "job_id": job.id})

@router.post("/api/v1/movies/{movie_id}/update")
async def update_movie(
    movie_id: int,
    title: str = Form(...),
    original_title: str = Form(None),
    genre: str = Form(None),
    release_year: int = Form(None),
    synopsis: str = Form(None),
    youtube_url: str = Form(None),
    db: Session = Depends(get_db)
):
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")

    movie.title = title.strip()
    if original_title is not None:
        movie.original_title = original_title.strip()
    if genre is not None:
        movie.genre = genre.strip()
    if release_year is not None:
        movie.release_year = release_year
    if synopsis is not None:
        movie.synopsis = synopsis.strip()

    # Update or attach YouTube URL to source
    if youtube_url and youtube_url.strip():
        clean_yt = youtube_url.strip()
        if movie.sources:
            movie.sources[0].license_info = clean_yt
        else:
            source = MovieSource(
                movie_id=movie.id,
                source_type="youtube_link",
                file_path=clean_yt,
                license_info=clean_yt,
                is_verified=False
            )
            db.add(source)

    db.commit()
    return JSONResponse({
        "status": "success",
        "message": f"Đã cập nhật thông tin phim '{movie.title}' thành công!",
        "movie": {
            "id": movie.id,
            "title": movie.title,
            "original_title": movie.original_title,
            "genre": movie.genre,
            "release_year": movie.release_year,
            "synopsis": movie.synopsis,
            "youtube_url": youtube_url.strip() if youtube_url else ""
        }
    })

async def _background_download_youtube_source(movie_id: int, url: str):
    """Background helper to download full YouTube video without blocking UI."""
    from app.database.session import SessionLocal
    from app.video.youtube_downloader import YouTubeTrailerDownloader, slugify_filename
    import asyncio
    from loguru import logger
    
    db = SessionLocal()
    try:
        movie = db.query(Movie).filter(Movie.id == movie_id).first()
        if not movie:
            return
            
        clean_prefix = slugify_filename(movie.title, movie.release_year, fallback_title=movie.original_title)
        info = await asyncio.to_thread(
            YouTubeTrailerDownloader.get_video_info_and_download,
            query_or_url=url,
            output_dir=str(settings.SOURCE_MEDIA_DIR),
            filename_prefix=f"{clean_prefix}"
        )
        
        if info.get("file_path") and os.path.exists(info["file_path"]):
            final_file_path = info["file_path"]
            source = db.query(MovieSource).filter(MovieSource.movie_id == movie_id, MovieSource.license_info == url).first()
            if source:
                source.file_path = final_file_path
                source.is_verified = True
            else:
                source = MovieSource(
                    movie_id=movie.id,
                    source_type="youtube_link",
                    file_path=final_file_path,
                    license_info=url,
                    is_verified=True
                )
                db.add(source)
            db.commit()
            logger.info(f"Background YouTube download completed for movie #{movie_id} -> {final_file_path}")
    except Exception as e:
        logger.error(f"Error in background youtube download for movie #{movie_id}: {e}")
    finally:
        db.close()

@router.post("/api/v1/movies/create-from-youtube")
async def create_movie_from_youtube(
    youtube_url: str = Form(...),
    title: str = Form(None),
    original_title: str = Form(None),
    genre: str = Form("Hành Động, Điện Ảnh"),
    release_year: int = Form(None),
    synopsis: str = Form(None),
    db: Session = Depends(get_db)
):
    url = youtube_url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="Vui lòng nhập đường link YouTube hợp lệ")

    from app.video.youtube_downloader import YouTubeTrailerDownloader
    import asyncio

    # Fast extraction (takes ~1-2 seconds) for immediate responsive UI
    fast_info = await asyncio.to_thread(YouTubeTrailerDownloader.extract_metadata_fast, url)

    movie_title = (
        (title.strip() if title and title.strip() else None)
        or fast_info.get("title")
        or "Phim Chưa Đặt Tên"
    )
    movie_orig = (
        (original_title.strip() if original_title and original_title.strip() else None)
        or movie_title
    )
    raw_desc = fast_info.get("description") or ""
    movie_synopsis = (
        (synopsis.strip() if synopsis and synopsis.strip() else None)
        or (raw_desc[:400] if raw_desc else f"Phim nhập từ YouTube: {movie_title}")
    )
    duration_val = fast_info.get("duration") or 0

    movie = Movie(
        title=movie_title,
        original_title=movie_orig,
        release_year=release_year,
        genre=genre,
        duration_minutes=duration_val,
        synopsis=movie_synopsis,
        potential_score=90.0,
        status="discovered",
        created_by="user"
    )
    db.add(movie)
    db.flush()

    source = MovieSource(
        movie_id=movie.id,
        source_type="youtube_link",
        file_path=url, # Initially points to URL until background download finishes
        license_info=url,
        is_verified=False
    )
    db.add(source)
    db.commit()

    # Launch non-blocking background download task
    asyncio.create_task(_background_download_youtube_source(movie.id, url))

    return JSONResponse({
        "status": "success",
        "message": f"Đã thêm thành công phim '{movie.title}' vào Kho Phim! Video đang được tải ngầm.",
        "movie_id": movie.id
    })

@router.post("/api/v1/movies/{movie_id}/upload-source")
async def upload_movie_source(
    movie_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")

    from app.video.youtube_downloader import slugify_filename
    clean_name = slugify_filename(movie.title, movie.release_year, fallback_title=movie.original_title)

    # Clean up old source records and files
    for old_s in movie.sources:
        if old_s.file_path and Path(old_s.file_path).exists() and "source" in old_s.file_path:
            try:
                Path(old_s.file_path).unlink()
            except Exception:
                pass
        db.delete(old_s)

    dest_file = settings.SOURCE_MEDIA_DIR / f"{clean_name}_{file.filename}"
    with open(dest_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    source = MovieSource(
        movie_id=movie.id,
        source_type="user_upload",
        file_path=str(dest_file),
        license_info=file.filename,
        is_verified=True
    )
    db.add(source)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã tải lên và thay thế video nguồn '{file.filename}' thành công!"})

@router.post("/api/v1/movies/{movie_id}/fetch-trailer")
async def fetch_trailer_youtube(
    movie_id: int,
    youtube_url: str = Form(None),
    db: Session = Depends(get_db)
):
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")

    from app.video.youtube_downloader import YouTubeTrailerDownloader, slugify_filename
    import asyncio
    search_query = youtube_url.strip() if youtube_url and youtube_url.strip() else f"{movie.original_title or movie.title} {movie.release_year or ''}"
    clean_prefix = slugify_filename(movie.title, movie.release_year, fallback_title=movie.original_title)

    file_path = await asyncio.to_thread(
        YouTubeTrailerDownloader.download_trailer,
        query_or_url=search_query,
        output_dir=str(settings.SOURCE_MEDIA_DIR),
        filename_prefix=clean_prefix
    )
    
    if not file_path:
        raise HTTPException(status_code=500, detail="Không thể tải trailer từ YouTube. Vui lòng kiểm tra lại đường truyền hoặc link.")

    # Clean up old source records and files
    for old_s in movie.sources:
        if old_s.file_path and old_s.file_path != file_path and Path(old_s.file_path).exists() and "source" in old_s.file_path:
            try:
                Path(old_s.file_path).unlink()
            except Exception:
                pass
        db.delete(old_s)

    # Save new movie source
    source = MovieSource(
        movie_id=movie.id,
        source_type="youtube_trailer",
        file_path=file_path,
        license_info=search_query if ("youtube.com" in search_query or "youtu.be" in search_query) else None,
        is_verified=True
    )
    db.add(source)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã tự động tải thành công trailer cho phim '{movie.title}'!"})

@router.get("/api/v1/movies/{movie_id}/sources")
async def get_movie_sources(movie_id: int, db: Session = Depends(get_db)):
    """Retrieve all media sources (trailers, clips, full videos) attached to a movie."""
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")

    sources = db.query(MovieSource).filter(
        MovieSource.movie_id == movie_id
    ).order_by(MovieSource.order_index.asc(), MovieSource.id.asc()).all()

    sources_data = []
    for s in sources:
        stream_url = ""
        filename = ""
        if s.file_path:
            norm = s.file_path.replace("\\", "/")
            if norm.startswith("http://") or norm.startswith("https://"):
                stream_url = norm
                filename = norm
            else:
                p = Path(s.file_path)
                filename = p.name
                if "media" in norm:
                    idx = norm.find("/media/")
                    stream_url = norm[idx:] if idx != -1 else f"/media/source/{p.name}"
                else:
                    stream_url = f"/media/source/{p.name}"
        
        sources_data.append({
            "id": s.id,
            "source_type": s.source_type,
            "file_path": s.file_path,
            "filename": filename or f"Nguồn #{s.id}",
            "stream_url": stream_url or f"/api/v1/movies/{movie_id}/source-stream",
            "license_info": s.license_info,
            "order_index": s.order_index or 1,
            "is_verified": s.is_verified,
            "created_at": s.created_at.strftime("%H:%M %d/%m/%Y") if s.created_at else ""
        })

    return JSONResponse({
        "status": "success",
        "movie_id": movie.id,
        "movie_title": movie.title,
        "sources": sources_data
    })

class ReorderSourcesRequest(BaseModel):
    source_ids: List[int]

@router.post("/api/v1/movies/{movie_id}/sources/reorder")
async def reorder_movie_sources(
    movie_id: int,
    req: ReorderSourcesRequest,
    db: Session = Depends(get_db)
):
    """Update sequence order (Tập 1, Tập 2, Tập 3) of sources."""
    for idx, s_id in enumerate(req.source_ids):
        db.query(MovieSource).filter(
            MovieSource.id == s_id,
            MovieSource.movie_id == movie_id
        ).update({"order_index": idx + 1})
    db.commit()
    return JSONResponse({"status": "success", "message": "Đã lưu thứ tự các tập video thành công!"})

@router.post("/api/v1/movies/{movie_id}/sources/add-youtube")
async def add_youtube_source(
    movie_id: int,
    youtube_url: str = Form(...),
    db: Session = Depends(get_db)
):
    """Add an extra YouTube clip/trailer to the movie's media pool."""
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")

    from app.video.youtube_downloader import YouTubeTrailerDownloader, slugify_filename
    import asyncio
    clean_prefix = slugify_filename(movie.title, movie.release_year, fallback_title=movie.original_title)
    
    file_path = await asyncio.to_thread(
        YouTubeTrailerDownloader.download_trailer,
        query_or_url=youtube_url.strip(),
        output_dir=str(settings.SOURCE_MEDIA_DIR),
        filename_prefix=f"{clean_prefix}_clip"
    )
    
    if not file_path:
        raise HTTPException(status_code=500, detail="Không thể tải video từ YouTube. Vui lòng kiểm tra lại link.")

    source = MovieSource(
        movie_id=movie.id,
        source_type="youtube_clip",
        file_path=file_path,
        license_info=youtube_url.strip(),
        order_index=len(movie.sources) + 1,
        is_verified=True
    )
    db.add(source)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã thêm nguồn video YouTube mới cho phim '{movie.title}'!"})

@router.post("/api/v1/movies/{movie_id}/sources/add-upload")
async def add_upload_source(
    movie_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Add an extra uploaded MP4 clip to the movie's media pool."""
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")

    from app.video.youtube_downloader import slugify_filename
    clean_name = slugify_filename(movie.title, movie.release_year, fallback_title=movie.original_title)

    dest_file = settings.SOURCE_MEDIA_DIR / f"{clean_name}_{file.filename}"
    with open(dest_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    source = MovieSource(
        movie_id=movie.id,
        source_type="user_upload_clip",
        file_path=str(dest_file),
        license_info=file.filename,
        order_index=len(movie.sources) + 1,
        is_verified=True
    )
    db.add(source)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã thêm clip video '{file.filename}' vào nguồn phim!"})

@router.delete("/api/v1/movies/{movie_id}/sources/{source_id}")
async def delete_movie_source(
    movie_id: int,
    source_id: int,
    db: Session = Depends(get_db)
):
    """Delete a specific media source from a movie."""
    source = db.query(MovieSource).filter(MovieSource.id == source_id, MovieSource.movie_id == movie_id).first()
    if not source:
        raise HTTPException(status_code=404, detail="Không tìm thấy nguồn video này")

    if source.file_path and Path(source.file_path).exists() and "source" in source.file_path:
        try:
            Path(source.file_path).unlink()
        except Exception:
            pass

    db.delete(source)
    db.commit()
    return JSONResponse({"status": "success", "message": "Đã xóa nguồn video thành công!"})

@router.get("/api/v1/movies/{movie_id}/source-stream")
async def stream_movie_source(movie_id: int, db: Session = Depends(get_db)):
    """Stream or redirect to the source media file/trailer for verification."""
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie or not movie.sources:
        raise HTTPException(status_code=404, detail="Phim chưa có nguồn video media nào")

    source = movie.sources[0]
    file_path = source.file_path

    if file_path.startswith("http://") or file_path.startswith("https://"):
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=file_path)

    p = Path(file_path)
    if not p.exists():
        raise HTTPException(status_code=404, detail="File video nguồn không tồn tại trên ổ cứng")

    return FileResponse(p, media_type="video/mp4", filename=p.name)

from typing import List
from pydantic import BaseModel

class BulkDeleteMovieRequest(BaseModel):
    ids: List[int]

@router.delete("/api/v1/movies/{movie_id}")
async def delete_movie(movie_id: int, db: Session = Depends(get_db)):
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")
    
    # Delete movie sources
    sources = db.query(MovieSource).filter(MovieSource.movie_id == movie_id).all()
    for s in sources:
        if s.file_path and Path(s.file_path).exists():
            try:
                Path(s.file_path).unlink()
            except Exception:
                pass
        db.delete(s)
        
    db.delete(movie)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã xóa phim #{movie_id} thành công!"})

@router.post("/api/v1/movies/bulk-delete")
async def bulk_delete_movies(req: BulkDeleteMovieRequest, db: Session = Depends(get_db)):
    if not req.ids:
        raise HTTPException(status_code=400, detail="Danh sách ID rỗng")
    
    movies = db.query(Movie).filter(Movie.id.in_(req.ids)).all()
    count = len(movies)
    for m in movies:
        sources = db.query(MovieSource).filter(MovieSource.movie_id == m.id).all()
        for s in sources:
            if s.file_path and Path(s.file_path).exists():
                try:
                    Path(s.file_path).unlink()
                except Exception:
                    pass
            db.delete(s)
        db.delete(m)
        
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã xóa thành công {count} bộ phim!"})
