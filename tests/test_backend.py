import os, tempfile, sys
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, db, roster, backup, updater, openrouter, textutil
from app.api import Api

def test_all():
    # 설정
    c = config.load()
    assert c["models"][0] == config.FREE_MODEL and c["privacy_block"] is False
    config.save({"openrouter_key": "sk-test", "models": ["a"], "bogus": 1})
    c = config.load(); assert c["models"] == ["a", "", "", ""] and "bogus" not in c
    config.reset_keys(); assert config.load()["openrouter_key"] == ""

    api = Api()
    assert api.create_year(2026, "homeroom")["ok"]
    st = api.year_state(); assert st["year"] == 2026 and st["role"] == "homeroom"
    r = api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}); assert r["ok"], r
    hr = r["id"]
    assert not api.add_group({"kind": "homeroom", "grade": 2, "class_no": 4})["ok"]
    sub = api.add_group({"kind": "subject", "name": "공통수학1", "semester": 1, "level_scale": 5})["id"]
    assert not api.add_group({"kind": "subject", "name": "공통수학1", "semester": 2})["ok"]
    club = api.add_group({"kind": "club", "name": "과학탐구"})["id"]

    # 명렬 붙여넣기(머리글 있음, 학년/반/번호 열)
    text = "학년\t반\t번호\t성명\n2\t3\t1\t김철수\n2\t3\t2\t이영희\n2\t3\t2\t박민수\n"
    p = api.roster_from_text(text); assert p["ok"] and p["header"]
    b = api.roster_build(hr, p["raw"], p["header"], p["columns"]); rows = b["rows"]
    assert rows[0]["student_no"] == "20301"
    assert "학번 중복" in rows[1]["issues"] and "학번 중복" in rows[2]["issues"]
    assert not api.roster_apply(hr, rows)["ok"]
    rows[2]["student_no"] = "20303"; rows[2]["grade"] = rows[2]["class_no"] = ""
    v = api.roster_validate(hr, rows)["rows"]; assert all(not r["issues"] for r in v), v
    a = api.roster_apply(hr, v); assert a["ok"] and a["count"] == 3

    # 다른 반 학생 → 담임 명렬에서 막힘
    p = api.roster_from_text("20401\t최가람"); b = api.roster_build(hr, p["raw"], p["header"], p["columns"])
    assert any("다른 반" in i for i in b["rows"][0]["issues"])

    # 과목 명렬: 학번만, 수준 열 자동 탐지, 머리글 없음
    p = api.roster_from_text("20301\t김철수\tB\n20501\t정다은\tF\n")
    assert p["columns"]["level"] == 2 and not p["header"]
    b = api.roster_build(sub, p["raw"], p["header"], p["columns"])
    assert any("범위 밖" in n for n in b["rows"][1]["notes"])
    assert api.roster_apply(sub, b["rows"])["ok"]
    # 같은 학번 이름 다르면 알림
    b2 = api.roster_build(club, *[api.roster_from_text("20301\t김철순\n30102\t한별")[k] for k in ("raw", "header", "columns")])
    assert any("기존 이름 김철수 → 김철순" in i for i in b2["rows"][0]["issues"])  # 이름 바뀜은 확인해야 반영
    rows2 = b2["rows"]; rows2[0]["rename_ok"] = True
    assert not api.roster_validate(club, rows2)["rows"][0]["issues"]
    assert "3학년: 1학기 마감 대상" in b2["rows"][1]["notes"]

    # 비활성화: 소속별 / 전출
    api.set_active(sub, ["20301"], False)
    m = {x["student_no"]: x["active"] for x in api.members(hr)["members"]}; assert m["20301"] == 1
    api.set_active(sub, ["20301"], False, True)
    m = {x["student_no"]: x["active"] for x in api.members(hr)["members"]}; assert m["20301"] == 0

    # 일정·분량
    assert api.add_schedule("2026-12-10", "자율 마감")["ok"]
    assert not api.add_schedule("", "x")["ok"]
    assert api.year_state()["targets"]["behavior"] == 900

    # 현황판
    dsh = api.dashboard(); assert dsh["ok"]; assert len(dsh["groups"]) == 3
    hrg = dsh["groups"][0]; assert hrg["items"] == ["autonomy", "career", "behavior"] and hrg["summary"]["students"] == 2
    api.set_role("subject"); assert all(g["kind"] != "homeroom" for g in api.dashboard()["groups"])
    assert "숨겨집니다" in api.role_change_preview("subject")["message"] or api.role_change_preview("subject")["message"] == ""

    # 백업·복원
    bk = api.backup_now(); assert bk["ok"]
    api.add_schedule("2026-12-20", "추가")
    assert len(api.year_state()["schedules"]) == 2
    rs = api.restore_backup(bk["name"]); assert rs["ok"], rs
    assert len(api.year_state()["schedules"]) == 1

    # 삭제 확인
    assert not api.delete_year(2026, "2026")["ok"]
    assert api.delete_year(2026, "2026학년도")["ok"]
    assert db.list_years() == []

    # 업데이트 버전 비교, 페이로드
    assert updater.is_newer("v0.2.0", "0.1.0") and not updater.is_newer("v0.1.0", "0.1.0") and updater.is_newer("v0.1.1", "0.1.0")
    pl = openrouter.build_payload("x", "s", "u", True); assert pl["provider"] == {"data_collection": "deny", "zdr": True}
    assert "provider" not in openrouter.build_payload("x", "s", "u", False)
    assert "학습 차단" in openrouter._explain(404, "No endpoints found", True)
    assert textutil.count_bytes("가a 1") == 6
    print("ALL OK")

if __name__ == "__main__":
    test_all()
