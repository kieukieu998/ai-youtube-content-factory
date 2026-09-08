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

            # Check characters_json in stories
            try:
                cols_s = [c[1] for c in conn.execute(text("PRAGMA table_info(stories)")).fetchall()]
                if "characters_json" not in cols_s and len(cols_s) > 0:
                    conn.execute(text("ALTER TABLE stories ADD COLUMN characters_json TEXT"))
                    conn.commit()
                    logger.info("Migrated column stories.characters_json")
            except Exception:
                pass

            # Check new columns in publishes
            try:
                cols_p = [c[1] for c in conn.execute(text("PRAGMA table_info(publishes)")).fetchall()]
                if len(cols_p) > 0:
                    if "story_id" not in cols_p:
                        conn.execute(text("ALTER TABLE publishes ADD COLUMN story_id INTEGER REFERENCES stories(id)"))
                    if "platform_video_id" not in cols_p:
                        conn.execute(text("ALTER TABLE publishes ADD COLUMN platform_video_id VARCHAR(100)"))
                    if "video_url" not in cols_p:
                        conn.execute(text("ALTER TABLE publishes ADD COLUMN video_url VARCHAR(500)"))
                    if "video_aspect" not in cols_p:
                        conn.execute(text("ALTER TABLE publishes ADD COLUMN video_aspect VARCHAR(20)"))
                    if "privacy_status" not in cols_p:
                        conn.execute(text("ALTER TABLE publishes ADD COLUMN privacy_status VARCHAR(50) DEFAULT 'public'"))
                    if "created_at" not in cols_p:
                        conn.execute(text("ALTER TABLE publishes ADD COLUMN created_at DATETIME"))
                    # Ensure video_id is nullable for story publishing
                    table_info = conn.execute(text("PRAGMA table_info(publishes)")).fetchall()
                    vid_col = next((c for c in table_info if c[1] == "video_id"), None)
                    if vid_col and vid_col[3] == 1: # notnull == 1
                        logger.info("Migrating publishes table to make video_id nullable for stories...")
                        conn.execute(text("""
                            CREATE TABLE IF NOT EXISTS publishes_new (
                                id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
                                video_id INTEGER REFERENCES videos(id),
                                story_id INTEGER REFERENCES stories(id),
                                platform VARCHAR(50) DEFAULT 'youtube',
                                title VARCHAR(255),
                                description TEXT,
                                hashtags TEXT,
                                platform_video_id VARCHAR(100),
                                tiktok_post_id VARCHAR(100),
                                video_url VARCHAR(500),
                                video_aspect VARCHAR(20),
                                privacy_status VARCHAR(50) DEFAULT 'public',
                                published_at DATETIME,
                                status VARCHAR(50) DEFAULT 'scheduled',
                                error_message TEXT,
                                created_at DATETIME
                            );
                        """))
                        conn.execute(text("""
                            INSERT INTO publishes_new (id, video_id, story_id, platform, title, description, hashtags, platform_video_id, tiktok_post_id, video_url, video_aspect, privacy_status, published_at, status, error_message, created_at)
                            SELECT id, video_id, story_id, platform, title, description, hashtags, platform_video_id, tiktok_post_id, video_url, video_aspect, privacy_status, published_at, status, error_message, created_at
                            FROM publishes;
                        """))
                        conn.execute(text("DROP TABLE publishes;"))
                        conn.execute(text("ALTER TABLE publishes_new RENAME TO publishes;"))
                        conn.commit()
                        logger.info("Migrated publishes table: video_id is now nullable.")
            except Exception as pe:
                logger.warning(f"Publishes migration notice: {pe}")
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
