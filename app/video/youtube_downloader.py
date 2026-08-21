import os
import asyncio
from pathlib import Path
from typing import Optional
from loguru import logger
from app.core.config import settings

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
            
        # Check if any mp4 matches prefix in folder
        matching = list(out_path.glob(f"{filename_prefix}_*.mp4"))
        if matching:
            return str(matching[-1])
            
        return None
