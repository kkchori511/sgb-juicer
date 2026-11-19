"""이미 쓴 생기부를 [그대로 최종안으로]·[기존 완성문 → 최종안 일괄]로 보내면 그 기록이 확정으로 잡히는지(학생 목록 '확정/전체')."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config  # noqa: E402
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def counts(api, gid, item):
    return {s["student_no"]: (s.get("confirmed", 0), s["records"]) for s in ok(api.slot_view(gid, item))["students"]}


def test_all():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    a = ok(api.add_record(hr, "autonomy", "20301", {"kind": "existing", "content": "이미 쓴 생기부 하나"}))["id"]
    b = ok(api.add_record(hr, "autonomy", "20302", {"kind": "existing", "content": "이미 쓴 생기부 둘"}))["id"]
    c = ok(api.add_record(hr, "autonomy", "20303", {"kind": "existing", "content": "이미 쓴 생기부 셋"}))["id"]
    assert counts(api, hr, "autonomy") == {"20301": (0, 1), "20302": (0, 1), "20303": (0, 1)}

    # 1) [그대로 최종안으로](바꾸기): 최종안이 생기고 기록은 확정, 최종안에 '채택 후 기록 변경' 표시가 붙지 않음
    ok(api.adopt_record(a))
    v = ok(api.student_view(hr, "autonomy", "20301"))
    assert v["final"]["text"] == "이미 쓴 생기부 하나" and not v["final"]["stale"]
    assert v["records"][0]["confirmed"] and v["records"][0]["content"] == "이미 쓴 생기부 하나"
    assert counts(api, hr, "autonomy")["20301"] == (1, 1)
    ok(api.adopt_record(a))  # 다시 해도 그대로
    assert counts(api, hr, "autonomy")["20301"] == (1, 1)

    # 2) 이어 붙이기 등 다른 방식 뒤 확정 표시만
    ok(api.final_append(hr, "autonomy", "20302", "이미 쓴 생기부 둘", 2026))
    ok(api.mark_record_confirmed(b))
    v = ok(api.student_view(hr, "autonomy", "20302"))
    assert v["records"][0]["confirmed"] and not v["final"]["stale"]
    assert counts(api, hr, "autonomy")["20302"] == (1, 1)

    # 3) 기존 완성문 → 최종안 일괄: 확정으로, 되돌리면 확정도 풀림(글은 그대로)
    ok(api.finals_from_existing(hr, "autonomy", [{"student_no": "20303", "record_id": c}]))
    assert counts(api, hr, "autonomy")["20303"] == (1, 1)
    assert not ok(api.student_view(hr, "autonomy", "20303"))["final"]["stale"]
    ok(api.finals_bulk_undo())
    v = ok(api.student_view(hr, "autonomy", "20303"))
    assert v["final"] is None and not v["records"][0]["confirmed"] and v["records"][0]["content"] == "이미 쓴 생기부 셋"
    assert counts(api, hr, "autonomy")["20303"] == (0, 1)

    # 4) 확정된 기록을 다시 그대로 최종안으로 보내도 확정 그대로, 마감까지
    ok(api.set_closed(hr, "autonomy", "20301", True))
    assert counts(api, hr, "autonomy")["20301"] == (1, 1)
    print("ALL OK")


if __name__ == "__main__":
    test_all()
