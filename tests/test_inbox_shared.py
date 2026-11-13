"""자료 인박스 '한 문서 → 여러 학생': 같은 문서를 고른 학생마다 한 건(역할 메모 한 줄), 태그, 보내기, 명렬 바꾸면 ①로.
태그 AI 변환 나머지 변환에서 같은 원문을 쓰는 대상이 있으면 '겹치지 않기' 규칙을 붙인다."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter

CALLS = []


def fake_chat(key, model, system, user, privacy_block=False):
    CALLS.append((system, user))
    return "결과:" + user[:15], 0.001


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402

DOC = "기후 위기 대응 방안을 조사한 모둠 보고서. 탄소 배출 통계를 분석하고 학교 실천 방안을 제안함."


def ok(r):
    assert r.get("ok"), r
    return r


def test_shared():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    hr2 = ok(api.add_group({"kind": "club", "name": "과학탐구반"}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나\n20304\t최네모")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    bid = ok(api.inbox_create("", hr, "autonomy"))["id"]
    # 막는 경우
    assert not api.inbox_shared(bid, {"text": " ", "picks": [{"student_no": "20301"}]})["ok"]
    assert not api.inbox_shared(bid, {"text": DOC, "picks": []})["ok"]
    assert not api.inbox_shared(bid, {"text": DOC, "picks": [{"student_no": "99999"}]})["ok"]
    assert not api.inbox_shared(bid, {"text": DOC, "date": "5월", "picks": [{"student_no": "20301"}]})["ok"]
    r = ok(api.inbox_shared(bid, {"text": DOC, "label": "기후 모둠 보고서", "date": "2026-05-10",
                                   "picks": [{"student_no": "20301", "role": "자료 조사"}, {"student_no": "20302", "role": ""},
                                             {"student_no": "20303", "role": "발표"}, {"student_no": "20301", "role": "중복"}]}))
    assert r["count"] == 3
    v = ok(api.inbox_view(bid))
    assert v["batch"]["structure"] == "shared" and v["batch"]["stage"] == "match" and v["batch"]["title"] == "기후 모둠 보고서"
    rows = {x["student_no"]: x for x in v["rows"]}
    assert rows["20301"]["content"] == DOC + "\n\n[이 학생의 역할] 자료 조사" and rows["20302"]["content"] == DOC
    assert all(x["state"] == "confirmed" for x in v["rows"]) and v["batch"]["meta"]["shared"]["picks"][0]["role"] == "자료 조사"
    ok(api.inbox_rematch(bid))  # 직접 고른 학생은 그대로
    assert all(x["state"] == "confirmed" for x in ok(api.inbox_view(bid))["rows"])
    # 명렬을 바꾸면 ①로(학생 다시 고르기), 되돌리면 다시 넣기
    ok(api.inbox_update(bid, {"group_id": hr2, "item": "club"}))
    v = ok(api.inbox_view(bid))
    assert v["batch"]["stage"] == "import" and not v["rows"] and v["batch"]["meta"]["shared"]["text"] == DOC
    ok(api.inbox_update(bid, {"group_id": hr, "item": "autonomy"}))
    ok(api.inbox_shared(bid, {"text": DOC, "label": "기후 모둠 보고서", "date": "2026-05-10",
                               "picks": [{"student_no": n, "role": rl} for n, rl in (("20301", "자료 조사"), ("20302", ""), ("20303", "발표"))]}))
    ok(api.add_tag("기후모둠"))
    tag = ok(api.tags())["tags"][0]["id"]
    ok(api.inbox_update(bid, {"tag_ids": [tag]}))
    ok(api.inbox_stage(bid, "review"))
    ok(api.inbox_send(bid))
    tv = ok(api.tag_view(tag, {}))
    recs = sorted(tv["records"], key=lambda x: x["student_no"])
    assert [x["student_no"] for x in recs] == ["20301", "20302", "20303"]
    assert recs[0]["title"] == "기후 모둠 보고서" and recs[0]["date"] == "2026-05-10" and recs[1]["content"] == DOC
    # 태그 AI 변환: 시험 → 확정 → 나머지 변환에는 같은 원문 규칙
    w = ok(api.tag_work(tag))["work"]
    c1 = ok(api.tag_trial_run(w["id"], recs[0]["id"], {"src": "original", "steps": [{"prompt": "지침"}]}))["id"]
    assert "[같은 자료를 쓴 다른 학생과 겹치지 않기]" not in CALLS[-1][0]
    ok(api.tag_confirm(c1, True))
    run = ok(api.tag_run_create(w["id"], [x["id"] for x in recs[1:]]))["run"]
    ok(api.tag_run_item(run["id"], recs[1]["id"]))
    assert "[같은 자료를 쓴 다른 학생과 겹치지 않기]" in CALLS[-1][0] and CALLS[-1][1] == DOC
    ok(api.tag_run_item(run["id"], recs[2]["id"]))
    assert "[같은 자료를 쓴 다른 학생과 겹치지 않기]" in CALLS[-1][0] and CALLS[-1][1].endswith("[이 학생의 역할] 발표")
    # 같은 원문이 아니면 붙이지 않음
    other = ok(api.add_record(hr, "autonomy", "20304", {"content": "혼자 쓴 다른 보고서 내용이 여기 있습니다. 충분히 긴 글.", "tag_ids": [tag]}))["id"]
    run2 = ok(api.tag_run_create(w["id"], [other]))["run"]
    ok(api.tag_run_item(run2["id"], other))
    assert "[같은 자료를 쓴 다른 학생과 겹치지 않기]" not in CALLS[-1][0]


if __name__ == "__main__":
    test_shared()
    print("test_inbox_shared OK")
