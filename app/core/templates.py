from pathlib import Path
from starlette.templating import Jinja2Templates
from app.core.version import get_app_version, get_git_commit_count

templates_dir = str(Path(__file__).resolve().parent.parent.parent / "templates")
templates = Jinja2Templates(directory=templates_dir)

# Register version and helper functions to all Jinja2 templates globally
templates.env.globals["get_app_version"] = get_app_version
templates.env.globals["get_git_commit_count"] = get_git_commit_count
templates.env.globals["app_version"] = get_app_version
