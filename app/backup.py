"""학년도 자료 백업·복원. 데이터 폴더/백업/YYYY-MM-DD_HHMMSS[_사유]/
  - 2026학년도.sqlite …  (열린 연결은 SQLite backup API로 일관된 사본)
  - 스캔/2026/batch_1.pdf … (스캔 원본도 같은 시점으로)

복원은 고른 백업을 지우지 않게 보호하고, 모든 파일을 임시로 준비한 뒤 한꺼번에 바꾼다.
"""
import datetime as dt
import shutil
import sqlite3

from . import db
from .paths import backup_dir, data_dir

KEEP = 7


def _new_dir(reason=""):
    base = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S") + (f"_{reason}" if reason else "")
    name, n = base, 2
    while (backup_dir() / name).exists():
        name = f"{base}_{n}"
        n += 1
    d = backup_dir() / name
    d.mkdir(parents=True)
    return d


def make(reason="", protect=()) -> str:
    years = db.list_years()
    if not years:
        return ""
    dest = _new_dir(reason)
    for y in years:
        db.open_year(y).backup_to(dest / db.year_path(y).name)
        src = data_dir() / "스캔" / str(y)
        if src.is_dir() and any(src.iterdir()):
            shutil.copytree(src, dest / "스캔" / str(y))
    (dest / "완료").write_text("ok", encoding="utf-8")  # 다 만들어진 백업 표시
    prune(protect={dest.name, *protect})
    return dest.name


def prune(keep=KEEP, protect=()):
    dirs = sorted([p for p in backup_dir().iterdir() if p.is_dir()], key=lambda p: p.name, reverse=True)
    for p in dirs[keep:]:
        if p.name not in protect:
            shutil.rmtree(p, ignore_errors=True)


def daily(last: str) -> str:
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
                scans = sum(1 for _ in (p / "스캔").rglob("*.pdf")) if (p / "스캔").is_dir() else 0
                out.append({"name": p.name, "files": files, "scans": scans})
    return out


def _check_sqlite(path):
    con = sqlite3.connect(path)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise db.DbError(f"백업 파일이 손상되었습니다: {path.name}")
    finally:
        con.close()


def restore(name: str) -> dict:
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise db.DbError("백업을 찾지 못했습니다.")
    src = backup_dir() / name
    if not src.is_dir():
        raise db.DbError("백업을 찾지 못했습니다.")
    files = sorted(src.glob("*.sqlite"))
    if not files:
        raise db.DbError("백업에 자료 파일이 없습니다.")
    for f in files:
        if not db.re.match(r"^\d{4}학년도\.sqlite$", f.name):
            raise db.DbError(f"알 수 없는 파일이 있습니다: {f.name}")
        _check_sqlite(f)
    # 1) 지금 상태를 먼저 남긴다(고른 백업은 정리 대상에서 보호)
    safety = make("복원전", protect={name})
    # 2) 새 파일을 임시 이름으로 모두 준비
    stage = data_dir() / ".복원준비"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    try:
        for f in files:
            shutil.copy2(f, stage / f.name)
        if (src / "스캔").is_dir():
            shutil.copytree(src / "스캔", stage / "스캔")
    except OSError as e:
        shutil.rmtree(stage, ignore_errors=True)
        raise db.DbError(f"복원 파일을 준비하지 못했습니다: {e}") from e
    # 3) 연결을 닫고 한꺼번에 바꾼다
    db.close_all()
    for f in files:
        target = data_dir() / f.name
        for suffix in ("-wal", "-shm"):
            side = target.with_name(target.name + suffix)
            if side.exists():
                side.unlink()
        shutil.move(str(stage / f.name), str(target))  # 같은 폴더 안 이동(교체)
        year = f.name[:4]
        cur = data_dir() / "스캔" / year
        shutil.rmtree(cur, ignore_errors=True)
        if (stage / "스캔" / year).is_dir():
            cur.parent.mkdir(exist_ok=True)
            shutil.move(str(stage / "스캔" / year), str(cur))
    shutil.rmtree(stage, ignore_errors=True)
    return {"restored": [f.name for f in files], "safety": safety}


def delete_year_files(year: int):
    """학년도 자료 삭제: DB와 그 학년도 스캔 원본을 함께 지운다(백업은 남김)."""
    p = db.year_path(year)
    for f in (p, p.with_name(p.name + "-wal"), p.with_name(p.name + "-shm")):
        if f.exists():
            f.unlink()
    shutil.rmtree(data_dir() / "스캔" / str(int(year)), ignore_errors=True)
