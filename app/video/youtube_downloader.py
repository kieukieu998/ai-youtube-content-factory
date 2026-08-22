import os
import re
import asyncio
import unicodedata
from pathlib import Path
from typing import Optional
from loguru import logger
from app.core.config import settings

def slugify_filename(title: str, year: Optional[int] = None) -> str:
    """Convert movie title and year to a clean safe filename string e.g. Tro_Choi_Tron_Tim_2019."""
    if not title:
        return "movie"
    nfkd = unicodedata.normalize('NFKD', str(title))
    ascii_text = nfkd.encode('ASCII', 'ignore').decode('ASCII')
    clean = re.sub(r'[^a-zA-Z0-9]+', '_', ascii_text).strip('_')
    if not clean:
        clean = "movie"
    if year:
        clean = f"{clean}_{year}"
    return clean[:70]

class YouTubeTrailerDownloader:
    """Auto-searches and downloads official movie trailers from YouTube using yt-dlp."""
    
    @staticmethod
    def download_trailer(
        query_or_url: str,
        output_dir: str,
        filename_prefix: str = "trailer"
    ) -> Optional[str]:
        """
        Download trailer by YouTube URL or search query (e.g. 'ytsearch1:Inception official trailer').
        Returns the absolute path to the downloaded MP4 file.
        """
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        output_template = str(out_path / f"{filename_prefix}_%(id)s.%(ext)s")
        
        if query_or_url.startswith("http://") or query_or_url.startswith("https://"):
            target = query_or_url
        else:
            target = f"ytsearch1:{query_or_url} official trailer HD"

        import yt_dlp
        
        ydl_opts = {
            'format': 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'max_filesize': 150 * 1024 * 1024, # Max 150MB
        }
        
        logger.info(f"Searching and downloading YouTube trailer for: {target}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target, download=True)
                if 'entries' in info:
                    info = info['entries'][0]
                downloaded_file = ydl.prepare_filename(info)
                if os.path.exists(downloaded_file):
                    logger.info(f"Downloaded trailer successfully: {downloaded_file}")
                    return downloaded_file
        except Exception as e:
            logger.error(f"Failed to download YouTube trailer: {e}")
            
    @staticmethod
    def extract_metadata_fast(query_or_url: str) -> dict:
        """Extract title, duration, description quickly without downloading video."""
        import yt_dlp
        if query_or_url.startswith("http://") or query_or_url.startswith("https://"):
            target = query_or_url
        else:
            target = f"ytsearch1:{query_or_url} official trailer HD"

        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'skip_download': True,
            'noplaylist': True,
            'extract_flat': False
        }
        info_res = {
            "title": "",
            "duration": 0,
            "description": "",
            "id": ""
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target, download=False)
                if 'entries' in info and info['entries']:
                    info = info['entries'][0]
                if info:
                    info_res["title"] = info.get("title", "")
                    info_res["duration"] = int(info.get("duration", 0) / 60) if info.get("duration") else 0
                    info_res["description"] = info.get("description", "")
                    info_res["id"] = info.get("id", "")
        except Exception as e:
            logger.warning(f"Failed to fast-extract YouTube metadata: {e}")
        return info_res

    @staticmethod
    def get_video_info_and_download(
        query_or_url: str,
        output_dir: str,
        filename_prefix: str = "media_yt"
    ) -> dict:
        """
        Download video and extract metadata (title, duration, description) using yt-dlp.
        Returns dict with keys: file_path, title, duration, description.
        """
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        
        output_template = str(out_path / f"{filename_prefix}_%(id)s.%(ext)s")
        
        if query_or_url.startswith("http://") or query_or_url.startswith("https://"):
            target = query_or_url
        else:
            target = f"ytsearch1:{query_or_url} official trailer HD"

        import yt_dlp
        
        ydl_opts = {
            'format': 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
            'merge_output_format': 'mp4',
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'ignoreerrors': True,
        }
        
        info_res = {
            "file_path": None,
            "title": "",
            "duration": 0,
            "description": ""
        }
        
        logger.info(f"Downloading YouTube video and extracting info for: {target}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target, download=True)
                if 'entries' in info and info['entries']:
                    info = info['entries'][0]
                
                if info:
                    info_res["title"] = info.get("title", "")
                    info_res["duration"] = int(info.get("duration", 0) / 60) if info.get("duration") else 0
                    info_res["description"] = info.get("description", "")
                    
                    downloaded_file = ydl.prepare_filename(info)
                    if not os.path.exists(downloaded_file):
                        # check mp4 variant
                        mp4_candidate = str(Path(downloaded_file).with_suffix(".mp4"))
                        if os.path.exists(mp4_candidate):
                            downloaded_file = mp4_candidate
                            
                    if os.path.exists(downloaded_file):
                        info_res["file_path"] = downloaded_file
                        logger.info(f"Downloaded video successfully: {downloaded_file}")
        except Exception as e:
            logger.error(f"Failed to download video from YouTube: {e}")
            
        if not info_res["file_path"]:
            matching = list(out_path.glob(f"{filename_prefix}_*.mp4"))
            if matching:
                info_res["file_path"] = str(matching[-1])
                
        return info_res
