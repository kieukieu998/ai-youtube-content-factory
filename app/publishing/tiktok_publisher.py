import os
import json
import time
import uuid
import urllib.parse
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from loguru import logger
import requests

class TikTokPublisher:
    """Handles TikTok Content Posting API v2, OAuth authentication, channel info, and video uploading."""

    SCOPES = [
        "user.info.basic",
        "video.upload",
        "video.publish"
    ]

    CONFIG_DIR = Path("config")
    CLIENT_KEY_FILE = CONFIG_DIR / "tiktok_client_key.json"
    TOKEN_FILE = CONFIG_DIR / "tiktok_token.json"
    DEMO_MODE_FILE = CONFIG_DIR / "tiktok_demo_mode.json"

    AUTH_URL_ENDPOINT = "https://www.tiktok.com/v2/auth/authorize/"
    TOKEN_ENDPOINT = "https://open.tiktokapis.com/v2/oauth/token/"
    USER_INFO_ENDPOINT = "https://open.tiktokapis.com/v2/user/info/"
    PUBLISH_INIT_ENDPOINT = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    INBOX_INIT_ENDPOINT = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
    STATUS_FETCH_ENDPOINT = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"

    @classmethod
    def is_demo_mode(cls) -> bool:
        """Check if simulated test/demo mode is active. Defaults to True if client key not configured."""
        if not cls.is_client_key_configured():
            return True
        if not cls.DEMO_MODE_FILE.exists():
            return False
        try:
            with open(cls.DEMO_MODE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("enabled", False)
        except Exception:
            return False

    @classmethod
    def set_demo_mode(cls, enabled: bool = True) -> bool:
        """Enable or disable simulated test/demo mode."""
        try:
            cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(cls.DEMO_MODE_FILE, "w", encoding="utf-8") as f:
                json.dump({"enabled": enabled}, f, indent=2)
            logger.info(f"TikTok Demo Mode set to: {enabled}")
            return True
        except Exception as e:
            logger.error(f"Failed to toggle TikTok demo mode: {e}")
            return False

    @classmethod
    def is_client_key_configured(cls) -> bool:
        """Check if tiktok_client_key.json file exists and has valid credentials."""
        if not cls.CLIENT_KEY_FILE.exists():
            return False
        try:
            with open(cls.CLIENT_KEY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                key = data.get("client_key", "")
                secret = data.get("client_secret", "")
                if not key or not secret or "demo" in key or "placeholder" in key:
                    return False
                return True
        except Exception:
            return False

    @classmethod
    def save_client_key(cls, client_key: str, client_secret: str) -> bool:
        """Save Client Key and Client Secret."""
        try:
            cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(cls.CLIENT_KEY_FILE, "w", encoding="utf-8") as f:
                json.dump({
                    "client_key": client_key.strip(),
                    "client_secret": client_secret.strip()
                }, f, indent=2, ensure_ascii=False)
            cls.set_demo_mode(False)
            logger.info("Successfully saved tiktok_client_key.json and disabled demo mode.")
            return True
        except Exception as e:
            logger.error(f"Failed to save TikTok client key: {e}")
            return False

    @classmethod
    def is_authenticated(cls) -> bool:
        """Check if valid token exists or demo mode is active."""
        if cls.is_demo_mode():
            return True
        return cls.get_token() is not None

    @classmethod
    def get_token(cls) -> Optional[Dict[str, Any]]:
        """Load and auto-refresh token if expired."""
        if not cls.TOKEN_FILE.exists():
            return None
        try:
            with open(cls.TOKEN_FILE, "r", encoding="utf-8") as f:
                token_data = json.load(f)

            expires_at = token_data.get("expires_at", 0)
            # If expired and has refresh_token, try refreshing
            if time.time() > expires_at and token_data.get("refresh_token"):
                logger.info("TikTok access token expired. Refreshing...")
                refreshed = cls._refresh_token(token_data.get("refresh_token"))
                if refreshed:
                    return refreshed

            return token_data
        except Exception as e:
            logger.warning(f"Error loading TikTok token: {e}")
            return None

    @classmethod
    def _refresh_token(cls, refresh_token: str) -> Optional[Dict[str, Any]]:
        """Internal helper to refresh token via TikTok API."""
        try:
            with open(cls.CLIENT_KEY_FILE, "r", encoding="utf-8") as f:
                keys = json.load(f)

            payload = {
                "client_key": keys["client_key"],
                "client_secret": keys["client_secret"],
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            res = requests.post(cls.TOKEN_ENDPOINT, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=15)
            data = res.json()
            if data.get("error"):
                logger.error(f"TikTok token refresh failed: {data}")
                return None

            token_info = data.get("data", data)
            token_info["expires_at"] = time.time() + token_info.get("expires_in", 86400)
            with open(cls.TOKEN_FILE, "w", encoding="utf-8") as f:
                json.dump(token_info, f, indent=2)
            logger.info("Successfully refreshed TikTok OAuth token.")
            return token_info
        except Exception as e:
            logger.error(f"Error during TikTok token refresh: {e}")
            return None

    @classmethod
    def get_auth_url(cls, redirect_uri: str, state: Optional[str] = None) -> str:
        """Generate TikTok OAuth 2.0 Authorization URL."""
        if not cls.is_client_key_configured():
            raise FileNotFoundError(
                "Chưa tìm thấy cấu hình 'config/tiktok_client_key.json'. "
                "Vui lòng cấu hình Client Key & Secret trước."
            )

        with open(cls.CLIENT_KEY_FILE, "r", encoding="utf-8") as f:
            keys = json.load(f)

        client_key = keys["client_key"]
        csrf_state = state or uuid.uuid4().hex[:16]
        scope_str = ",".join(cls.SCOPES)

        params = {
            "client_key": client_key,
            "scope": scope_str,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": csrf_state
        }
        return f"{cls.AUTH_URL_ENDPOINT}?{urllib.parse.urlencode(params)}"

    @classmethod
    def exchange_code(cls, code: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange authorization code for access and refresh tokens."""
        if not cls.is_client_key_configured():
            raise FileNotFoundError("Chưa cấu hình Client Key.")

        with open(cls.CLIENT_KEY_FILE, "r", encoding="utf-8") as f:
            keys = json.load(f)

        payload = {
            "client_key": keys["client_key"],
            "client_secret": keys["client_secret"],
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri
        }

        res = requests.post(cls.TOKEN_ENDPOINT, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=20)
        data = res.json()

        if data.get("error") or data.get("error_code"):
            err_msg = data.get("error_description") or data.get("message") or str(data)
            raise RuntimeError(f"Lỗi xác thực TikTok: {err_msg}")

        token_info = data.get("data", data)
        token_info["expires_at"] = time.time() + token_info.get("expires_in", 86400)

        cls.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(cls.TOKEN_FILE, "w", encoding="utf-8") as f:
            json.dump(token_info, f, indent=2, ensure_ascii=False)

        cls.set_demo_mode(False)
        logger.info("TikTok OAuth tokens saved successfully.")
        return token_info

    @classmethod
    def disconnect(cls) -> bool:
        """Remove saved tokens and disconnect account."""
        try:
            if cls.TOKEN_FILE.exists():
                cls.TOKEN_FILE.unlink()
            logger.info("Disconnected TikTok account.")
            return True
        except Exception as e:
            logger.error(f"Error disconnecting TikTok: {e}")
            return False

    @classmethod
    def get_account_info(cls) -> Dict[str, Any]:
        """Retrieve connected TikTok creator profile information."""
        if cls.is_demo_mode():
            return {
                "connected": True,
                "is_demo": True,
                "has_key": cls.is_client_key_configured(),
                "open_id": "demo_open_id_tiktok_9988",
                "username": "@minhphong2311",
                "display_name": "Phong Nguyen Ba Minh",
                "avatar_url": "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=150&auto=format&fit=crop&q=80",
                "follower_count": 1420,
                "following_count": 89,
                "likes_count": 28400,
                "bio_description": "Kênh sáng tạo video hoạt hình & truyện ngắn đa giọng AI."
            }

        token_info = cls.get_token()
        if not token_info or not token_info.get("access_token"):
            return {
                "connected": False,
                "is_demo": False,
                "has_key": cls.is_client_key_configured(),
                "error": "Chưa kết nối tài khoản TikTok."
            }

        access_token = token_info["access_token"]
        try:
            fields = "open_id,union_id,avatar_url,display_name"
            headers = {"Authorization": f"Bearer {access_token}"}
            res = requests.get(f"{cls.USER_INFO_ENDPOINT}?fields={fields}", headers=headers, timeout=15)
            data = res.json()

            user_data = data.get("data", {}).get("user", {})
            display_name = user_data.get("display_name", "TikTok Creator")
            return {
                "connected": True,
                "is_demo": False,
                "has_key": True,
                "open_id": user_data.get("open_id") or token_info.get("open_id"),
                "username": f"@{display_name}",
                "display_name": display_name,
                "avatar_url": user_data.get("avatar_url"),
                "follower_count": user_data.get("follower_count", 0),
                "following_count": user_data.get("following_count", 0),
                "likes_count": user_data.get("likes_count", 0),
                "bio_description": user_data.get("bio_description", "")
            }
        except Exception as e:
            logger.warning(f"Error fetching TikTok user info: {e}")
            return {
                "connected": True,
                "is_demo": False,
                "has_key": True,
                "open_id": token_info.get("open_id"),
                "username": "@creator",
                "display_name": "TikTok Creator",
                "avatar_url": None,
                "follower_count": 0,
                "following_count": 0,
                "likes_count": 0,
                "bio_description": ""
            }

    @classmethod
    def upload_video(
        cls,
        file_path: str,
        title: str,
        privacy_level: str = "PUBLIC_TO_EVERYONE", # PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, SELF_ONLY
        disable_duet: bool = False,
        disable_comment: bool = False,
        disable_stitch: bool = False,
        brand_content_toggle: bool = False,
        brand_organic_toggle: bool = False,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Upload vertical 9:16 video to TikTok with Direct Post API v2 or simulation.
        Supports live progress tracking and chunked upload.
        """
        video_file = Path(file_path).resolve()
        if not video_file.exists():
            raise FileNotFoundError(f"Không tìm thấy file video: {file_path}")

        file_size = os.path.getsize(video_file)
        total_mb = file_size / (1024 * 1024)
        clean_title = title.strip()

        # In Demo Mode: Simulate realistic upload steps
        if cls.is_demo_mode():
            logger.info(f"[TIKTOK DEMO] Simulating Direct Post upload for: '{clean_title}' ({total_mb:.1f} MB)...")
            simulated_steps = [
                (0.12, "Đang khởi tạo kết nối TikTok Direct Post API (Kênh Test)..."),
                (0.35, f"Đang truyền tải video chunks lên máy chủ TikTok: 35% ({total_mb*0.35:.1f}/{total_mb:.1f} MB)..."),
                (0.68, f"Đang truyền tải video chunks lên máy chủ TikTok: 68% ({total_mb*0.68:.1f}/{total_mb:.1f} MB)..."),
                (0.90, "TikTok đang xử lý định dạng 9:16 và kiểm tra âm thanh bản quyền (90%)..."),
                (1.00, "Đã xuất bản video lên TikTok thành công (100%)!")
            ]
            for prog, msg in simulated_steps:
                if progress_callback:
                    try:
                        progress_callback(prog, msg)
                    except Exception:
                        pass
                time.sleep(1.0)

            post_id = f"74{uuid.uuid4().int % 10000000000000000:016d}"
            video_url = f"https://www.tiktok.com/@minhphong2311/video/{post_id}"
            return {
                "success": True,
                "post_id": post_id,
                "video_url": video_url,
                "title": clean_title,
                "privacy_level": privacy_level,
                "is_demo": True
            }

        # Real Mode: TikTok Content Posting API v2
        token_info = cls.get_token()
        if not token_info or not token_info.get("access_token"):
            raise RuntimeError("Chưa kết nối tài khoản TikTok hoặc token đã hết hạn.")

        access_token = token_info["access_token"]

        if progress_callback:
            try:
                progress_callback(0.08, "Đang khởi tạo phiên upload với TikTok Direct Post API...")
            except Exception:
                pass

        # 1. Initialize Direct Post video upload
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8"
        }

        init_payload = {
            "post_info": {
                "title": clean_title[:2200],
                "privacy_level": privacy_level,
                "disable_duet": disable_duet,
                "disable_comment": disable_comment,
                "disable_stitch": disable_stitch,
                "brand_content_toggle": brand_content_toggle,
                "brand_organic_toggle": brand_organic_toggle
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": min(file_size, 10 * 1024 * 1024),
                "total_chunk_count": (file_size + (10 * 1024 * 1024 - 1)) // (10 * 1024 * 1024)
            }
        }

        is_inbox_mode = False
        init_res = requests.post(cls.PUBLISH_INIT_ENDPOINT, headers=headers, json=init_payload, timeout=30)
        init_data = init_res.json()

        if init_data.get("error") and "unaudited_client_can_only_post_to_private_accounts" in str(init_data):
            logger.info("TikTok Sandbox unaudited client: switching automatically to Creator Inbox / Draft upload...")
            if progress_callback:
                try:
                    progress_callback(0.12, "Tài khoản Sandbox đang chuyển sang chế độ tải vào Hộp Thư / Bản Nháp TikTok...")
                except Exception:
                    pass
            is_inbox_mode = True
            inbox_payload = {
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": file_size,
                    "chunk_size": min(file_size, 10 * 1024 * 1024),
                    "total_chunk_count": (file_size + (10 * 1024 * 1024 - 1)) // (10 * 1024 * 1024)
                }
            }
            init_res = requests.post(cls.INBOX_INIT_ENDPOINT, headers=headers, json=inbox_payload, timeout=30)
            init_data = init_res.json()

        err_code = init_data.get("error", {}).get("code") if isinstance(init_data.get("error"), dict) else None
        if (err_code and err_code != "ok") or "data" not in init_data:
            err = init_data.get("error", {}).get("message") or err_code or str(init_data)
            if err_code == "spam_risk_too_many_pending_share" or "spam_risk_too_many_pending_share" in str(init_data):
                raise RuntimeError(
                    "Tài khoản TikTok đang có quá nhiều video chờ duyệt trong Hộp Thư (chính sách giới hạn tối đa 5 video chờ/24h của TikTok). "
                    "Vui lòng mở ứng dụng TikTok trên điện thoại -> vào mục 'Hộp Thư (Inbox)' -> 'Thông Báo Hệ Thống' -> mở các thông báo video chờ để duyệt đăng hoặc xóa nháp để tiếp tục!"
                )
            raise RuntimeError(f"TikTok Publish Init Error: {err}")

        publish_id = init_data["data"].get("publish_id")
        upload_url = init_data["data"].get("upload_url")

        # 2. Upload video binary chunks
        chunk_size = 10 * 1024 * 1024
        with open(video_file, "rb") as vf:
            uploaded_bytes = 0
            while uploaded_bytes < file_size:
                chunk = vf.read(chunk_size)
                if not chunk:
                    break
                chunk_len = len(chunk)
                start_byte = uploaded_bytes
                end_byte = start_byte + chunk_len - 1

                chunk_headers = {
                    "Content-Range": f"bytes {start_byte}-{end_byte}/{file_size}",
                    "Content-Type": "video/mp4"
                }
                upload_res = requests.put(upload_url, data=chunk, headers=chunk_headers, timeout=60)
                if upload_res.status_code not in [200, 201, 206]:
                    raise RuntimeError(f"Lỗi khi gửi chunk video lên TikTok (HTTP {upload_res.status_code})")

                uploaded_bytes += chunk_len
                prog_pct = min(0.92, 0.15 + (uploaded_bytes / file_size) * 0.75)
                up_mb = uploaded_bytes / (1024 * 1024)
                if progress_callback:
                    try:
                        progress_callback(prog_pct, f"Đang tải lên TikTok (9:16): {int(prog_pct*100)}% ({up_mb:.1f}/{total_mb:.1f} MB)")
                    except Exception:
                        pass

        # 3. Poll status_fetch until complete
        logger.info(f"Checking TikTok status for publish_id: {publish_id} (inbox_mode={is_inbox_mode})...")
        for attempt in range(25):
            time.sleep(3)
            status_res = requests.post(
                cls.STATUS_FETCH_ENDPOINT,
                headers=headers,
                json={"publish_id": publish_id},
                timeout=15
            )
            sdata = status_res.json().get("data", {})
            p_status = sdata.get("status")

            if p_status in ["PUBLISH_COMPLETE", "UPLOAD_SUCCESS", "SUCCESS", "SEND_TO_USER_INBOX"]:
                public_id = sdata.get("publicaly_available_post_id", [publish_id])[0] if sdata.get("publicaly_available_post_id") else publish_id
                video_url = f"https://www.tiktok.com/@minhphong2311/video/{public_id}" if not is_inbox_mode else "https://www.tiktok.com"
                msg_done = "Đã xuất bản video lên TikTok thành công!" if not is_inbox_mode else "Đã gửi video vào Hộp Thư / Bản Nháp tài khoản TikTok thành công!"
                if progress_callback:
                    try:
                        progress_callback(1.0, msg_done)
                    except Exception:
                        pass
                return {
                    "success": True,
                    "publish_id": publish_id,
                    "post_id": public_id,
                    "video_url": video_url,
                    "title": clean_title,
                    "privacy_level": privacy_level,
                    "is_inbox": is_inbox_mode,
                    "is_demo": False
                }
            elif p_status == "FAILED":
                fail_reason = sdata.get("fail_reason", "Không rõ nguyên nhân")
                raise RuntimeError(f"TikTok đăng bài thất bại: {fail_reason}")

        # Fallback if processing takes longer in queue
        fallback_url = "https://www.tiktok.com"
        return {
            "success": True,
            "publish_id": publish_id,
            "video_url": fallback_url,
            "title": clean_title,
            "privacy_level": privacy_level,
            "is_inbox": is_inbox_mode,
            "is_demo": False
        }
