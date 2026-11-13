"""태그별 기록: 고른 기록의 활동명·날짜를 한꺼번에 바꾸고 되돌리기(마감·비활성 건너뜀, 그 뒤 바뀐 기록은 되돌리지 않음)."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_fields():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나\n20304\t최네모")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    rids = [ok(api.add_record(hr, "career", f"2030{i}", {"content": f"기록{i}", "title": "옛 이름"}))["id"] for i in range(1, 5)]
    ok(api.edit_final(hr, "career", "20303", "최종안"))
    ok(api.set_closed(hr, "career", "20303", True))
    ok(api.set_active(hr, ["20304"], False))
    r = ok(api.records_set_field(rids, "title", "  진로 독서  ", 2026))
    assert [p[0] for p in r["pairs"]] == rids[:2] and r["pairs"][0][1:] == ["옛 이름", "진로 독서"]
    assert r["states"][str(rids[0])]["title"] == "진로 독서"
    d = ok(api.records_set_field(rids[:2], "date", "2026-04-01", 2026))
    assert len(d["pairs"]) == 2
    assert not api.records_set_field(rids, "date", "4월 1일", 2026)["ok"]
    assert not api.records_set_field(rids, "content", "x", 2026)["ok"]
    # 같은 값이면 바뀐 것 없음
    assert ok(api.records_set_field(rids[:2], "title", "진로 독서", 2026))["pairs"] == []
    # 되돌리기: 그 뒤 다시 고친 기록은 건너뜀
    ok(api.update_record(rids[1], {"title": "따로 고침"}))
    u = ok(api.undo_records_field(r["pairs"], "title", 2026))
    assert (u["done"], u["changed"]) == (1, 1), u
    view = {x["id"]: x for x in ok(api.student_view(hr, "career", "20301"))["records"]}
    assert view[rids[0]]["title"] == "옛 이름"
    # 날짜 비우기
    e = ok(api.records_set_field(rids[:2], "date", "", 2026))
    assert all(p[2] == "" for p in e["pairs"]) and len(e["pairs"]) == 2


if __name__ == "__main__":
    test_fields()
    print("test_tag_fields OK")
