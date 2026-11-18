"""등록된 학생 고치기(v0.23): 이름·학년·반·번호·수업, 학번 바꾸기(모든 담당의 자료 옮김, 맞바꾸기), 검사."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config  # noqa: E402
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def row(m, **kw):
    r = {"orig_no": m["student_no"], "student_no": m["student_no"], "name": m["name"], "grade": m["grade"], "class_no": m["class_no"], "number": m["number"], "section": m["section"]}
    r.update(kw)
    return r


def test_all():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    sub = ok(api.add_group({"kind": "subject", "name": "물리", "grade": 2, "semester": 1}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나")
    for gid in (hr, sub):
        ok(api.roster_apply(gid, api.roster_build(gid, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.add_record(hr, "career", "20301", {"content": "진로 발표"}))
    ok(api.add_record(sub, "subject", "20301", {"content": "물리 실험"}))
    ok(api.add_record(hr, "career", "20302", {"content": "두리 기록"}))
    ms = {m["student_no"]: m for m in api.members(sub)["members"]}

    # 이름·번호·수업 고치기(학번 그대로): 백업 없이 바로
    r = ok(api.roster_edit_apply(sub, [row(ms["20303"], name="박세나나", section="A반")]))
    assert r["moved"] == 0 and "backup" not in r
    m = {x["student_no"]: x for x in api.members(sub)["members"]}["20303"]
    assert m["name"] == "박세나나" and m["section"] == "A반"
    assert {x["student_no"]: x for x in api.members(hr)["members"]}["20303"]["name"] == "박세나나"  # 모든 소속에 반영

    # 이미 쓰는 학번으로는 못 바꿈
    v = ok(api.roster_edit_validate(sub, [row(ms["20301"], student_no="20302")]))["rows"][0]
    assert any("이미 있는 학번" in x for x in v["issues"])
    assert not api.roster_edit_apply(sub, [row(ms["20301"], student_no="20302")]).get("ok")

    # 학번 바꾸기: 모든 담당의 소속·기록이 옮겨짐, 백업
    r = ok(api.roster_edit_apply(sub, [row(ms["20301"], student_no="20401", grade="2", class_no="4", number="1")]))
    assert r["moved"] == 1 and r["backup"]
    assert "20301" not in {x["student_no"] for x in api.members(hr)["members"]}
    assert "20401" in {x["student_no"] for x in api.members(hr)["members"]}
    assert len(api.student_view(hr, "career", "20401")["records"]) == 1
    assert len(api.student_view(sub, "subject", "20401")["records"]) == 1

    # 맞바꾸기(20302 ↔ 20303)
    ms = {m["student_no"]: m for m in api.members(sub)["members"]}
    rows = [row(ms["20302"], student_no="20303", number="3"), row(ms["20303"], student_no="20302", number="2")]
    v = ok(api.roster_edit_validate(sub, rows))["rows"]
    assert all(not x["issues"] for x in v), v
    ok(api.roster_edit_apply(sub, rows))
    ms = {m["student_no"]: m for m in api.members(hr)["members"]}
    assert ms["20303"]["name"] == "이두리" and ms["20302"]["name"] == "박세나나"
    assert api.student_view(hr, "career", "20303")["records"][0]["content"] == "두리 기록"

    # 담임반: 다른 반이면 막음
    v = ok(api.roster_edit_validate(hr, [row(ms["20302"], class_no="5")]))["rows"][0]
    assert any("다른 반" in x for x in v["issues"])


if __name__ == "__main__":
    test_all()
    print("test_roster_edit OK")
