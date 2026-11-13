"""태그 AI 변환 경계(Codex 검토 C01~C12·U03·U06): 원문 바뀐 뒤 이어 고치기, 학년도 확인, 중지 뒤 늦은 답,
지침 이어받기, 같은 건 동시 호출, 여러 단계 중간 실패 이어 하기, 대상·항목 검사, 지운 태그 이력, 설정 파일, 번호 고정."""
import json, os, sys, tempfile, threading, time
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter

CALLS = []
HOOK = {"fn": None}


def fake_chat(key, model, system, user, privacy_block=False):
    CALLS.append((system, user))
    if HOOK["fn"]:
        HOOK["fn"](system, user)
    return "결과:" + user[:30], 0.01


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0  # 시험에서 잔액 조회 HTTP를 보내지 않음
from app.api import Api  # noqa: E402
from app.tagwork import TagWork, step_system  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def setup():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    names = ["김하나", "이두리", "박세나", "최네모"]
    p = api.roster_from_text("\n".join(f"203{i:02d}\t{n}" for i, n in enumerate(names, 1)))
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.add_tag("봉사"))
    tag = ok(api.tags())["tags"][0]["id"]
    rids = [ok(api.add_record(hr, "autonomy", f"203{i:02d}", {"content": f"봉사 원문{i}", "tag_ids": [tag]}))["id"] for i in range(1, 5)]
    other = ok(api.add_record(hr, "career", "20301", {"content": "진로 기록", "tag_ids": [tag]}))["id"]
    plain = ok(api.add_record(hr, "autonomy", "20302", {"content": "태그 없는 기록"}))["id"]
    return api, hr, tag, rids, other, plain


def chain(p, *reqs, src="original"):
    return {"src": src, "steps": [{"prompt": p, "example": "", "request": ""}] + [{"prompt": "", "example": "", "request": r} for r in reqs]}


def test_edges():
    api, hr, tag, rids, other, plain = setup()
    Y = 2026
    w = ok(api.tag_work(tag, Y))["work"]
    r0 = rids[0]
    # C03: 학년도가 다르면 막음
    assert not api.tag_draft_save(w["id"], {"prompt": "x"}, 2025)["ok"]
    assert not api.tag_trial_run(w["id"], r0, chain("A"), None, None, 2025)["ok"]
    # 태그가 없는 기록은 시험 불가
    assert not api.tag_trial_run(w["id"], plain, chain("A"), None, None, Y)["ok"]
    # C01: 앞 후보를 만든 뒤 원문이 바뀌면 이어 고치기 막음
    c1 = ok(api.tag_trial_run(w["id"], r0, chain("A"), None, None, Y))["id"]
    par = [t for t in ok(api.tag_work(tag, Y))["trials"] if t["id"] == c1][0]
    ok(api.update_record(r0, {"content": "새로 추가한 중요한 관찰 사실"}))
    n = len(CALLS)
    bad = api.tag_trial_run(w["id"], r0, chain("A", "더 짧게"), c1, None, Y)
    assert not bad["ok"] and "바뀌었" in bad["error"] and len(CALLS) == n, bad
    assert ok(api.tag_confirm(c1, True, Y))["applied"]["skipped"][0]["why"] == "결과를 만든 뒤 기록이 바뀜"
    # AI를 기다리는 동안 기록이 바뀌면 후보를 저장하지 않음
    HOOK["fn"] = lambda s, u: api._db()._conn.execute("UPDATE records SET content='도중에 고침' WHERE id=?", (rids[1],))
    assert not api.tag_trial_run(w["id"], rids[1], chain("A"), None, None, Y)["ok"]
    HOOK["fn"] = None
    # C06: 2단계에서 고친 전체 지침이 3단계에도 이어짐
    ch = {"src": "original", "steps": [{"prompt": "지침A", "example": "", "request": ""}, {"prompt": "지침B", "example": "", "request": "r1"},
                                       {"prompt": "", "example": "", "request": "r2"}]}
    assert step_system(ch, 2).startswith("지침B") and "r2" in step_system(ch, 2)
    # C05: 중지 전에 보낸 요청은 새 실행이 중지를 풀어도 버림
    def cancel_then_reset(s, u):
        openrouter.cancel()
        openrouter.reset()
    HOOK["fn"] = cancel_then_reset
    r = api.tag_trial_run(w["id"], rids[2], chain("A"), None, None, Y)
    HOOK["fn"] = None
    assert not r["ok"] and r.get("code") == "cancelled", r
    assert not [t for t in ok(api.tag_work(tag, Y))["trials"] if t["record_id"] == rids[2]]
    # U03: 후보가 밀려 지워져도 프롬프트 번호는 그대로
    for p in ("P1", "P2", "P3", "P4"):
        ok(api.tag_trial_run(w["id"], rids[3], chain(p), None, None, Y))
    tr = {t["chain"]["steps"][0]["prompt"]: t["ver_no"] for t in ok(api.tag_work(tag, Y))["trials"] if t["record_id"] == rids[3]}
    assert "P1" not in tr and tr["P4"] - tr["P2"] == 2, tr
    # 확정(2단계) → 일괄
    two = [t for t in ok(api.tag_work(tag, Y))["trials"] if t["record_id"] == rids[3]][-1]
    c2 = ok(api.tag_trial_run(w["id"], rids[3], {**two["chain"], "steps": two["chain"]["steps"] + [{"prompt": "", "example": "", "request": "요청B"}]}, two["id"], None, Y))["id"]
    ok(api.tag_confirm(c2, True, Y))
    # C04·C11: 지금 조건에 없는 기록, 다른 항목이 섞이면 실행을 만들지 않음
    assert not api.tag_run_create(w["id"], [rids[1], other], {}, Y)["ok"]
    assert not api.tag_run_create(w["id"], [rids[1], plain], {"slot": "i:autonomy"}, Y)["ok"]
    run = ok(api.tag_run_create(w["id"], [rids[0], rids[1], rids[2]], {"slot": "i:autonomy"}, Y))["run"]
    # U06: 아직 한 건도 안 했으면 결과 없음으로 셈
    assert ok(api.tag_summary())["works"][0]["notrun"] == 3
    # C07: 같은 건이 처리 중이면 두 번째는 AI를 부르지 않음
    gate, entered = threading.Event(), threading.Event()
    def block(s, u):
        entered.set()
        gate.wait(5)
    HOOK["fn"] = block
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("a", api.tag_run_item(run["id"], rids[1], None, Y)))
    th.start()
    entered.wait(5)
    n = len(CALLS)
    second = api.tag_run_item(run["id"], rids[1], None, Y)
    m = len(CALLS)
    gate.set()
    th.join(5)
    HOOK["fn"] = None
    assert not second["ok"] and m == n, (second, m, n)
    assert out["a"]["ok"]
    assert ok(api.tag_run_item(run["id"], rids[1], None, Y)).get("skipped")
    # C08: 2단계 중 두 번째에서 실패하면 첫 단계 결과·비용을 남기고, 다시 할 때 두 번째부터
    fail = {"n": 0}
    def fail_b(s, u):
        if "요청B" in s and fail["n"] == 0:
            fail["n"] += 1
            raise openrouter.LlmError("가짜 실패")
    HOOK["fn"] = fail_b
    assert not api.tag_run_item(run["id"], rids[2], None, Y)["ok"]
    rv = {x["record_id"]: x for x in ok(api.tag_review(w["id"], run["id"], Y))["rows"]}
    assert rv[rids[2]]["state"] == "failed" and rv[rids[2]]["cand"]["cost"] > 0
    before = len(CALLS)
    ok(api.tag_run_item(run["id"], rids[2], None, Y))
    HOOK["fn"] = None
    # 확정 단계: P? → (이어) 요청B. 실패한 건은 마지막 단계만 다시
    assert len(CALLS) - before == 1, CALLS[before:]
    # A03: AI 답을 받은 뒤 저장 직전에 중지가 끼어도 저장하지 않음
    def cancel_after(tw_method):
        real = getattr(TagWork, tw_method)
        def wrapped(self, *a, **k):
            openrouter.cancel()
            openrouter.reset()
            return real(self, *a, **k)
        return real, wrapped
    real, wrapped = cancel_after("add_trial")
    TagWork.add_trial = wrapped
    try:
        r = api.tag_trial_run(w["id"], rids[2], chain("A"), None, None, Y)
    finally:
        TagWork.add_trial = real
    assert not r["ok"] and r.get("code") == "cancelled", r
    # A04: 단계 사이에서 중지하면 끝낸 단계·비용은 '중지함'으로 남고, 다시 할 때 다음 단계부터
    stop = {"n": 0}
    def stop_b(s, u):
        if "요청B" in s and stop["n"] == 0:
            stop["n"] += 1
            openrouter.cancel()
            raise openrouter.Cancelled()
    HOOK["fn"] = stop_b
    run2 = ok(api.tag_run_create(w["id"], [rids[0]], {"slot": "i:autonomy"}, Y))["run"]
    assert not api.tag_run_item(run2["id"], rids[0], None, Y)["ok"]
    openrouter.reset()
    HOOK["fn"] = None
    rv0 = ok(api.tag_review(w["id"], run2["id"], Y))["rows"][0]
    assert rv0["state"] == "failed" and "중지" in rv0["cand"]["error"] and rv0["cand"]["cost"] > 0, rv0
    before = len(CALLS)
    ok(api.tag_run_item(run2["id"], rids[0], None, Y))
    assert len(CALLS) - before == 1
    # R01: 예전에 반영한 기록을 다시 변환한 새 결과는 '검토 전'으로 셈
    c_old = ok(api.tag_review(w["id"], run2["id"], Y))["rows"][0]["cand"]["id"]
    ok(api.tag_apply(w["id"], [c_old], Y))
    run3 = ok(api.tag_run_create(w["id"], [rids[0]], {"slot": "i:autonomy"}, Y))["run"]
    ok(api.tag_run_item(run3["id"], rids[0], None, Y))
    assert ok(api.tag_summary())["works"][0]["pending"] >= 1
    # R02: 초안 저장이 프롬프트 번호표를 지우지 않음
    vers_before = ok(api.tag_work(tag, Y))["trials"]
    ok(api.tag_draft_save(w["id"], {"prompt": "새 초안"}, Y))
    d = api._db().q("SELECT draft FROM tag_works WHERE id=?", (w["id"],))[0]["draft"]
    assert json.loads(d).get("_vers"), d
    # A02: 다른 학년도 화면의 요청은 그 학년도 DB에만, 지금 학년도가 아니면 거절
    assert not api.tag_draft_save(w["id"], {"prompt": "x"}, 2027)["ok"]
    # 검토 행에 활성 여부·회차 등
    row = ok(api.tag_review(w["id"], run["id"], Y))["rows"][1]
    assert row["active"] is True and "seq" in row
    # C10: 태그를 지워도 반영 기록을 볼 수 있고 되돌릴 수 있음
    cand = row["cand"]["id"]
    res = ok(api.tag_apply(w["id"], [cand], Y))
    assert res["applied"]
    ok(api.delete_tag(tag))
    orph = ok(api.tag_orphans(Y))["works"]
    assert orph and orph[0]["live"] >= 1
    assert not ok(api.tag_summary())["works"]  # 현황판에는 지운 태그 작업을 띄우지 않음
    bt = ok(api.tag_batches(orph[0]["work_id"], Y))["batches"]
    ok(api.tag_undo(orph[0]["work_id"], bt[0]["batch"], Y))
    assert not api.tag_run_create(w["id"], [rids[0]], {}, Y)["ok"]  # 지운 태그로 새 변환은 안 됨


def test_config_broken_keep():
    """C12: 깨진 설정을 옮기지 못하면 덮어쓰지 않음, 배열 JSON도 깨진 것으로."""
    path = config.config_path()
    path.write_text("[1, 2]", encoding="utf-8")
    cfg = config.load()
    assert config.read_problem()["broken"] and cfg["setup_done"] is False
    path.write_text("{깨짐", encoding="utf-8")
    real = config._set_aside
    config._set_aside = lambda p: None
    try:
        config.load()
        assert config.read_problem()["error"]
        try:
            config.save({"menu_collapsed": True})
            raise AssertionError("깨진 원본을 덮어씀")
        except config.ConfigError:
            pass
        assert path.read_text(encoding="utf-8") == "{깨짐"
    finally:
        config._set_aside = real


if __name__ == "__main__":
    test_edges()
    test_config_broken_keep()
    print("test_tagwork_edges OK")
