from pathlib import Path
from starlette.templating import Jinja2Templates
from app.core.version import get_app_version, get_git_commit_count

templates_dir = str(Path(__file__).resolve().parent.parent.parent / "templates")
templates = Jinja2Templates(directory=templates_dir)

def format_duration(seconds: float | int | None) -> str:
    """Format duration into digital timecode format: MM:SS or H:MM:SS (e.g. 17:51, 01:06, 3:35:36)"""
    if seconds is None or seconds <= 0:
        return "00:00"
    secs = int(round(seconds))
    mins = secs // 60
    rem_secs = secs % 60
    hours = mins // 60
    rem_mins = mins % 60
    
    if hours > 0:
        return f"{hours}:{rem_mins:02d}:{rem_secs:02d}"
    else:
        return f"{rem_mins:02d}:{rem_secs:02d}"

# Register version and helper functions to all Jinja2 templates globally
templates.env.globals["get_app_version"] = get_app_version
templates.env.globals["get_git_commit_count"] = get_git_commit_count
templates.env.globals["app_version"] = get_app_version
templates.env.filters["format_duration"] = format_duration
templates.env.globals["format_duration"] = format_duration
