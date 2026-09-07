import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
    class ConfigBase(BaseSettings):
        model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
except ImportError:
    from pydantic import BaseModel
    class ConfigBase(BaseModel):
        pass

def _resolve_ffmpeg_binary() -> str:
    import shutil
    env_val = os.getenv("FFMPEG_PATH")
    if env_val and (shutil.which(env_val) or os.path.exists(env_val)):
        return env_val
    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.exists(exe):
            return exe
    except Exception:
        pass
    return "ffmpeg"

class Settings(ConfigBase):
    # App General Settings
    APP_NAME: str = os.getenv("APP_NAME", "AI Movie Content Factory")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_HOST: str = os.getenv("APP_HOST", "127.0.0.1")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "super_secret_movie_content_factory_key_2026")
    
    # Paths
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    MEDIA_DIR: Path = BASE_DIR / "media"
    SOURCE_MEDIA_DIR: Path = BASE_DIR / "media" / "source"
    WORKING_MEDIA_DIR: Path = BASE_DIR / "media" / "working"
    OUTPUT_MEDIA_DIR: Path = BASE_DIR / "media" / "output"
    BGM_MEDIA_DIR: Path = BASE_DIR / "media" / "bgm"
    LOGS_DIR: Path = BASE_DIR / "logs"
    
    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR}/data/movie_ai.db")
    
    # AI Providers (Default: Gemini Free)
    DEFAULT_AI_PROVIDER: str = os.getenv("DEFAULT_AI_PROVIDER", "gemini_free")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    DEEPSEEK_API_KEY: Optional[str] = os.getenv("DEEPSEEK_API_KEY")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY")
    
    # Audio TTS
    DEFAULT_TTS_VOICE: str = os.getenv("DEFAULT_TTS_VOICE", "vi-VN-HoaiMyNeural")
    DEFAULT_TTS_SPEED: float = float(os.getenv("DEFAULT_TTS_SPEED", "1.0"))
    
    # Video & FFmpeg
    FFMPEG_PATH: str = _resolve_ffmpeg_binary()
    FFPROBE_PATH: str = os.getenv("FFPROBE_PATH", "ffprobe")
    
    # TikTok Publishing API
    TIKTOK_CLIENT_KEY: Optional[str] = os.getenv("TIKTOK_CLIENT_KEY")
    TIKTOK_CLIENT_SECRET: Optional[str] = os.getenv("TIKTOK_CLIENT_SECRET")
    TIKTOK_REDIRECT_URI: str = os.getenv("TIKTOK_REDIRECT_URI", "http://localhost:8000/api/v1/publishing/tiktok/callback")
    
    # Emergency & Guard
    DAILY_BUDGET_LIMIT_USD: float = float(os.getenv("DAILY_BUDGET_LIMIT_USD", "0.0"))
    OPERATION_MODE: str = os.getenv("OPERATION_MODE", "semi_auto")
    TELEGRAM_BOT_TOKEN: Optional[str] = os.getenv("TELEGRAM_BOT_TOKEN")
    def model_post_init(self, __context):
        self.FFMPEG_PATH = _resolve_ffmpeg_binary()

settings = Settings()
settings.FFMPEG_PATH = _resolve_ffmpeg_binary()

# Ensure directories exist
for directory in [
    settings.DATA_DIR,
    settings.MEDIA_DIR,
    settings.SOURCE_MEDIA_DIR,
    settings.WORKING_MEDIA_DIR,
    settings.OUTPUT_MEDIA_DIR,
    settings.BGM_MEDIA_DIR,
    settings.LOGS_DIR,
]:
    directory.mkdir(parents=True, exist_ok=True)
