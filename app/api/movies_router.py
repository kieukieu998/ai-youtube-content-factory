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

@router.get("/movies", response_class=HTMLResponse)
async def movies_list_page(request: Request, db: Session = Depends(get_db)):
    movies = db.query(Movie).order_by(Movie.created_at.desc()).all()
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
            "synopsis": movie.synopsis
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

    from app.video.youtube_downloader import YouTubeTrailerDownloader
    import asyncio

    # Download in thread
    info = await asyncio.to_thread(
        YouTubeTrailerDownloader.get_video_info_and_download,
        query_or_url=url,
        output_dir=str(settings.SOURCE_MEDIA_DIR),
        filename_prefix="movie_yt"
    )

    if not info.get("file_path"):
        raise HTTPException(status_code=500, detail="Không thể tải video từ link YouTube này. Vui lòng kiểm tra lại URL.")

    movie_title = title.strip() if (title and title.strip()) else (info.get("title") or "Phim Chưa Đặt Tên")
    movie_orig = original_title.strip() if (original_title and original_title.strip()) else movie_title
    movie_synopsis = synopsis.strip() if (synopsis and synopsis.strip()) else (info.get("description", "")[:400] if info.get("description") else f"Video phim nhập từ YouTube: {movie_title}")
    
    movie = Movie(
        title=movie_title,
        original_title=movie_orig,
        release_year=release_year,
        genre=genre,
        duration_minutes=info.get("duration", 0),
        synopsis=movie_synopsis,
        potential_score=90.0,
        status="discovered"
    )
    db.add(movie)
    db.flush()

    # Move/rename to movie ID prefix for neat organization
    orig_path = Path(info["file_path"])
    dest_path = settings.SOURCE_MEDIA_DIR / f"movie_{movie.id}_{orig_path.name}"
    try:
        orig_path.rename(dest_path)
        final_file_path = str(dest_path)
    except Exception:
        final_file_path = str(orig_path)

    source = MovieSource(
        movie_id=movie.id,
        source_type="youtube_link",
        file_path=final_file_path,
        is_verified=True
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

    dest_file = settings.SOURCE_MEDIA_DIR / f"movie_{movie_id}_{file.filename}"
    with open(dest_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    source = MovieSource(
        movie_id=movie.id,
        source_type="user_upload",
        file_path=str(dest_file),
        is_verified=True
    )
    db.add(source)
    db.commit()
    return JSONResponse({"status": "success", "message": "Tải lên video nguồn thành công!"})

@router.post("/api/v1/movies/{movie_id}/fetch-trailer")
async def fetch_trailer_youtube(
    movie_id: int,
    youtube_url: str = Form(None),
    db: Session = Depends(get_db)
):
    movie = db.query(Movie).filter(Movie.id == movie_id).first()
    if not movie:
        raise HTTPException(status_code=404, detail="Không tìm thấy phim")

    from app.video.youtube_downloader import YouTubeTrailerDownloader
    search_query = youtube_url if youtube_url and youtube_url.strip() else f"{movie.original_title or movie.title} {movie.release_year or ''}"
    
    file_path = YouTubeTrailerDownloader.download_trailer(
        query_or_url=search_query,
        output_dir=str(settings.SOURCE_MEDIA_DIR),
        filename_prefix=f"movie_{movie.id}"
    )
    
    if not file_path:
        raise HTTPException(status_code=500, detail="Không thể tải trailer từ YouTube. Vui lòng kiểm tra lại đường truyền hoặc link.")

    # Save to movie sources
    source = MovieSource(
        movie_id=movie.id,
        source_type="youtube_trailer",
        file_path=file_path,
        is_verified=True
    )
    db.add(source)
    db.commit()
    return JSONResponse({"status": "success", "message": f"Đã tự động tải thành công trailer cho phim '{movie.title}'!"})

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
