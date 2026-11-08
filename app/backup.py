"""학년도 자료 백업·복원. 데이터 폴더/백업/YYYY-MM-DD_HHMMSS[_사유]/
  - 2026학년도.sqlite …  (열린 연결은 SQLite backup API로 일관된 사본)
  - 스캔/2026/batch_1.pdf … (스캔 원본도 같은 시점으로)

백업은 임시 폴더에 다 만든 뒤 게시한다(실패한 백업은 목록에 안 보임).
복원은 고른 백업을 지우지 않게 보호하고, 새 파일을 준비한 뒤 지금 파일을 옆으로 옮겨 두고 바꾼다.
도중에 실패하거나 앱이 꺼지면 원래 파일로 되돌린다.
"""
import datetime as dt
import shutil
import sqlite3

from . import db
from .paths import backup_dir, data_dir

KEEP = 7


DONE = "완료"
STAGE = ".복원준비"
PREV = ".복원이전"
JOURNAL = ".복원중"


def _new_name(reason=""):
    base = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S") + (f"_{reason}" if reason else "")
    name, n = base, 2
    while (backup_dir() / name).exists():
        name = f"{base}_{n}"
        n += 1
    return name


def make(reason="", protect=()) -> str:
    """임시 폴더에 다 만든 뒤 이름을 바꿔 게시한다. 도중에 실패하면 목록에 남지 않는다."""
    years = db.list_years()
    if not years:
        return ""
    name = _new_name(reason)
    tmp = backup_dir() / f".작성중_{name}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    try:
        for y in years:
            db.open_year(y).backup_to(tmp / db.year_path(y).name)
            src = data_dir() / "스캔" / str(y)
            if src.is_dir() and any(src.iterdir()):
                shutil.copytree(src, tmp / "스캔" / str(y))
        (tmp / DONE).write_text("ok", encoding="utf-8")  # 다 만들어진 백업 표시
        tmp.rename(backup_dir() / name)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    prune(protect={name, *protect})
    return name


def _dirs():
    """게시된 백업 폴더(점으로 시작하는 작성 중 폴더 제외)."""
    return [p for p in backup_dir().iterdir() if p.is_dir() and not p.name.startswith(".")]


def prune(keep=KEEP, protect=()):
    for p in backup_dir().iterdir():  # 오래 남은 작성 중 폴더 정리
        if p.is_dir() and p.name.startswith(".작성중_") and p.name[len(".작성중_"):] not in protect:
            try:
                if dt.datetime.now().timestamp() - p.stat().st_mtime > 3600:
                    shutil.rmtree(p, ignore_errors=True)
            except OSError:
                pass
    dirs = sorted(_dirs(), key=lambda p: p.name, reverse=True)
    for p in dirs[keep:]:
        if p.name not in protect:
            shutil.rmtree(p, ignore_errors=True)


def daily(last: str) -> str:
    today = dt.date.today().isoformat()
    if last != today:
        make()
    return today


def list_backups() -> list[dict]:
    """legacy: 완료 표시가 없는 백업(v0.7 이전 형식이거나 v0.8에서 만들다 실패한 것).
    스캔 원본이 빠졌을 수 있어 복원할 때 지금 스캔 원본을 그대로 둔다."""
    out = []
    for p in sorted(_dirs(), key=lambda p: p.name, reverse=True):
        files = sorted(f.name for f in p.glob("*.sqlite"))
        if files:
            scans = sum(1 for _ in (p / "스캔").rglob("*.pdf")) if (p / "스캔").is_dir() else 0
            out.append({"name": p.name, "files": files, "scans": scans, "legacy": not (p / DONE).exists()})
    return out


def _check_sqlite(path):
    con = sqlite3.connect(path)
    try:
        if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise db.DbError(f"백업 파일이 손상되었습니다: {path.name}")
    finally:
        con.close()


def _remove(path):
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _rollback(saved, placed):
    """교체 도중 실패: 새로 놓은 것을 치우고 옮겨 둔 원래 파일을 제자리로."""
    errors = []
    for target in reversed(placed):
        try:
            _remove(target)
        except OSError as e:
            errors.append(f"{target.name}: {e}")
    for target, prev in reversed(saved):
        try:
            _remove(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(prev), str(target))
        except OSError as e:
            errors.append(f"{target.name}: {e}")
    return errors


def recover_interrupted() -> bool:
    """복원 도중 앱이 꺼졌으면(.복원중 표시가 남음) 복원 전 상태로 되돌린다. 앱 시작 때 부른다."""
    root = data_dir()
    journal, prev = root / JOURNAL, root / PREV
    if not journal.exists():
        return False
    db.close_all()
    saved = []
    if prev.is_dir():
        for f in prev.glob("*.sqlite*"):
            saved.append((root / f.name, f))
        if (prev / "스캔").is_dir():
            for d in (prev / "스캔").iterdir():
                saved.append((root / "스캔" / d.name, d))
    errors = _rollback(saved, [])
    if not errors:
        journal.unlink()
        shutil.rmtree(prev, ignore_errors=True)
        shutil.rmtree(root / STAGE, ignore_errors=True)
    return True


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
    legacy = not (src / DONE).exists()  # 스캔 원본이 빠졌을 수 있는 백업: 지금 스캔 원본은 건드리지 않는다
    root = data_dir()
    # 1) 지금 상태를 먼저 남긴다(고른 백업은 정리 대상에서 보호)
    safety = make("복원전", protect={name})
    # 2) 새 파일을 임시 이름으로 모두 준비
    stage, prev, journal = root / STAGE, root / PREV, root / JOURNAL
    shutil.rmtree(stage, ignore_errors=True)
    shutil.rmtree(prev, ignore_errors=True)
    stage.mkdir()
    try:
        for f in files:
            shutil.copy2(f, stage / f.name)
        if not legacy and (src / "스캔").is_dir():
            shutil.copytree(src / "스캔", stage / "스캔")
    except OSError as e:
        shutil.rmtree(stage, ignore_errors=True)
        raise db.DbError(f"복원 파일을 준비하지 못했습니다: {e}") from e
    # 3) 연결을 닫고, 지금 파일을 옆으로 옮겨 둔 뒤 바꾼다. 도중에 실패하면 전부 되돌린다.
    db.close_all()
    prev.mkdir()
    journal.write_text(name, encoding="utf-8")
    saved, placed = [], []
    try:
        for f in files:
            target = root / f.name
            for t in (target, target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
                if t.exists():
                    shutil.move(str(t), str(prev / t.name))
                    saved.append((t, prev / t.name))
            shutil.move(str(stage / f.name), str(target))
            placed.append(target)
            if legacy:
                continue
            year = f.name[:4]
            cur = root / "스캔" / year
            if cur.exists():
                (prev / "스캔").mkdir(exist_ok=True)
                shutil.move(str(cur), str(prev / "스캔" / year))
                saved.append((cur, prev / "스캔" / year))
            if (stage / "스캔" / year).is_dir():
                cur.parent.mkdir(exist_ok=True)
                shutil.move(str(stage / "스캔" / year), str(cur))
                placed.append(cur)
    except BaseException as e:
        errors = _rollback(saved, placed)
        if not errors:
            journal.unlink()
            shutil.rmtree(prev, ignore_errors=True)
        shutil.rmtree(stage, ignore_errors=True)
        if errors:
            raise db.DbError(f"복원 중 오류가 나서 되돌리다가 일부를 못 되돌렸습니다. 앱을 다시 켜면 다시 되돌립니다. ({e})") from e
        raise db.DbError(f"복원 중 오류가 나서 원래 자료로 되돌렸습니다: {e}") from e
    journal.unlink()
    shutil.rmtree(prev, ignore_errors=True)
    shutil.rmtree(stage, ignore_errors=True)
    return {"restored": [f.name for f in files], "safety": safety, "legacy": legacy}


def delete_year_files(year: int):
    """학년도 자료 삭제: DB와 그 학년도 스캔 원본을 함께 지운다(백업은 남김)."""
    p = db.year_path(year)
    for f in (p, p.with_name(p.name + "-wal"), p.with_name(p.name + "-shm")):
        if f.exists():
            f.unlink()
    shutil.rmtree(data_dir() / "스캔" / str(int(year)), ignore_errors=True)
