import os
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from loguru import logger

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

class YouTubePublisher:
    """Handles YouTube Data API v3 OAuth authentication, channel info, and video uploading."""

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube.readonly"
    ]
    
    CONFIG_DIR = Path("config")
    CLIENT_SECRET_FILE = CONFIG_DIR / "youtube_client_secret.json"
    TOKEN_FILE = CONFIG_DIR / "youtube_token.json"

    @classmethod
    def is_client_secret_configured(cls) -> bool:
        """Check if client_secrets.json file exists and is valid JSON."""
        if not cls.CLIENT_SECRET_FILE.exists():
            return False
        try:
            with open(cls.CLIENT_SECRET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return "web" in data or "installed" in data
        except Exception:
            return False

    @classmethod
    def save_client_secret(cls, secret_data: Dict[str, Any]) -> bool:
        """Save uploaded or pasted client_secrets JSON content."""
        try:
            cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(cls.CLIENT_SECRET_FILE, "w", encoding="utf-8") as f:
                json.dump(secret_data, f, indent=2, ensure_ascii=False)
            logger.info("Successfully saved youtube_client_secret.json")
            return True
        except Exception as e:
            logger.error(f"Failed to save client_secret: {e}")
            return False

    @classmethod
    def get_credentials(cls) -> Optional[Credentials]:
        """Load and automatically refresh credentials if expired."""
        if not cls.TOKEN_FILE.exists():
            return None

        try:
            creds = Credentials.from_authorized_user_file(str(cls.TOKEN_FILE), cls.SCOPES)
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired YouTube OAuth credentials...")
                creds.refresh(Request())
                with open(cls.TOKEN_FILE, "w", encoding="utf-8") as f:
                    f.write(creds.to_json())
                logger.info("YouTube OAuth token refreshed successfully.")
            return creds if (creds and creds.valid) else None
        except Exception as e:
            logger.warning(f"Error loading/refreshing YouTube credentials: {e}")
            return None

    @classmethod
    def is_authenticated(cls) -> bool:
        """Check if user has an active, valid authentication token."""
        creds = cls.get_credentials()
        return creds is not None and creds.valid

    @classmethod
    def get_auth_url(cls, redirect_uri: str) -> str:
        """Generate Google OAuth 2.0 authorization URL."""
        if not cls.is_client_secret_configured():
            raise FileNotFoundError(
                "Chưa tìm thấy file cấu hình 'config/youtube_client_secret.json'. "
                "Vui lòng tạo OAuth Client ID trên Google Cloud Console và tải file về máy."
            )

        flow = Flow.from_client_secrets_file(
            str(cls.CLIENT_SECRET_FILE),
            scopes=cls.SCOPES,
            redirect_uri=redirect_uri
        )
        auth_url, _ = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent"
        )
        return auth_url

    @classmethod
    def exchange_code(cls, code: str, redirect_uri: str) -> bool:
        """Exchange authorization code for access and refresh tokens."""
        if not cls.is_client_secret_configured():
            raise FileNotFoundError("Chưa cấu hình client_secret.json")

        try:
            flow = Flow.from_client_secrets_file(
                str(cls.CLIENT_SECRET_FILE),
                scopes=cls.SCOPES,
                redirect_uri=redirect_uri
            )
            flow.fetch_token(code=code)
            creds = flow.credentials

            cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(cls.TOKEN_FILE, "w", encoding="utf-8") as f:
                f.write(creds.to_json())

            logger.info("Successfully saved YouTube OAuth credentials to youtube_token.json")
            return True
        except Exception as e:
            logger.error(f"Failed to exchange authorization code: {e}")
            raise e

    @classmethod
    def disconnect(cls) -> bool:
        """Remove saved token to disconnect channel."""
        try:
            if cls.TOKEN_FILE.exists():
                cls.TOKEN_FILE.unlink()
                logger.info("Disconnected YouTube channel by deleting token file.")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting YouTube: {e}")
            return False

    @classmethod
    def get_channel_info(cls) -> Dict[str, Any]:
        """Fetch connected YouTube channel profile and subscriber metrics."""
        creds = cls.get_credentials()
        if not creds:
            return {
                "connected": False,
                "has_secret": cls.is_client_secret_configured(),
                "message": "Chưa kết nối tài khoản YouTube"
            }

        try:
            youtube = build("youtube", "v3", credentials=creds)
            resp = youtube.channels().list(
                mine=True,
                part="snippet,statistics"
            ).execute()

            items = resp.get("items", [])
            if not items:
                return {
                    "connected": True,
                    "has_secret": True,
                    "title": "Tài Khoản Google (Chưa tạo Kênh)",
                    "avatar_url": "",
                    "subscriber_count": 0,
                    "video_count": 0
                }

            ch = items[0]
            snippet = ch.get("snippet", {})
            stats = ch.get("statistics", {})

            return {
                "connected": True,
                "has_secret": True,
                "channel_id": ch.get("id"),
                "title": snippet.get("title", "Kênh YouTube"),
                "custom_url": snippet.get("customUrl", ""),
                "description": snippet.get("description", ""),
                "avatar_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                "subscriber_count": int(stats.get("subscriberCount", 0)),
                "video_count": int(stats.get("videoCount", 0)),
                "view_count": int(stats.get("viewCount", 0))
            }
        except Exception as e:
            logger.warning(f"Error fetching YouTube channel info: {e}")
            return {
                "connected": False,
                "has_secret": cls.is_client_secret_configured(),
                "error": str(e)
            }

    @classmethod
    def upload_video(
        cls,
        file_path: str,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        privacy_status: str = "public",
        category_id: str = "24", # 24 = Entertainment, 27 = Education
        is_shorts: bool = False,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Upload video to YouTube with resumable chunked upload & live progress stream.
        Automatically appends #Shorts for vertical 9:16 videos.
        """
        creds = cls.get_credentials()
        if not creds:
            raise RuntimeError("Chưa kết nối tài khoản YouTube hoặc token đã hết hạn.")

        video_file = Path(file_path).resolve()
        if not video_file.exists():
            raise FileNotFoundError(f"Không tìm thấy file video: {file_path}")

        file_size = os.path.getsize(video_file)

        # Optimize title and tags for Shorts if vertical format
        clean_title = title.strip()
        if is_shorts and "#Shorts" not in clean_title and "#shorts" not in clean_title:
            clean_title = f"{clean_title} #Shorts"

        tags_list = tags or ["AI Content", "Audiobook", "Review Phim"]
        if is_shorts and "Shorts" not in tags_list:
            tags_list.append("Shorts")

        body = {
            "snippet": {
                "title": clean_title[:100], # YouTube title max 100 chars
                "description": description[:5000], # Max 5000 chars
                "tags": tags_list[:50],
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": privacy_status, # public, private, unlisted
                "selfDeclaredMadeForKids": False
            }
        }

        youtube = build("youtube", "v3", credentials=creds)

        # 4MB chunk size for smooth resumable upload
        chunk_size = 4 * 1024 * 1024
        media = MediaFileUpload(
            str(video_file),
            mimetype="video/mp4",
            chunksize=chunk_size,
            resumable=True
        )

        logger.info(f"Initiating YouTube Resumable Upload for: {clean_title} ({file_size / (1024*1024):.1f} MB)...")
        if progress_callback:
            try:
                progress_callback(0.05, "Đang khởi tạo kết nối upload YouTube...")
            except Exception:
                pass

        insert_request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = insert_request.next_chunk()
            if status:
                progress_float = float(status.progress())
                pct = min(0.95, max(0.05, progress_float))
                uploaded_mb = (progress_float * file_size) / (1024 * 1024)
                total_mb = file_size / (1024 * 1024)
                msg = f"Đang upload lên YouTube: {int(pct*100)}% ({uploaded_mb:.1f}/{total_mb:.1f} MB)"
                logger.debug(msg)
                if progress_callback:
                    try:
                        progress_callback(pct, msg)
                    except Exception:
                        pass

        video_id = response.get("id")
        video_url = f"https://youtu.be/{video_id}"
        logger.info(f"YouTube Upload Finished Successfully! Video ID: {video_id} -> {video_url}")

        if progress_callback:
            try:
                progress_callback(1.0, f"Đăng video thành công ({video_url})!")
            except Exception:
                pass

        return {
            "video_id": video_id,
            "video_url": video_url,
            "title": clean_title,
            "privacy_status": privacy_status,
            "response": response
        }
