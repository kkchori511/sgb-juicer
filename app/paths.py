import os
import sys
from pathlib import Path

DATA_FOLDER = "생기부착즙기_데이터"


def resource_dir() -> Path:
    """번들된 리소스(app/web 등)의 기준 폴더."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """exe가 있는 폴더. 개발 중에는 프로젝트 루트."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """설정·학생 자료를 두는 폴더(exe 옆). 테스트에서는 SGB_DATA_DIR로 바꿀 수 있다."""
    override = os.environ.get("SGB_DATA_DIR")
    d = Path(override) if override else app_dir() / DATA_FOLDER
    d.mkdir(parents=True, exist_ok=True)
    return d


def backup_dir() -> Path:
    d = data_dir() / "백업"
    d.mkdir(parents=True, exist_ok=True)
    return d


def web_dir() -> Path:
    return resource_dir() / "app" / "web"
