import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from starlette.staticfiles import StaticFiles
from loguru import logger
import uvicorn

from app.core.config import settings
from app.database.init_db import init_db
from app.scheduler.job_worker import JobWorker

# Import Routers
from app.api.dashboard_router import router as dashboard_router
from app.api.movies_router import router as movies_router
from app.api.scripts_router import router as scripts_router
from app.api.videos_router import router as videos_router
from app.api.jobs_router import router as jobs_router
from app.api.settings_router import router as settings_router
from app.api.transform_router import router as transform_router
from app.api.stories_router import router as stories_router
from app.api.publishing_router import router as publishing_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan event handler: Startup database and background worker."""
    logger.info("Initializing AI Movie Content Factory Application...")
    # 1. Initialize SQLite database & settings
    init_db()
    
    # 1.1 Reset interrupted processing jobs back to pending
    try:
        from app.database.session import SessionLocal
        from app.database.models import Job
        db = SessionLocal()
        stuck_jobs = db.query(Job).filter(Job.status == "processing").all()
        if stuck_jobs:
            logger.info(f"Auto-recovering {len(stuck_jobs)} interrupted jobs...")
            for j in stuck_jobs:
                j.status = "pending"
                j.progress = 0
            db.commit()
        db.close()
    except Exception as e:
        logger.warning(f"Could not auto-recover jobs: {e}")
    
    # 2. Launch Background Worker Task
    worker_task = asyncio.create_task(JobWorker.start_worker_loop())
    logger.info("Background Queue Worker successfully started!")
    
    yield
    
    # 3. Shutdown
    logger.info("Shutting down Application...")
    JobWorker._is_running = False
    worker_task.cancel()

from app.core.version import get_app_version

# Create FastAPI App instance
app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered short-form movie review video factory for TikTok & Shorts",
    version=get_app_version(),
    lifespan=lifespan
)

from starlette.responses import FileResponse

# Mount Static Files & Media
static_path = Path(__file__).resolve().parent / "static"
static_path.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return FileResponse(static_path / "favicon.ico")

media_path = settings.MEDIA_DIR
app.mount("/media", StaticFiles(directory=str(media_path)), name="media")

# Register API & Web Routers
app.include_router(dashboard_router, tags=["Dashboard"])
app.include_router(movies_router, tags=["Movies"])
app.include_router(scripts_router, tags=["Scripts"])
app.include_router(videos_router, tags=["Videos"])
app.include_router(transform_router, tags=["Transformer"])
app.include_router(stories_router, tags=["Stories"])
app.include_router(jobs_router, tags=["Jobs"])
app.include_router(settings_router, tags=["Settings"])
app.include_router(publishing_router, tags=["Publishing"])

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=True
    )
