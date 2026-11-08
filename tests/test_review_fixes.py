"""Codex 최종 검토(docs/review/codex_final_review.md)에서 재현된 문제의 회귀 시험."""
import os, sys, tempfile, threading, time
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import backup, config, db, export, ocr, openrouter, scan, updater, weights
from app.api import Api
from app.inbox import match_one

HERE = os.path.dirname(__file__)
PDF = os.path.join(HERE, "fixtures", "scan_sample.pdf")
SENT = []
GATE = threading.Event(); GATE.set()


def fake_chat(key, model, system, user, privacy_block=False):
    GATE.wait(10)
    SENT.append(user)
    return "결과 " + user[:10], 0.0


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0


class W:
    def create_file_dialog(self, *a, **k): return (PDF,)
    def evaluate_js(self, js): pass


def ok(r):
    assert r.get("ok"), r
    return r


def setup():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "clova_url": "https://x", "clova_secret": "s"})
    api = Api(); api.attach(W())
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김철수\n20302\t이영희\n20303\t박민수")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    return api, hr


def wait_idle(api):
    for _ in range(200):
        if not api._busy.locked():
            return
        time.sleep(0.05)


def test_h01_h02_h03_h04(api, hr):
    # H01: 두 번째 페이지 머리글도 지움
    texts = ["학번 20301 이름 김철수\n" + "\n".join(f"본문 {i}" for i in range(10)), "학번 20301 이름 김철수\n뒷면 본문"]
    ocr.ocr_pdf = lambda *a, **k: list(texts)
    bid = ok(api.inbox_create("양면", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid)); ok(api.inbox_scan_ocr(bid, 2)); wait_idle(api)
    g = ok(api.inbox_scan_groups(bid, [0], []))["groups"][0]
    assert "20301" not in g["content"] and "김철수" not in g["content"] and "뒷면 본문" in g["content"], g["content"]
    # H02: 학년도마다 따로
    p26 = scan.pdf_path(2026, bid); assert p26.exists()
    # H03: 백업에 스캔 원본 포함, 묶음 지운 뒤 복원하면 PDF도 돌아옴
    name = ok(api.backup_now())["name"]
    assert (backup.backup_dir() / name / "스캔" / "2026" / p26.name).exists()
    ok(api.inbox_delete(bid)); assert not p26.exists()
    ok(api.restore_backup(name)); assert p26.exists()
    # H04: 백업 7개 중 가장 오래된 것도 복원됨(복원 전 백업이 지우지 않음)
    for _ in range(7):
        api.backup_now()
    oldest = sorted(b["name"] for b in ok(api.backups())["backups"])[0]
    ok(api.restore_backup(oldest))
    # M05: 학번만 맞으면 추천
    assert match_one("20301", "", [{"student_no": "20301", "name": "김철수", "active": 1}])[1] == "suggested"


def test_h05_h06(api, hr):
    r1 = ok(api.add_record(hr, "career", "20302", {"content": "가\n\n나"}))["id"]
    ok(api.ai_record(r1))  # 후보 하나
    ok(api.move_records([{"record_id": r1, "paras": None}], hr, "autonomy"))
    moved = ok(api.student_view(hr, "autonomy", "20302"))["records"][-1]
    ok(api.update_record(moved["id"], {"content": "고친 내용"}))
    e = api.undo_move(); assert not e["ok"] and "고치거나" in e["error"]  # H06: 이후 수정 있으면 막음
    # 후보 복원 확인
    r2 = ok(api.add_record(hr, "career", "20302", {"content": "다"}))["id"]
    ok(api.ai_record(r2))
    ok(api.move_records([{"record_id": r2, "paras": None}], hr, "behavior"))
    ok(api.undo_move())
    back = [r for r in ok(api.student_view(hr, "career", "20302"))["records"] if r["id"] == r2][0]
    assert len(back["candidates"]) == 1
    # H05: 학년도가 바뀌면 되돌리기 안 됨
    r3 = ok(api.add_record(hr, "career", "20302", {"content": "라"}))["id"]
    ok(api.move_records([{"record_id": r3, "paras": None}], hr, "behavior"))
    u = api._last_undo
    ok(api.create_year(2027, "homeroom"))
    assert api._last_undo is None
    api._last_undo = u
    e = api.undo_move(); assert not e["ok"] and "학년도" in e["error"]
    ok(api.delete_year(2027, "2027학년도"))  # 2026이 다시 최신 학년도
    assert api.year_state()["year"] == 2026 and not api.year_state()["archived"]


def test_h07_h11(api, hr):
    # H07: 동시에 두 번 보내도 한 번만
    b = ok(api.inbox_create("동시", hr, "career"))["id"]
    s = ok(api.inbox_source_text(b, "20303\t박민수\t내용"))
    ok(api.inbox_import(b, {"structure": "multi", **s["opts"]})); ok(api.inbox_stage(b, "review"))
    res = []
    ts = [threading.Thread(target=lambda: res.append(api.inbox_send(b))) for _ in range(2)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sum(1 for r in res if r["ok"]) == 1
    assert len([r for r in ok(api.student_view(hr, "career", "20303"))["records"] if r["source"] == f"inbox:{b}"]) == 1
    # H11: AI를 기다리는 동안 마감되면 결과를 저장하지 않음, 작업 중 복원·학년도 전환 막음
    rid = ok(api.add_record(hr, "behavior", "20301", {"content": "행특 기록"}))["id"]
    GATE.clear()
    out = []
    t = threading.Thread(target=lambda: out.append(api.ai_record(rid))); t.start(); time.sleep(0.2)
    assert not api.switch_year(2027)["ok"] and not api.restore_backup("x")["ok"]
    ok(api.adopt_record(rid)); ok(api.set_closed(hr, "behavior", "20301", True))
    GATE.set(); t.join()
    assert not out[0]["ok"] and "마감" in out[0]["error"]
    ok(api.job_begin()); assert not api.delete_year(2027, "2027학년도")["ok"]; ok(api.job_end())


def test_h13_m06_l02():
    try:
        updater.download({"url": f"https://github.com/{updater.GITHUB_REPO}/releases/download/v9/SGB-Juicer.exe", "sha256": ""}); raise AssertionError
    except updater.UpdateError as e:
        assert "SHA-256" in str(e)
    p = os.path.join(os.environ["SGB_DATA_DIR"], "f.xlsx")
    export.write_xlsx(p, [{"student_no": "1", "name": "가", "closed": True, "text": "=1+1", "bytes": 4}], "full", "t")
    from openpyxl import load_workbook
    assert load_workbook(p).active["D2"].data_type == "s"
    try:
        export.write_xlsx(p, [{"student_no": "1", "name": "가", "closed": True, "text": "가" * 33000, "bytes": 1}], "full", "t"); raise AssertionError
    except ValueError:
        pass
    for bad in ("nan", "inf"):
        try:
            weights.compute([{"bytes": 1, "weight": bad}], False); raise AssertionError
        except weights.WeightError:
            pass


def test_m01_m02_m03_m04(api, hr):
    # M01: 보관 학년도 쓰기 막기(2027이 있으니 2026은 보관)
    assert api.year_state()["archived"]
    for r in (api.add_schedule("2026-12-01", "x"), api.update_group(hr, {"grade": 2, "class_no": 4}), api.set_role("subject"), api.create_year(2026, "subject")):
        assert not r["ok"], r
    ok(api.switch_year(2027)); ok(api.delete_year(2027, "2027학년도")); ok(api.switch_year(2026))
    # M02: 후보만 있는 학생은 명렬에서 빠지지 않고 비활성
    sub = ok(api.add_group({"kind": "subject", "name": "수학", "semester": 1}))["id"]
    p = api.roster_from_text("20301\t김철수\n20302\t이영희")
    ok(api.roster_apply(sub, api.roster_build(sub, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.standards_save(sub, "[기준] 내용"))
    ok(api.ai_standards_only(sub, "subject", "20302", {"text": "[기준] 내용", "level": "B"}))
    p2 = api.roster_from_text("20301\t김철수")
    res = ok(api.roster_apply(sub, api.roster_build(sub, p2["raw"], p2["header"], p2["columns"])["rows"]))
    assert res["deactivated"] == 1 and res["removed"] == 0
    # M03: 담당 삭제 영향·백업·연결 묶음
    b = ok(api.inbox_create("수학 자료", sub, "subject"))["id"]
    im = ok(api.group_impact(sub)); assert im["batches"] == 1 and im["results"] == 1 and im["standards"] == 1
    d = ok(api.delete_group(sub)); assert d["backup"]
    assert not any(x["id"] == b for x in ok(api.inbox_list())["batches"])
    # M04: 인박스에서 쓰던 태그를 지워도 보낼 수 있음
    tag = ok(api.add_tag("임시"))["id"]
    b2 = ok(api.inbox_create("태그", hr, "career"))["id"]
    s = ok(api.inbox_source_text(b2, "20301\t김철수\t태그 시험"))
    ok(api.inbox_import(b2, {"structure": "multi", **s["opts"]})); ok(api.inbox_update(b2, {"tag_ids": [tag]}))
    assert [t for t in ok(api.tags())["tags"] if t["id"] == tag][0]["used_inbox"] == 1
    ok(api.delete_tag(tag)); ok(api.inbox_stage(b2, "review")); ok(api.inbox_send(b2))
    # M05: 보낸 스캔 묶음은 다시 묶을 수 없음
    assert not api.inbox_scan_confirm(b2, [0], [])["ok"]


def test_single_instance():
    import subprocess
    from app import single
    assert single.acquire()
    r = subprocess.run([sys.executable, "-c", "import sys;sys.path.insert(0,'.');from app import single;print(single.acquire())"],
                       capture_output=True, text=True, env=os.environ, cwd=os.path.dirname(HERE))
    assert r.stdout.strip() == "False", r.stdout + r.stderr


if __name__ == "__main__":
    api, hr = setup()
    test_h01_h02_h03_h04(api, hr)
    test_h05_h06(api, hr)
    test_h07_h11(api, hr)
    test_h13_m06_l02()
    ok(api.create_year(2027, "homeroom")); ok(api.switch_year(2026))
    test_m01_m02_m03_m04(api, hr)
    test_single_instance()
    print("REVIEW FIXES OK")
