import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, openrouter
from app.api import Api
from app.records import Records

openrouter.chat = lambda key, model, system, user, privacy_block=False: ("종합 결과", 0.0)
openrouter.balance = lambda key: 1.0

def ok(r):
    assert r.get("ok"), r
    return r

def test():
    assert Records.paragraphs("가\n\n나\n다") == ["가", "나\n다"] and Records.paragraphs("가\n나") == ["가", "나"] and Records.paragraphs("") == []
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    club = ok(api.add_group({"kind": "club", "name": "탐구반"}))["id"]
    p = api.roster_from_text("20301\t김철수\n20302\t이영희\n20303\t박민수")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    p2 = api.roster_from_text("20301\t김철수")
    ok(api.roster_apply(club, api.roster_build(club, p2["raw"], p2["header"], p2["columns"])["rows"]))
    tag = ok(api.add_tag("독서"))["id"]

    # 이동 대상: 같은 학생이 속한 다른 항목
    t = ok(api.move_targets(hr, "career", "20301"))["targets"]
    assert [(x["group_id"], x["item"]) for x in t] == [(hr, "autonomy"), (hr, "behavior"), (club, "club")]
    assert [x["item"] for x in ok(api.move_targets(hr, "career", "20302"))["targets"]] == ["autonomy", "behavior"]

    r1 = ok(api.add_record(hr, "career", "20301", {"content": "문단1\n\n문단2\n\n문단3", "title": "독서", "date": "2026-03-01", "tag_ids": [tag]}))["id"]
    r2 = ok(api.add_record(hr, "career", "20301", {"content": "전체 이동"}))["id"]
    ok(api.add_record(hr, "autonomy", "20301", {"content": "자율 기존"}))
    # 최종안이 있으면 양쪽 모두 '채택 후 변경'
    ok(api.adopt_record(r2))
    ok(api.move_records([{"record_id": r1, "paras": [1]}], hr, "autonomy"))
    src = ok(api.student_view(hr, "career", "20301"))
    assert [r["content"] for r in src["records"] if r["id"] == r1] == ["문단1\n\n문단3"] and src["final"]["stale"]
    dst = ok(api.student_view(hr, "autonomy", "20301"))["records"]
    moved = dst[-1]
    assert moved["content"] == "문단2" and moved["seq"] == 2 and moved["title"] == "독서" and moved["tags"][0]["name"] == "독서" and moved["source"].startswith("moved:career")
    # 되돌리기
    ok(api.undo_move())
    assert [r["content"] for r in ok(api.student_view(hr, "career", "20301"))["records"] if r["id"] == r1] == ["문단1\n\n문단2\n\n문단3"]
    assert len(ok(api.student_view(hr, "autonomy", "20301"))["records"]) == 1
    assert not api.undo_move()["ok"]
    # 기록 전체 여러 건 → 동아리, 원래 기록 삭제되고 되돌리면 복원(태그 포함)
    ok(api.move_records([{"record_id": r1, "paras": None}, {"record_id": r2, "paras": None}], club, "club"))
    assert ok(api.student_view(hr, "career", "20301"))["records"] == []
    assert [r["content"] for r in ok(api.student_view(club, "club", "20301"))["records"]] == ["문단1\n\n문단2\n\n문단3", "전체 이동"]
    ok(api.undo_move())
    back = ok(api.student_view(hr, "career", "20301"))["records"]
    assert [r["id"] for r in back] == [r1, r2] and back[0]["tags"][0]["name"] == "독서"
    # 마감된 도착지·속하지 않은 항목은 막힘
    rid = ok(api.add_record(hr, "behavior", "20301", {"content": "행특"}))["id"]
    ok(api.adopt_record(rid)); ok(api.set_closed(hr, "behavior", "20301", True))
    assert "마감" in api.move_records([{"record_id": r1, "paras": [0]}], hr, "behavior")["error"]
    r3 = ok(api.add_record(hr, "career", "20302", {"content": "x"}))["id"]
    assert not api.move_records([{"record_id": r3, "paras": None}], club, "club")["ok"]
    assert not api.move_records([{"record_id": r1, "paras": []}], hr, "autonomy")["ok"]

    # 일괄 종합 준비 정보
    for i in range(3):
        x = ok(api.ai_synth(hr, "career", "20302", [r3], None)); ok(api.lock_result(x["id"], True))
    info = {s["student_no"]: s for s in ok(api.batch_info(hr, "career"))["students"]}
    assert info["20301"]["records"] == 2 and not info["20301"]["all_locked"]
    assert info["20302"]["all_locked"] and info["20303"]["records"] == 0
    # 현황판: 인박스 할 일
    b = ok(api.inbox_create("자료", hr, "career"))["id"]
    s = ok(api.inbox_source_text(b, "20301\t김철수\t내용"))
    ok(api.inbox_import(b, {"structure": "multi", **s["opts"]}))
    labels = [t["label"] for t in ok(api.dashboard())["todo"]]
    assert not any("인박스 확인 필요" in l for l in labels)  # 모두 확정된 매칭 대기는 '확인 필요' 아님
    ok(api.inbox_stage(b, "review"))
    assert any("인박스 보내기 대기 1묶음" == l for l in [t["label"] for t in ok(api.dashboard())["todo"]])
    print("MOVE/BATCH OK")

if __name__ == "__main__":
    test()
