from pathlib import Path
from starlette.templating import Jinja2Templates
from app.core.version import get_app_version, get_git_commit_count

templates_dir = str(Path(__file__).resolve().parent.parent.parent / "templates")
templates = Jinja2Templates(directory=templates_dir)

def format_duration(seconds: float | int | None) -> str:
    if seconds is None or seconds <= 0:
        return "0s"
    secs = int(round(seconds))
    if secs < 60:
        return f"{seconds:.1f}s" if (isinstance(seconds, float) and seconds != int(seconds)) else f"{secs}s"
    mins = secs // 60
    rem_secs = secs % 60
    if mins < 60:
        return f"{mins}p {rem_secs:02d}s" if rem_secs > 0 else f"{mins} phút"
    hours = mins // 60
    rem_mins = mins % 60
    return f"{hours}h {rem_mins:02d}p {rem_secs:02d}s" if rem_secs > 0 else f"{hours}h {rem_mins:02d}p"

# Register version and helper functions to all Jinja2 templates globally
templates.env.globals["get_app_version"] = get_app_version
templates.env.globals["get_git_commit_count"] = get_git_commit_count
templates.env.globals["app_version"] = get_app_version
templates.env.filters["format_duration"] = format_duration
templates.env.globals["format_duration"] = format_duration
