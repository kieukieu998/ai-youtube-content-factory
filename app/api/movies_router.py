import os
import json
import shutil
from pathlib import Path
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

    from app.video.youtube_downloader import YouTubeTrailerDownloader, slugify_filename
    import asyncio

    # Try fast extraction first for immediate responsiveness
    fast_info = await asyncio.to_thread(YouTubeTrailerDownloader.extract_metadata_fast, url)

    # Attempt download
    info = await asyncio.to_thread(
        YouTubeTrailerDownloader.get_video_info_and_download,
        query_or_url=url,
        output_dir=str(settings.SOURCE_MEDIA_DIR),
        filename_prefix="movie_yt"
    )

    movie_title = (
        (title.strip() if title and title.strip() else None)
        or info.get("title")
        or fast_info.get("title")
        or "Phim Chưa Đặt Tên"
    )
    movie_orig = (
        (original_title.strip() if original_title and original_title.strip() else None)
        or movie_title
    )
    raw_desc = info.get("description") or fast_info.get("description") or ""
    movie_synopsis = (
        (synopsis.strip() if synopsis and synopsis.strip() else None)
        or (raw_desc[:400] if raw_desc else f"Phim nhập từ YouTube: {movie_title}")
    )
    duration_val = info.get("duration") or fast_info.get("duration") or 0

    movie = Movie(
        title=movie_title,
        original_title=movie_orig,
        release_year=release_year,
        genre=genre,
        duration_minutes=duration_val,
        synopsis=movie_synopsis,
        potential_score=90.0,
        status="discovered"
    )
    db.add(movie)
    db.flush()

    final_file_path = None
    if info.get("file_path") and os.path.exists(info["file_path"]):
        orig_path = Path(info["file_path"])
        clean_name = slugify_filename(movie.title, movie.release_year)
        dest_path = settings.SOURCE_MEDIA_DIR / f"{movie.id}_{clean_name}_{orig_path.name}"
        try:
            orig_path.rename(dest_path)
            final_file_path = str(dest_path)
        except Exception:
            final_file_path = str(orig_path)
    else:
        final_file_path = url

    source = MovieSource(
        movie_id=movie.id,
        source_type="youtube_link",
        file_path=final_file_path,
        license_info=url,
        is_verified=bool(info.get("file_path") and os.path.exists(info["file_path"]))
    )
    db.add(source)
    db.commit()

    return JSONResponse({
        "status": "success",
        "message": f"Đã thêm thành công phim '{movie.title}' từ YouTube vào kho dữ liệu!",
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
    clean_name = slugify_filename(movie.title, movie.release_year)

    # Clean up old source records and files
    for old_s in movie.sources:
        if old_s.file_path and Path(old_s.file_path).exists() and "source" in old_s.file_path:
            try:
                Path(old_s.file_path).unlink()
            except Exception:
                pass
        db.delete(old_s)

    dest_file = settings.SOURCE_MEDIA_DIR / f"{movie_id}_{clean_name}_{file.filename}"
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
    search_query = youtube_url.strip() if youtube_url and youtube_url.strip() else f"{movie.original_title or movie.title} {movie.release_year or ''}"
    clean_prefix = slugify_filename(movie.title, movie.release_year)

    file_path = YouTubeTrailerDownloader.download_trailer(
        query_or_url=search_query,
        output_dir=str(settings.SOURCE_MEDIA_DIR),
        filename_prefix=f"{movie.id}_{clean_prefix}"
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
