"""기록 확정·결과 묶음(항목별+태그 결과)·직접 작성·이어 붙이기·전체 학생 이어 붙이기(가짜 AI)."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter

openrouter.chat = lambda key, model, system, user, privacy_block=False: ("변환:" + user, 0.001)
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def recs(api, gid, item, sno):
    return ok(api.student_view(gid, item, sno))["records"]


def test_all():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.add_tag("봉사")); ok(api.add_tag("독서"))
    tags = {t["name"]: t["id"] for t in ok(api.tags())["tags"]}
    a = ok(api.add_record(hr, "autonomy", "20301", {"content": "봉사 원문", "tag_ids": [tags["봉사"]]}))["id"]
    b = ok(api.add_record(hr, "autonomy", "20301", {"content": "독서 원문", "tag_ids": [tags["독서"]]}))["id"]
    # AI 변환은 후보만(4번 해도 지워지지 않음, 원문 기준)
    for _ in range(4):
        ok(api.ai_record(a))
    r = recs(api, hr, "autonomy", "20301")[0]
    assert r["id"] == a and not r["confirmed"] and r["orig"] == "봉사 원문" and r["content"] == "봉사 원문"
    assert len(r["bundle"]) == 4 and all(x["text"] == "변환:봉사 원문" for x in r["bundle"])
    # 태그 변환 결과도 같은 묶음에(맨 위)
    w = ok(api.tag_work(tags["봉사"], 2026))["work"]
    cid = ok(api.tag_trial_run(w["id"], a, {"src": "original", "steps": [{"prompt": "p"}]}, None, None, 2026))["id"]
    r = recs(api, hr, "autonomy", "20301")[0]
    assert len(r["bundle"]) == 5 and r["bundle"][0]["src"] == "tag" and r["bundle"][0]["meta"]["tag_name"] == "봉사"
    # 결과로 확정 → 확정본, 원문 보존
    res_id = [x for x in r["bundle"] if x["src"] == "rec"][0]["id"]
    ok(api.apply_candidate(res_id))
    r = recs(api, hr, "autonomy", "20301")[0]
    assert r["confirmed"] and r["content"] == "변환:봉사 원문" and r["orig"] == "봉사 원문"
    # 확정본 수정 → 확정 유지
    ok(api.update_record(a, {"content": "봉사 확정본"}))
    r = recs(api, hr, "autonomy", "20301")[0]
    assert r["confirmed"] and r["content"] == "봉사 확정본"
    # 확정 풀기 → 확정본은 '이전 확정본' 결과, 원문으로
    ok(api.unconfirm_record(a))
    r = recs(api, hr, "autonomy", "20301")[0]
    assert not r["confirmed"] and r["content"] == "봉사 원문" and any(x["label"] == "이전 확정본" and x["text"] == "봉사 확정본" for x in r["bundle"])
    # 확정 전 원문 고치기
    ok(api.update_record(a, {"orig": "봉사 원문2"}))
    r = recs(api, hr, "autonomy", "20301")[0]
    assert r["orig"] == "봉사 원문2" and r["content"] == "봉사 원문2"
    # 직접 작성 확정, 후보 저장, 새 기록
    ok(api.confirm_record(a, "봉사 직접 확정"))
    ok(api.save_draft(b, "독서 초안"))
    nid = ok(api.new_record_from(b, "독서 새 기록"))["id"]
    rs = recs(api, hr, "autonomy", "20301")
    nb = [x for x in rs if x["id"] == nid][0]
    assert nb["confirmed"] and nb["tags"][0]["name"] == "독서"
    assert any(x["label"] == "직접 작성" for x in [x for x in rs if x["id"] == b][0]["bundle"])
    # 원문 그대로 확정
    ok(api.confirm_record(b, "독서 원문"))
    r = [x for x in recs(api, hr, "autonomy", "20301") if x["id"] == b][0]
    assert r["confirmed"] and r["original"] is None
    # 이어 붙이기: 순서대로, 순서 저장, 최종안 '확인 필요' 표시
    prev = ok(api.join_confirmed(hr, "autonomy", "20301", [b, a]))["prev"]
    assert prev == ""
    v = ok(api.student_view(hr, "autonomy", "20301"))
    assert v["final"]["text"] == "독서 원문 봉사 직접 확정" and v["final"]["source"] == "join"
    assert [x["id"] for x in v["records"]][:2] == [b, a]
    ok(api.update_record(a, {"content": "봉사 고친 확정본"}))
    assert ok(api.student_view(hr, "autonomy", "20301"))["final"]["stale"]
    assert not api.join_confirmed(hr, "autonomy", "20301", [nid, a, 999])["ok"]
    # 전체 학생: 20302는 독서만, 20303은 확정 없음
    c2 = ok(api.add_record(hr, "autonomy", "20302", {"content": "둘 독서", "tag_ids": [tags["독서"]]}))["id"]
    ok(api.confirm_record(c2, "둘 독서 확정"))
    ok(api.add_record(hr, "autonomy", "20303", {"content": "셋 미확정"}))
    view = ok(api.join_bulk_view(hr, "autonomy"))
    assert [x["name"] for x in view["activities"]] == ["독서", "봉사"] or [x["name"] for x in view["activities"]] == ["봉사", "독서"]
    order = [tags["봉사"], tags["독서"], 0]
    pv = ok(api.join_bulk_preview(hr, "autonomy", order))["plan"]
    assert pv["20301"]["text"] == "봉사 고친 확정본 독서 원문 독서 새 기록" and pv["20302"]["text"] == "둘 독서 확정"
    out = ok(api.join_bulk(hr, "autonomy", order, False))
    assert out["count"] == 1 and out["skipped"] == {"최종안 있음": 1, "확정 기록 없음": 1}, out
    out = ok(api.join_bulk(hr, "autonomy", order, True))
    assert out["count"] == 1, out  # 20301만 바뀜(20302는 이미 같은 내용)
    assert ok(api.student_view(hr, "autonomy", "20301"))["final"]["text"] == pv["20301"]["text"]
    ok(api.finals_bulk_undo())
    assert ok(api.student_view(hr, "autonomy", "20301"))["final"]["text"] == "독서 원문 봉사 직접 확정"
    # 태그 ③ 반영 = 확정, 되돌리면 풀림
    d = ok(api.add_record(hr, "autonomy", "20303", {"content": "셋 봉사", "tag_ids": [tags["봉사"]]}))["id"]
    tc = ok(api.tag_trial_run(w["id"], d, {"src": "original", "steps": [{"prompt": "p"}]}, None, None, 2026))["id"]
    ap = ok(api.tag_apply(w["id"], [tc], 2026))
    r = [x for x in recs(api, hr, "autonomy", "20303") if x["id"] == d][0]
    assert r["confirmed"] and r["orig"] == "셋 봉사"
    ok(api.tag_undo(w["id"], ap["batch"], 2026))
    r = [x for x in recs(api, hr, "autonomy", "20303") if x["id"] == d][0]
    assert not r["confirmed"] and r["content"] == "셋 봉사"


if __name__ == "__main__":
    test_all()
    print("test_confirm_join OK")
