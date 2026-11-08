"""Codex 재검토(docs/review/codex_recheck.md) N02~N08 백엔드 회귀 시험."""
import os, shutil, sys, tempfile, threading, time
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import backup, config, db, openrouter, single, updater
from app.api import Api
from app.paths import backup_dir, data_dir

HERE = os.path.dirname(__file__)
GATE = threading.Event(); GATE.set()


def fake_chat(key, model, system, user, privacy_block=False):
    GATE.wait(10)
    return "결과 " + user[:10], 0.0


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0


class W:
    def create_file_dialog(self, *a, **k): return ()
    def evaluate_js(self, js): pass
    def destroy(self): pass


def ok(r):
    assert r.get("ok"), r
    return r


def setup():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api(); api.attach(W())
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김철수\n20302\t이영희")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    return api, hr


def final_text(api, hr, sno="20301", item="career"):
    f = ok(api.student_view(hr, item, sno))["final"]
    return f["text"] if f else None


def test_n02_year(api, hr):
    ok(api.edit_final(hr, "career", "20301", "2026 글", 2026))
    e = api.edit_final(hr, "career", "20301", "다른 학년도 글", 2027)
    assert not e["ok"] and "학년도" in e["error"], e
    assert final_text(api, hr) == "2026 글"
    e = api.standards_save(hr, "x", None, 2025)
    assert not e["ok"] and "학년도" in e["error"], e


def test_n04_failed_backup_hidden(api, hr):
    os.makedirs(data_dir() / "스캔" / "2026", exist_ok=True)
    (data_dir() / "스캔" / "2026" / "batch_99.pdf").write_bytes(b"%PDF-1.4 fake")
    before = {b["name"] for b in ok(api.backups())["backups"]}
    real = shutil.copytree
    backup.shutil.copytree = lambda *a, **k: (_ for _ in ()).throw(OSError("주입한 실패"))
    try:
        assert not api.backup_now()["ok"]
    finally:
        backup.shutil.copytree = real
    after = {b["name"] for b in ok(api.backups())["backups"]}
    assert after == before, after - before
    assert not any(p.name.startswith(".작성중") for p in backup_dir().iterdir())
    # 완료 표시 없는 옛 백업: 목록엔 보이되 legacy, 복원해도 지금 스캔 원본을 지우지 않는다
    name = ok(api.backup_now())["name"]
    os.remove(backup_dir() / name / "완료")
    shutil.rmtree(backup_dir() / name / "스캔")
    assert [b for b in ok(api.backups())["backups"] if b["name"] == name][0]["legacy"]
    assert ok(api.restore_backup(name))["legacy"]
    assert (data_dir() / "스캔" / "2026" / "batch_99.pdf").exists()


def test_n05_restore_rollback(api, hr):
    ok(api.edit_final(hr, "career", "20301", "OLD26"))
    ok(api.create_year(2027, "homeroom"))
    hr27 = ok(api.add_group({"kind": "homeroom", "grade": 3, "class_no": 3}))["id"]
    p = api.roster_from_text("30301\t김철수")
    ok(api.roster_apply(hr27, api.roster_build(hr27, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.edit_final(hr27, "career", "30301", "OLD27"))
    snap = ok(api.backup_now())["name"]
    ok(api.edit_final(hr27, "career", "30301", "NEW27"))
    # 2026은 이제 보관 학년도라 화면으로는 못 고침 → DB에 직접
    with db.open_year(2026).tx() as c:
        c.execute("UPDATE finals SET text='NEW26' WHERE student_no='20301'")
    real, n = shutil.move, [0]

    def flaky(src, dst):
        if str(src).endswith("2027학년도.sqlite") and ".복원준비" in str(src):
            n[0] += 1
            raise OSError("주입한 교체 실패")
        return real(src, dst)
    backup.shutil.move = flaky
    try:
        e = api.restore_backup(snap)
    finally:
        backup.shutil.move = real
    assert not e["ok"] and "되돌렸" in e["error"], e
    assert n[0] == 1
    t26 = db.open_year(2026).q("SELECT text FROM finals WHERE student_no='20301'")[0]["text"]
    t27 = db.open_year(2027).q("SELECT text FROM finals WHERE student_no='30301'")[0]["text"]
    assert (t26, t27) == ("NEW26", "NEW27"), (t26, t27)
    assert not (data_dir() / ".복원이전").exists() and not (data_dir() / ".복원중").exists()
    # 정상 복원은 두 학년도 모두 OLD
    ok(api.restore_backup(snap))
    t26 = db.open_year(2026).q("SELECT text FROM finals WHERE student_no='20301'")[0]["text"]
    t27 = db.open_year(2027).q("SELECT text FROM finals WHERE student_no='30301'")[0]["text"]
    assert (t26, t27) == ("OLD26", "OLD27"), (t26, t27)
    # 복원 도중 꺼진 상황: 표시가 남아 있으면 다음 실행 때 복원 전 상태로
    db.close_all()
    prev = data_dir() / ".복원이전"; prev.mkdir()
    cur = data_dir() / "2027학년도.sqlite"
    shutil.copy2(cur, prev / cur.name)
    con = __import__("sqlite3").connect(cur); con.execute("UPDATE finals SET text='HALF'"); con.commit(); con.close()
    (data_dir() / ".복원중").write_text(snap, encoding="utf-8")
    assert backup.recover_interrupted()
    assert db.open_year(2027).q("SELECT text FROM finals WHERE student_no='30301'")[0]["text"] == "OLD27"
    assert not (data_dir() / ".복원중").exists()
    return hr27


def test_n06_undo(api, hr):
    r = ok(api.add_record(hr, "career", "20302", {"content": "가\n\n나", "title": "제목"}))["id"]
    ok(api.move_records([{"record_id": r, "paras": [0]}], hr, "autonomy"))
    moved = [x for x in ok(api.student_view(hr, "autonomy", "20302"))["records"] if x["content"] == "가"][0]
    ok(api.update_record(moved["id"], {"title": "바꾼 제목"}))
    e = api.undo_move(); assert not e["ok"] and "고치거나" in e["error"], e
    # 이동한 기록에 새 후보를 만들고 잠그면 되돌리기 막음
    r2 = ok(api.add_record(hr, "career", "20302", {"content": "다"}))["id"]
    ok(api.move_records([{"record_id": r2, "paras": None}], hr, "autonomy"))
    m2 = [x for x in ok(api.student_view(hr, "autonomy", "20302"))["records"] if x["content"] == "다"][0]
    cid = ok(api.ai_record(m2["id"]))["id"]
    ok(api.lock_result(cid, True))
    e = api.undo_move(); assert not e["ok"], e
    assert any(x["id"] == m2["id"] for x in ok(api.student_view(hr, "autonomy", "20302"))["records"])
    # 아무것도 안 바꿨으면 되돌리기 됨
    r3 = ok(api.add_record(hr, "career", "20302", {"content": "라"}))["id"]
    ok(api.move_records([{"record_id": r3, "paras": None}], hr, "autonomy"))
    ok(api.undo_move())


def test_n07_exclusion(api, hr):
    # 관리 작업 중에는 새 AI·쓰기·일괄 작업이 막힘
    api._maint_begin("복원", take_busy=True)
    try:
        assert not api.add_record(hr, "career", "20301", {"content": "x"})["ok"]
        assert not api.job_begin()["ok"]
    finally:
        api._maint_end(take_busy=True)
    rid = ok(api.add_record(hr, "behavior", "20302", {"content": "행특 기록"}))["id"]
    # AI 결과를 저장할 때까지 작업이 살아 있어 학년도 만들기가 막힘
    GATE.clear()
    out = []
    t = threading.Thread(target=lambda: out.append(api.ai_record(rid))); t.start(); time.sleep(0.2)
    assert not api.create_year(2028, "homeroom")["ok"]
    GATE.set(); t.join()
    ok(out[0])
    assert 2028 not in db.list_years()


def test_n08_update_lock(api):
    assert single.acquire()
    api._update_info = {"sha256": "x", "url": "u"}
    real = (updater.can_apply, updater.download, updater.swap_and_launch)
    updater.can_apply = lambda: True
    updater.download = lambda info, prog=None: "new.exe"

    def bad_swap(path, args=(), before_launch=None):
        before_launch()
        raise updater.UpdateError("실행 실패(주입)")
    updater.swap_and_launch = bad_swap
    try:
        ok(api.update_apply())
        for _ in range(100):
            if not api._maint:
                break
            time.sleep(0.05)
        assert not api._maint and not api._halted
    finally:
        updater.can_apply, updater.download, updater.swap_and_launch = real
    import subprocess
    r = subprocess.run([sys.executable, "-c", "import sys;sys.path.insert(0,'.');from app import single;print(single.acquire())"],
                       capture_output=True, text=True, env=os.environ, cwd=os.path.dirname(os.path.abspath(HERE)))
    assert r.stdout.strip() == "False", r.stdout + r.stderr
    ok(api.add_record(*api._t, {"content": "업데이트 실패 뒤에도 쓰기"}))


def test_close_hook():
    js = []

    class CW(W):
        def evaluate_js(self, code): js.append(code)
        def destroy(self): js.append("destroyed")
    a = Api(); a.attach(CW())
    assert a.on_closing() is False  # 첫 닫기: 화면에 남은 저장을 맡기고 멈춤
    time.sleep(0.2)
    assert js and "__beforeClose" in js[0]
    assert a.on_closing() is True  # 화면이 응답하지 않으면 다시 닫을 때 바로 닫힘
    b = Api(); b.attach(CW())
    b.close_app()
    assert js[-1] == "destroyed" and b.on_closing() is True


if __name__ == "__main__":
    api, hr = setup()
    test_n02_year(api, hr)
    test_n06_undo(api, hr)
    test_n07_exclusion(api, hr)
    test_n04_failed_backup_hidden(api, hr)
    hr27 = test_n05_restore_rollback(api, hr)
    api._t = (hr27, "career", "30301")
    test_n08_update_lock(api)
    test_close_hook()
    print("RECHECK FIXES OK")
