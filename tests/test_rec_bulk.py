"""항목별 기록 › AI 변환 › 프롬프트 마법사: 대화 결과를 기록 결과 묶음에 넣기, 저장한 프롬프트를 다른 학생 기록에도 적용."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter  # noqa: E402

CALLS = []


def fake_chat(key, model, system, user, privacy_block=False, history=None):
    CALLS.append(system)
    return ("변환 글", 0.0)


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_all():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나\n20304\t최네모")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    a = ok(api.add_record(hr, "career", "20301", {"content": "진로 발표", "title": "발표"}))["id"]
    b = ok(api.add_record(hr, "career", "20302", {"content": "진로 탐색"}))["id"]
    c = ok(api.add_record(hr, "career", "20303", {"content": "마감될 학생"}))["id"]
    d = ok(api.add_record(hr, "career", "20304", {"content": "확정한 기록"}))["id"]
    e = ok(api.add_record(hr, "career", "20302", {"content": "이미 쓴 생기부", "kind": "existing"}))
    ok(api.confirm_record(d, "확정본"))
    ok(api.edit_final(hr, "career", "20303", "최종안"))
    ok(api.set_closed(hr, "career", "20303", True))

    # 1) 대화 결과 → 그 기록의 결과 묶음(💬 대화 결과)
    ok(api.save_chat_result(a, "대화로 얻은 글", {"model": "1번 · m", "secret": "x"}))
    v = ok(api.student_view(hr, "career", "20301"))
    rec = next(r for r in v["records"] if r["id"] == a)
    top = rec["bundle"][0]
    assert top["op"] == "chat" and top["text"] == "대화로 얻은 글", top
    assert "secret" not in (top.get("meta") or {})
    assert not api.save_chat_result(a, "  ")["ok"]
    assert not api.save_chat_result(d, "확정된 기록에는 안 됨")["ok"]
    assert not api.save_chat_result(c, "마감 학생은 안 됨")["ok"]

    # 2) 대상 목록: 확정·마감·다른 종류 제외, 결과 수 표시
    t = ok(api.rec_ai_targets(hr, "career", "record"))
    ids = [x["id"] for x in t["records"]]
    assert ids == [a, b], ids
    assert t["records"][0]["results"] == 1 and t["records"][1]["results"] == 0
    assert t["skipped_closed"] == 1
    assert [x["text"] for x in ok(api.rec_ai_targets(hr, "career", "existing"))["records"]] == ["이미 쓴 생기부"]

    # 3) 저장한 프롬프트로 다른 학생 기록 변환(고른 프롬프트가 쓰임)
    pid = ok(api.prompt_save({"name": "대화 스킬", "prompt": "특별한-지침-XYZ", "example": "", "made": "스킬화", "tags": []}))["id"]
    api.ai_extra_set("", pid, "")
    try:
        ok(api.ai_record(b, 0))
    finally:
        api.ai_extra_set("", "", "")
    assert "특별한-지침-XYZ" in CALLS[-1]
    v = ok(api.student_view(hr, "career", "20302"))
    rb = next(r for r in v["records"] if r["id"] == b)
    assert rb["bundle"][0]["text"] == "변환 글" and rb["bundle"][0]["meta"]["prompt_name"] == "대화 스킬"
    assert rb["content"] == "진로 탐색"  # 원문은 그대로
    assert e

    # 4) 태그별 [최신 결과로 확정] + 되돌리기
    v = ok(api.student_view(hr, "career", "20302"))
    before = {r["id"]: (r["content"], r["original"], r["confirmed"]) for r in v["records"]}
    out = ok(api.confirm_many([[b, "변환 글"], [d, "이미 확정"], [c, "마감"], [a, ""]]))
    assert out["done"] == 1 and out["token"], out
    whys = {x["id"]: x["why"] for x in out["skipped"]}
    assert whys[d] == "이미 확정" and a in whys and c in whys, whys
    rb = next(r for r in ok(api.student_view(hr, "career", "20302"))["records"] if r["id"] == b)
    assert rb["confirmed"] and rb["content"] == "변환 글" and rb["orig"] == "진로 탐색"
    u = ok(api.undo_confirm_many(out["token"]))
    assert u["done"] == 1
    after = {r["id"]: (r["content"], r["original"], r["confirmed"]) for r in ok(api.student_view(hr, "career", "20302"))["records"]}
    assert after[b] == before[b], (after[b], before[b])
    assert not api.undo_confirm_many(out["token"])["ok"]  # 한 번만
    # 확정 뒤 다시 고쳤으면 되돌리지 않음
    out = ok(api.confirm_many([[b, "변환 글"]]))
    ok(api.confirm_record(b, "다시 고친 확정본"))
    assert ok(api.undo_confirm_many(out["token"]))["skipped"] == 1
    # 5) 예전 반영 이력 목록(없으면 빈 목록)
    assert ok(api.tag_legacy())["works"] == []


if __name__ == "__main__":
    test_all()
    print("test_rec_bulk OK")
