import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, openrouter
from app.api import Api
from app.inbox import detect, interpret, label_date, match_one

SENT = []
openrouter.chat = lambda key, model, system, user, privacy_block=False: (SENT.append((system, user)) or ("정제됨: " + user, 0.001))
openrouter.balance = lambda key: 2.0

def ok(r):
    assert r.get("ok"), r
    return r

def test_units():
    assert label_date("3/15", 2026) == "2026-03-15" and label_date("2월 3일", 2026) == "2027-02-03" and label_date("1차", 2026) == ""
    # 학생이 행, 첫 줄 제목
    raw = [["학번", "이름", "3/15", "4/2"], ["20301", "김철수", "A내용", "B내용"], ["20302", "이영희", "C내용", ""]]
    d = detect(raw); assert d["orient"] == "rows" and d["header"] and d["no_idx"] == 0 and d["name_idx"] == 1
    rows = interpret(raw, {"structure": "multi", **d}, 2026)
    assert [(r["ext_no"], r["label"], r["date"], r["content"], r["source_ref"]) for r in rows] == [
        ("20301", "3/15", "2026-03-15", "A내용", "C2"), ("20301", "4/2", "2026-04-02", "B내용", "D2"), ("20302", "3/15", "2026-03-15", "C내용", "C3")]
    # 학생이 열
    t = [list(x) for x in zip(*raw)]
    d2 = detect(t); assert d2["orient"] == "cols" and d2["no_idx"] == 0
    rows2 = interpret(t, {"structure": "multi", **d2}, 2026)
    assert [r["content"] for r in rows2] == ["A내용", "B내용", "C내용"] and rows2[0]["source_ref"] == "B3"
    # 제목 없으면 1회, 2회
    rows3 = interpret(raw[1:], {"structure": "multi", "orient": "rows", "header": False, "no_idx": 0, "name_idx": 1}, 2026)
    assert [r["label"] for r in rows3] == ["1회", "2회", "1회"]
    # 한 학생: 행 우선 / 열 우선
    g = [["a", "b"], ["c", ""]]
    assert [r["content"] for r in interpret(g, {"structure": "single", "order": "row"}, 2026)] == ["a", "b", "c"]
    assert [r["content"] for r in interpret(g, {"structure": "single", "order": "col"}, 2026)] == ["a", "c", "b"]
    # 매칭 규칙
    mem = [{"student_no": "20301", "name": "김철수", "active": 1}, {"student_no": "20302", "name": "이영희", "active": 1},
           {"student_no": "20303", "name": "이영희", "active": 1}, {"student_no": "20304", "name": "박민수", "active": 0}]
    assert match_one("20301", "김철수", mem)[1] == "confirmed"
    assert match_one("20301", "김철순", mem)[1] == "suggested"
    assert match_one("", "김철수", mem)[:2] == ("20301", "suggested")
    assert match_one("", "이영희", mem)[1] == "none" and "동명이인" in match_one("", "이영희", mem)[2]
    assert match_one("", "김철우", mem)[:2] == ("20301", "suggested")  # 비슷한 이름
    assert "비활성" in match_one("20304", "박민수", mem)[2]
    assert match_one("29999", "", mem)[1] == "none"

def test_flow():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김철수\n20302\t이영희\n20303\t박민수")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    tag = ok(api.add_tag("독서"))["id"]

    bid = ok(api.inbox_create("독서 기록", hr, "career"))["id"]
    src = ok(api.inbox_source_text(bid, "학번\t이름\t3/15\t4/2\n20301\t김철수\t\"첫 줄\n둘째 줄\"\t감상2\n\t박민수\t감상3\t\n20399\t홍길동\t감상4\t"))
    opts = {"structure": "multi", **src["opts"]}
    assert len(ok(api.inbox_preview(bid, opts))["rows"]) == 4
    assert ok(api.inbox_import(bid, opts))["count"] == 4
    v = ok(api.inbox_view(bid))
    assert v["counts"] == {"confirmed": 2, "suggested": 1, "none": 1, "excluded": 0, "sent": 0}, v["counts"]
    assert v["rows"][0]["content"] == "첫 줄\n둘째 줄"
    assert not api.inbox_stage(bid, "refine")["ok"]  # 확인 필요 남음(화면 확인 없이)
    # 확인을 받고 넘어가면 확인 필요 행은 '제외(매칭 미확인)' → 매칭으로 돌아와 제외 취소하면 되살아남
    ok(api.inbox_stage(bid, "refine", True))
    vv = ok(api.inbox_view(bid))
    assert vv["counts"] == {"confirmed": 2, "suggested": 0, "none": 0, "excluded": 2, "sent": 0} and {r["exclude_reason"] for r in vv["rows"] if r["state"] == "excluded"} == {"매칭 미확인"}
    ok(api.inbox_stage(bid, "match"))
    ok(api.inbox_exclude([r["id"] for r in vv["rows"] if r["state"] == "excluded"], "", False))
    assert ok(api.inbox_view(bid))["counts"] == {"confirmed": 2, "suggested": 1, "none": 1, "excluded": 0, "sent": 0}
    assert not api.inbox_send(bid)["ok"]
    ok(api.inbox_confirm_suggested(bid))
    none_row = [r for r in ok(api.inbox_view(bid))["rows"] if r["state"] == "none"][0]
    assert not api.inbox_set_student(none_row["id"], "29999")["ok"]
    ok(api.inbox_exclude([none_row["id"]], "다른 반"))
    ok(api.inbox_stage(bid, "refine"))
    # 정제: 학번·이름 미전송, 후보 3개 순환
    r0 = ok(api.inbox_view(bid))["rows"][0]
    for _ in range(4):
        ok(api.ai_inbox_row(r0["id"]))
    for sys_, user in SENT:
        for leak in ("20301", "김철수", "박민수", "20399"):
            assert leak not in sys_ and leak not in user
    r0 = [r for r in ok(api.inbox_view(bid))["rows"] if r["id"] == r0["id"]][0]
    assert len(r0["cands"]) == 3 and r0["text"].startswith("정제됨")
    ok(api.inbox_use_cand(r0["id"], None)); assert [r for r in ok(api.inbox_view(bid))["rows"] if r["id"] == r0["id"]][0]["text"] == "첫 줄\n둘째 줄"
    ok(api.inbox_use_cand(r0["id"], r0["cands"][-1]["id"]))
    ok(api.inbox_update(bid, {"tag_ids": [tag], "date": "2026-06-01"}))
    ok(api.inbox_stage(bid, "review"))
    rv = ok(api.inbox_review(bid)); assert rv["send_rows"] == 3 and rv["excluded"] == 1 and len(rv["students"]) == 2

    # 마감된 학생 → 막음 / 제외 / 해제
    rid = ok(api.add_record(hr, "career", "20303", {"content": "기존"}))["id"]
    ok(api.adopt_record(rid)); ok(api.set_closed(hr, "career", "20303", True))
    bad = api.inbox_send(bid); assert not bad["ok"] and "마감된 학생 1명" in bad["error"]
    res = ok(api.inbox_send(bid, "reopen"))
    assert res["records"] == 3 and res["reopened"] == ["20303"]
    assert not api.inbox_send(bid)["ok"]  # 재전송 막음
    assert not api.inbox_exclude([r0["id"]], "x")["ok"]  # 보낸 묶음 수정 막음
    v1 = ok(api.student_view(hr, "career", "20301"))["records"]
    assert [(r["seq"], r["title"], r["date"]) for r in v1] == [(1, "독서 기록", "2026-03-15"), (2, "독서 기록", "2026-04-02")]
    assert v1[0]["content"].startswith("정제됨") and v1[0]["tags"][0]["name"] == "독서" and v1[0]["source"] == f"inbox:{bid}"
    v3 = ok(api.student_view(hr, "career", "20303"))
    assert v3["final"]["stale"] and not v3["final"]["closed"] and [r["seq"] for r in v3["records"]] == [1, 2]  # 기존 기록 다음 회차

    # 한 학생 여러 회차, 열 우선
    b2 = ok(api.inbox_create("관찰", hr, "behavior"))["id"]
    ok(api.inbox_source_text(b2, "a\tb\nc\t"))
    assert not api.inbox_import(b2, {"structure": "single"})["ok"]  # 학생 미선택
    assert ok(api.inbox_import(b2, {"structure": "single", "order": "col", "student_no": "20302"}))["count"] == 3
    ok(api.inbox_stage(b2, "review")); ok(api.inbox_send(b2))
    assert [r["content"] for r in ok(api.student_view(hr, "behavior", "20302"))["records"]] == ["a", "c", "b"]

    # 보낸 묶음 단위: 태그 한꺼번에(되돌리기), 모두 삭제(마감·옮긴 기록 빼고), 남은 게 없으면 다시 보내기 가능
    info = ok(api.inbox_sent_info(bid))
    assert len(info["record_ids"]) == 3 and info["students"] == 2 and info["tag_counts"] == {str(tag): 3} and info["with_cands"] == 0, info
    t2 = ok(api.add_tag("과학"))["id"]
    tr = ok(api.tag_records_undoable(info["record_ids"], [t2], "add"))
    assert ok(api.inbox_sent_info(bid))["tag_counts"][str(t2)] == 3
    ok(api.undo_tag_records(tr["pairs"], "add"))
    assert str(t2) not in ok(api.inbox_sent_info(bid))["tag_counts"]
    ok(api.set_closed(hr, "career", "20303", True))  # 마감된 학생 기록은 지우지 않음
    info = ok(api.inbox_sent_info(bid)); assert info["closed"] == 1 and len(info["deletable"]) == 2
    assert not api.inbox_delete_sent(bid, "확인")["ok"]  # '확인했어요'를 쳐야 함
    d1 = ok(api.inbox_delete_sent(bid, "확인했어요"))
    assert d1["deleted"] == 2 and not d1["reopened"] and ok(api.inbox_view(bid))["batch"]["stage"] == "sent"
    assert [r["source"] for r in ok(api.student_view(hr, "career", "20301"))["records"]] == []
    ok(api.set_closed(hr, "career", "20303", False))
    d2 = ok(api.inbox_delete_sent(bid, "확인했어요"))
    assert d2["deleted"] == 1 and d2["reopened"]
    vb = ok(api.inbox_view(bid))["batch"]; assert vb["stage"] == "review" and not vb["sent_at"]
    assert ok(api.inbox_send(bid))["records"] == 3  # 다시 보내기

    # 대상 명렬을 바꾸면 다시 매칭
    sub = ok(api.add_group({"kind": "subject", "name": "수학", "semester": 1}))["id"]
    b3 = ok(api.inbox_create("x", hr, "career"))["id"]
    s3 = ok(api.inbox_source_text(b3, "20301\t김철수\t내용"))
    ok(api.inbox_import(b3, {"structure": "multi", **s3["opts"]}))
    ok(api.inbox_update(b3, {"group_id": sub, "item": "subject"}))
    assert ok(api.inbox_view(b3))["rows"][0]["state"] == "none"  # 수학 명렬 비어 있음
    lst = ok(api.inbox_list())["batches"]; assert lst[-1]["stage"] == "sent" and any(b["pending"] for b in lst)
    # 인박스 묶음 이름 → 태그(보내기 전 묶음에는 붙이고, 보낸 묶음은 그대로, 이미 있는 태그는 건너뜀)
    ok(api.add_tag("관찰"))
    names = {n["name"]: n for n in ok(api.inbox_tag_names())["names"]}
    assert names["관찰"]["exists"] and not names["x"]["exists"] and names["x"]["open"] == 1 and names["독서 기록"]["open"] == 0
    r = ok(api.tags_from_inbox(["x", "독서 기록", "관찰", " x "]))
    assert r["made"] == 2 and r["attached"] == 1, r
    tid = {t["name"]: t["id"] for t in r["tags"]}
    assert ok(api.inbox_view(b3))["batch"]["tag_ids"] == [tid["x"]]
    assert tid["독서 기록"] not in ok(api.inbox_view(bid))["batch"]["tag_ids"]  # 보낸 묶음은 그대로
    # 보낸 묶음을 이력에서 지워도 기록은 그대로
    n_before = len(ok(api.student_view(hr, "behavior", "20302"))["records"])
    ok(api.inbox_delete(b2))
    assert b2 not in [x["id"] for x in ok(api.inbox_list())["batches"]]
    assert len(ok(api.student_view(hr, "behavior", "20302"))["records"]) == n_before == 3
    print("INBOX OK")

if __name__ == "__main__":
    test_units(); test_flow()
