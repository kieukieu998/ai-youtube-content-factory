import subprocess
from pathlib import Path
from functools import lru_cache

def get_git_commit_count() -> int:
    """
    Get the total number of commits in the git repository.
    Returns 0 if not a git repository or no commits yet.
    """
    try:
        repo_dir = str(Path(__file__).resolve().parent.parent.parent)
        res = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=repo_dir,
            timeout=2.0
        )
        if res.returncode == 0 and res.stdout.strip().isdigit():
            return int(res.stdout.strip())
    except Exception:
        pass
    return 0

def get_app_version() -> str:
    """
    Calculates semantic version based on user rules:
    - Base: 1.0.0 (0 commits)
    - 1 commit -> 1.0.1
    - 100 commits -> 1.1.0
    - 1000 commits (when middle digit reaches 10) -> 2.0.0
    
    Formula:
    major = 1 + (commits // 1000)
    minor = (commits // 100) % 10
    patch = commits % 100
    """
    commits = get_git_commit_count()
    major = 1 + (commits // 1000)
    minor = (commits // 100) % 10
    patch = commits % 100
    return f"{major}.{minor}.{patch}"
