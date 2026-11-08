"""학년도 자료 백업·복원. 데이터 폴더/백업/YYYY-MM-DD_HHMMSS[_사유]/*.sqlite"""
import datetime as dt
import shutil

from . import db
from .paths import backup_dir, data_dir

KEEP = 7


def _stamp(reason=""):
    s = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return f"{s}_{reason}" if reason else s


def make(reason="") -> str:
    """열려 있는 연결은 SQLite backup API로, 나머지 파일은 그대로 복사한다."""
    years = db.list_years()
    if not years:
        return ""
    dest = backup_dir() / _stamp(reason)
    dest.mkdir(parents=True, exist_ok=True)
    for y in years:
        db.open_year(y).backup_to(dest / db.year_path(y).name)
    prune()
    return dest.name


def prune(keep=KEEP):
    dirs = sorted([p for p in backup_dir().iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    for p in dirs[keep:]:
        shutil.rmtree(p, ignore_errors=True)


def daily(last: str) -> str:
    """오늘 백업이 없으면 만든다. 반환: 오늘 날짜(설정에 저장용)."""
    today = dt.date.today().isoformat()
    if last != today:
        make()
    return today


def list_backups() -> list[dict]:
    out = []
    for p in sorted(backup_dir().iterdir(), key=lambda p: p.name, reverse=True):
        if p.is_dir():
            files = sorted(f.name for f in p.glob("*.sqlite"))
            if files:
                out.append({"name": p.name, "files": files})
    return out


def restore(name: str) -> dict:
    src = backup_dir() / name
    if not src.is_dir() or src.parent != backup_dir() or "/" in name or "\\" in name:
        raise db.DbError("백업을 찾지 못했습니다.")
    files = list(src.glob("*.sqlite"))
    if not files:
        raise db.DbError("백업에 자료 파일이 없습니다.")
    safety = make("복원전")  # 지금 상태를 먼저 남긴다
    db.close_all()
    for f in files:
        target = data_dir() / f.name
        for suffix in ("-wal", "-shm"):
            side = target.with_name(target.name + suffix)
            if side.exists():
                side.unlink()
        shutil.copy2(f, target)
    return {"restored": [f.name for f in files], "safety": safety}
