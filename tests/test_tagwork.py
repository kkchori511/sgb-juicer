"""태그 AI 변환: 시험(후보 3칸·이어 고치기) → 확정(반영) → 나머지 일괄(단계 재현) → 검토·반영(바뀐 기록 제외) → 되돌리기."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter

CALLS = []


def fake_chat(key, model, system, user, privacy_block=False):
    CALLS.append((system, user))
    n = len(CALLS)
    if "실패시켜" in user:
        raise openrouter.LlmError("가짜 실패")
    return f"변환{n}:" + user[:20], 0.001


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0  # 잔액 조회 HTTP를 보내지 않음
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def setup():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    names = ["김하나", "이두리", "박세나", "최네모", "정다섯", "한여섯"]
    p = api.roster_from_text("\n".join(f"203{i:02d}\t{n}" for i, n in enumerate(names, 1)))
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.add_tag("독서"))
    tag = ok(api.tags())["tags"][0]["id"]
    rids = []
    for i in range(1, 6):
        rids.append(ok(api.add_record(hr, "career", f"203{i:02d}", {"content": f"원문{i} 책을 읽음", "tag_ids": [tag]}))["id"])
    ex = ok(api.add_record(hr, "career", "20306", {"kind": "existing", "content": "기존 완성문", "tag_ids": [tag]}))["id"]
    return api, hr, tag, rids, ex


def test_flow():
    api, hr, tag, rids, ex = setup()
    w = ok(api.tag_work(tag))["work"]
    assert w["tag_name"] == "독서" and ok(api.tag_work(tag))["work"]["id"] == w["id"]  # 같은 작업을 이어 씀
    ok(api.tag_draft_save(w["id"], {"prompt": "지침A", "example": ""}))
    assert ok(api.tag_work(tag))["work"]["draft"]["prompt"] == "지침A"
    r0 = rids[0]
    chain_a = {"src": "original", "steps": [{"prompt": "지침A", "example": "", "request": ""}]}
    # 시험 4번 → 후보 3칸(가장 오래된 것 지움), 잠근 것은 남음
    c1 = ok(api.tag_trial_run(w["id"], r0, chain_a))["id"]
    ok(api.tag_cand_lock(c1, True))
    for _ in range(3):
        ok(api.tag_trial_run(w["id"], r0, {"src": "original", "steps": [{"prompt": "지침B", "example": "", "request": ""}]}))
    trials = ok(api.tag_work(tag))["trials"]
    assert len(trials) == 3 and c1 in [t["id"] for t in trials]
    assert {t["ver_no"] for t in trials} == {1, 2}  # 지침A=1, 지침B=2
    assert CALLS[-1][1] == "원문1 책을 읽음" and "지침B" in CALLS[-1][0]
    # 이어 고치기: 앞 후보 글에 요청만
    par = trials[-1]
    chain2 = {"src": "original", "steps": par["chain"]["steps"] + [{"prompt": "", "example": "", "request": "더 짧게"}]}
    c2 = ok(api.tag_trial_run(w["id"], r0, chain2, par["id"]))["id"]
    assert CALLS[-1][1] == par["text"] and "더 짧게" in CALLS[-1][0] and "지침B" in CALLS[-1][0]
    bad = api.tag_trial_run(w["id"], r0, {"src": "original", "steps": [{"prompt": "다른", "request": ""}, {"request": "x"}]}, par["id"])
    assert not bad["ok"]
    # 확정 → 그 기록에 반영, 단계 2개가 태그 설정
    cf = ok(api.tag_confirm(c2, True))
    assert cf["applied"]["applied"] and ok(api.tag_work(tag))["work"]["confirmed"]["chain"]["steps"][1]["request"] == "더 짧게"
    rec0 = [r for r in ok(api.student_view(hr, "career", "20301"))["records"] if r["id"] == r0][0]
    assert rec0["content"].startswith("변환") and rec0["original"] == "원문1 책을 읽음"
    # 대상 목록: 반영한 기록·기존 완성문은 체크 해제로
    pl = ok(api.tag_plan(w["id"], {}))
    dflt = {t["id"]: t["default"] for t in pl["targets"]}
    assert dflt[r0] is False and dflt[ex] is False and all(dflt[r] for r in rids[1:]), dflt
    assert pl["cost_per_call"] and pl["items"]
    # 마감 학생은 막힘
    ok(api.add_record(hr, "career", "20305", {"kind": "existing", "content": "마감용"}))
    # 일괄: 단계 2개 재현(원문 → 지침B → 더 짧게), 한 건은 실패
    ok(api.update_record(rids[3], {"content": "실패시켜 주세요"}))
    run = ok(api.tag_run_create(w["id"], rids[1:], {}))["run"]
    n0 = len(CALLS)
    outs = [api.tag_run_item(run["id"], r) for r in rids[1:]]
    assert sum(1 for o in outs if o["ok"]) == 3 and not outs[2]["ok"]
    assert len(CALLS) - n0 == 3 * 2 + 1  # 성공 3건×2단계 + 실패 1번
    assert ok(api.tag_run_item(run["id"], rids[1])).get("skipped")  # 성공한 건은 다시 부르지 않음
    assert not api.tag_run_item(run["id"], r0)["ok"]  # 대상 아님
    ok(api.tag_run_finish(run["id"], "done"))
    rv = ok(api.tag_review(w["id"]))
    st = {x["record_id"]: x for x in rv["rows"]}
    assert st[rids[3]]["state"] == "failed" and st[rids[1]]["state"] == "ok" and not st[rids[1]]["changed"]
    # 그사이 원문이 바뀐 기록은 반영에서 빠짐
    ok(api.update_record(rids[2], {"content": "선생님이 고침"}))
    cid1, cid2, cid4 = st[rids[1]]["cand"]["id"], st[rids[2]]["cand"]["id"], st[rids[4]]["cand"]["id"]
    ok(api.tag_cand_edit(cid1, "검토하며 고친 글"))
    ok(api.tag_cand_check([cid1, cid2, cid4], True))
    res = ok(api.tag_apply(w["id"], [cid1, cid2, cid4]))
    assert {a["record_id"] for a in res["applied"]} == {rids[1], rids[4]}
    assert [s["why"] for s in res["skipped"]] == ["결과를 만든 뒤 기록이 바뀜"]
    view = {r["id"]: r for r in ok(api.student_view(hr, "career", "20302"))["records"]}
    assert view[rids[1]]["content"] == "검토하며 고친 글"
    # 반영 뒤 다시 고친 기록은 되돌리지 않음
    ok(api.update_record(rids[4], {"content": "또 고침"}))
    un = ok(api.tag_undo(w["id"], res["batch"]))
    assert [u["record_id"] for u in un["undone"]] == [rids[1]] and un["skipped"][0]["why"] == "반영 뒤 기록이 다시 바뀜"
    view = {r["id"]: r for r in ok(api.student_view(hr, "career", "20302"))["records"]}
    assert view[rids[1]]["content"] == "원문2 책을 읽음"
    assert not api.tag_undo(w["id"], res["batch"])["ok"] or ok(api.tag_undo(w["id"], res["batch"]))["undone"] == []
    # 실패만 다시: 내용 고친 뒤 같은 실행으로 다시
    ok(api.update_record(rids[3], {"content": "다시 해 볼 원문"}))
    assert ok(api.tag_run_item(run["id"], rids[3]))["id"]
    assert ok(api.tag_review(w["id"]))["rows"][2]["state"] == "ok"
    # 현황판
    sm = ok(api.tag_summary())["works"]
    assert sm and sm[0]["tag_name"] == "독서" and sm[0]["pending"] >= 1
    # 마감된 학생 기록은 시험·반영 불가
    final = ok(api.student_view(hr, "career", "20301"))
    ok(api.edit_final(hr, "career", "20301", "최종안"))
    ok(api.set_closed(hr, "career", "20301", True))
    assert not api.tag_trial_run(w["id"], r0, chain_a)["ok"]
    # 태그를 지워도 작업 이력은 남음
    ok(api.delete_tag(tag))
    assert ok(api.tag_review(w["id"]))["rows"]


if __name__ == "__main__":
    test_flow()
    print("test_tagwork OK")
