"""백업 중 꺼짐·닫기(사용자 지정 2026-11-24): 복사로 게시하다 멈춘 폴더는 목록에 안 보이고 정리되며, 백업 중 창 닫기는 끝날 때까지 기다린다."""
import os
import sys
import tempfile
import time

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import backup  # noqa: E402
from app.api import Api  # noqa: E402
from app.paths import backup_dir  # noqa: E402


class W:
    x = y = 0
    width, height = 1200, 800

    def __init__(self):
        self.js = []

    def evaluate_js(self, js):
        self.js.append(js)

    def destroy(self):
        pass


def ok(r):
    assert r.get("ok"), r
    return r


def test_publish_marker():
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    name = backup.make("수동")
    assert any(b["name"] == name and not b["legacy"] for b in backup.list_backups())
    # 이름 바꾸기가 계속 막혀 복사로 게시: 표시 없이 끝나야 함
    from pathlib import Path
    real = Path.rename
    Path.rename = lambda self, t: (_ for _ in ()).throw(OSError("액세스 거부"))
    sleep = backup.time.sleep
    backup.time.sleep = lambda s: None  # 다시 시도 기다림은 건너뜀
    try:
        n2 = backup.make("복사게시")
    finally:
        Path.rename = real
        backup.time.sleep = sleep
    d2 = backup_dir() / n2
    assert (d2 / backup.DONE).exists() and not (d2 / backup.PUBLISHING).exists()
    assert any(b["name"] == n2 and not b["legacy"] for b in backup.list_backups())
    # 복사 도중 꺼진 폴더(표시가 남음): 목록에 안 보이고, 1시간 지나면 정리
    half = backup_dir() / "2026-01-01_000000_복사중꺼짐"
    half.mkdir()
    (half / backup.PUBLISHING).write_text("ok", encoding="utf-8")
    (half / "2026학년도.sqlite").write_bytes(b"half")
    assert all(b["name"] != half.name for b in backup.list_backups())
    backup.prune()
    assert half.exists()  # 아직 1시간 전
    old = time.time() - 7200
    os.utime(half / backup.PUBLISHING, (old, old))
    backup.prune()
    assert not half.exists()


def test_close_waits_for_backup():
    api = Api()
    w = W()
    api.attach(w)
    seen = []
    real = backup._make
    backup._make = lambda reason, protect: (seen.append(backup.busy()), real(reason, protect))[1]
    try:
        backup.make("수동")
    finally:
        backup._make = real
    assert seen == [True] and not backup.busy()
    # 백업 중 닫기 → 안내하고 기다림(닫지 않음), 끝나면 평소 닫기(__beforeClose)
    backup._busy += 1
    try:
        assert api.on_closing() is False
        assert any('"notice"' in j for j in w.js)
        assert api.on_closing() is False  # 다시 눌러도 백업 중이면 기다림
        time.sleep(0.5)
        assert not any("__beforeClose" in j for j in w.js)
    finally:
        backup._busy -= 1
    for _ in range(50):
        if any("__beforeClose" in j for j in w.js):
            break
        time.sleep(0.1)
    assert any("__beforeClose" in j for j in w.js)


if __name__ == "__main__":
    test_publish_marker()
    test_close_waits_for_backup()
    print("BACKUP SAFETY OK")
