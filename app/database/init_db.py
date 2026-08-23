import json
from app.database.session import engine, Base, SessionLocal
from app.database.models import Setting
from loguru import logger

def init_db():
    """Create all tables and seed default settings."""
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    
    # Auto-migrate missing columns for SQLite
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            # Check created_by in movies
            cols_m = [c[1] for c in conn.execute(text("PRAGMA table_info(movies)")).fetchall()]
            if "created_by" not in cols_m:
                conn.execute(text("ALTER TABLE movies ADD COLUMN created_by VARCHAR(50) DEFAULT 'ai'"))
                conn.commit()
                logger.info("Migrated column movies.created_by")

            # Check title, video_type, movie_id in videos
            cols_v = [c[1] for c in conn.execute(text("PRAGMA table_info(videos)")).fetchall()]
            if "title" not in cols_v:
                conn.execute(text("ALTER TABLE videos ADD COLUMN title VARCHAR(255)"))
                conn.commit()
                logger.info("Migrated column videos.title")
            if "video_type" not in cols_v:
                conn.execute(text("ALTER TABLE videos ADD COLUMN video_type VARCHAR(50) DEFAULT 'script_review'"))
                conn.commit()
                logger.info("Migrated column videos.video_type")
            if "movie_id" not in cols_v:
                conn.execute(text("ALTER TABLE videos ADD COLUMN movie_id INTEGER REFERENCES movies(id)"))
                conn.commit()
                logger.info("Migrated column videos.movie_id")
    except Exception as e:
        logger.warning(f"Column migration notice: {e}")
    
    db = SessionLocal()
    try:
        # Default settings definitions
        default_settings = {
            "default_ai_provider": "gemini_free",
            "operation_mode": "semi_auto", # semi_auto or full_auto
            "default_tts_voice": "vi-VN-HoaiMyNeural",
            "default_tts_speed": "1.0",
            "daily_budget_limit_usd": "0.0",
            "target_episodes_default": "3",
            "video_render_preset": "blurred_stack_9_16",
            "anti_shadowban_enabled": "true",
            "audio_ducking_enabled": "true",
            "auto_cleanup_working_dir": "true"
        }
        
        for key, value in default_settings.items():
            existing = db.query(Setting).filter(Setting.key == key).first()
            if not existing:
                db.add(Setting(key=key, value=value))
                logger.info(f"Seeded default setting: {key} = {value}")
                
        db.commit()
        logger.info("Database initialization completed successfully!")
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to initialize database: {e}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
