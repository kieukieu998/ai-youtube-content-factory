from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Float, Boolean, 
    DateTime, ForeignKey, BigInteger
)
from sqlalchemy.orm import relationship
from app.database.session import Base

class Setting(Base):
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Movie(Base):
    __tablename__ = "movies"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), index=True, nullable=False)
    original_title = Column(String(255), nullable=True)
    release_year = Column(Integer, nullable=True)
    genre = Column(String(100), nullable=True)
    duration_minutes = Column(Integer, nullable=True)
    synopsis = Column(Text, nullable=True)
    poster_url = Column(String(500), nullable=True)
    potential_score = Column(Float, default=0.0)
    status = Column(String(50), default="discovered", index=True) # discovered, analyzed, scripted, completed
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    sources = relationship("MovieSource", back_populates="movie", cascade="all, delete-orphan")
    scripts = relationship("Script", back_populates="movie", cascade="all, delete-orphan")

class MovieSource(Base):
    __tablename__ = "movie_sources"
    
    id = Column(Integer, primary_key=True, index=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    source_type = Column(String(50), default="user_upload") # user_upload, public_domain, licensed_partner
    file_path = Column(String(500), nullable=False)
    license_info = Column(Text, nullable=True)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    movie = relationship("Movie", back_populates="sources")

class Script(Base):
    __tablename__ = "scripts"
    
    id = Column(Integer, primary_key=True, index=True)
    movie_id = Column(Integer, ForeignKey("movies.id"), nullable=False)
    title = Column(String(255), nullable=False)
    target_episodes = Column(Integer, default=3)
    full_script = Column(Text, nullable=True)
    style = Column(String(50), default="dramatic")
    language = Column(String(10), default="vi")
    created_at = Column(DateTime, default=datetime.utcnow)
    
    movie = relationship("Movie", back_populates="scripts")
    episodes = relationship("Episode", back_populates="script", cascade="all, delete-orphan")

class Episode(Base):
    __tablename__ = "episodes"
    
    id = Column(Integer, primary_key=True, index=True)
    script_id = Column(Integer, ForeignKey("scripts.id"), nullable=False)
    episode_number = Column(Integer, nullable=False)
    hook_text = Column(Text, nullable=True)
    hook_score = Column(Float, default=0.0)
    content_text = Column(Text, nullable=False)
    call_to_action = Column(Text, nullable=True)
    status = Column(String(50), default="draft", index=True) # draft, approval_pending, approved, voice_ready, rendered, qa_passed, published
    created_at = Column(DateTime, default=datetime.utcnow)
    
    script = relationship("Script", back_populates="episodes")
    media_files = relationship("MediaFile", back_populates="episode", cascade="all, delete-orphan")
    videos = relationship("Video", back_populates="episode", cascade="all, delete-orphan")

class MediaFile(Base):
    __tablename__ = "media_files"
    
    id = Column(Integer, primary_key=True, index=True)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=True)
    file_type = Column(String(50), nullable=False) # audio_tts, audio_bgm, subtitle_ass, subtitle_srt, cut_scene, preview
    file_path = Column(String(500), nullable=False)
    duration_seconds = Column(Float, default=0.0)
    file_size_bytes = Column(BigInteger, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    episode = relationship("Episode", back_populates="media_files")

class Video(Base):
    __tablename__ = "videos"
    
    id = Column(Integer, primary_key=True, index=True)
    episode_id = Column(Integer, ForeignKey("episodes.id"), nullable=False)
    file_path = Column(String(500), nullable=False)
    resolution = Column(String(20), default="1080x1920")
    fps = Column(Integer, default=30)
    duration_seconds = Column(Float, nullable=False)
    file_size_bytes = Column(BigInteger, default=0)
    qa_status = Column(String(50), default="pending", index=True) # pending, passed, failed
    qa_notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    episode = relationship("Episode", back_populates="videos")
    publishes = relationship("Publish", back_populates="video", cascade="all, delete-orphan")

class Job(Base):
    __tablename__ = "jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(50), nullable=False, index=True) # MovieJob, ScriptJob, SceneSliceJob, VoiceJob, SubtitleJob, VideoJob, QAJob, PublishJob, CleanupJob
    status = Column(String(50), default="pending", index=True) # pending, processing, completed, failed, cancelled
    progress = Column(Integer, default=0)
    payload = Column(Text, nullable=True) # JSON
    result = Column(Text, nullable=True) # JSON
    error_message = Column(Text, nullable=True)
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Publish(Base):
    __tablename__ = "publishes"
    
    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(Integer, ForeignKey("videos.id"), nullable=False)
    platform = Column(String(50), default="tiktok", index=True) # tiktok, youtube_shorts, facebook_reels
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    hashtags = Column(Text, nullable=True)
    tiktok_post_id = Column(String(100), nullable=True)
    published_at = Column(DateTime, nullable=True)
    status = Column(String(50), default="scheduled", index=True) # scheduled, publishing, published, failed
    error_message = Column(Text, nullable=True)
    
    video = relationship("Video", back_populates="publishes")
    analytics = relationship("Analytics", back_populates="publish", cascade="all, delete-orphan")

class Analytics(Base):
    __tablename__ = "analytics"
    
    id = Column(Integer, primary_key=True, index=True)
    publish_id = Column(Integer, ForeignKey("publishes.id"), nullable=False)
    views_count = Column(Integer, default=0)
    likes_count = Column(Integer, default=0)
    comments_count = Column(Integer, default=0)
    shares_count = Column(Integer, default=0)
    avg_watch_time = Column(Float, default=0.0)
    retention_rate = Column(Float, default=0.0)
    recorded_at = Column(DateTime, default=datetime.utcnow)
    
    publish = relationship("Publish", back_populates="analytics")

class AIRun(Base):
    __tablename__ = "ai_runs"
    
    id = Column(Integer, primary_key=True, index=True)
    agent_name = Column(String(100), nullable=False, index=True)
    provider = Column(String(50), nullable=False) # gemini_free, openai, deepseek, claude
    model_name = Column(String(100), nullable=False)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    execution_time_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
