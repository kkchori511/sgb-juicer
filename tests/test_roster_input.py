"""v0.10 명렬 입력: 이어서 추가·전입 한 줄·전출 삭제/비활성·여러 파일 읽기."""
import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config
from app.api import Api

TMP = tempfile.mkdtemp()


def ok(r):
    assert r.get("ok"), r
    return r


class W:
    files = ()
    def create_file_dialog(self, *a, **k):
        assert k.get("allow_multiple")
        return self.files
    def evaluate_js(self, js): pass


def add(api, gid, text, mode="add"):
    p = ok(api.roster_from_text(text))
    rows = ok(api.roster_build(gid, p["raw"], p["header"], p["columns"], True))["rows"]
    return ok(api.roster_apply(gid, rows, mode))


if __name__ == "__main__":
    config.save({"openrouter_key": "sk"})
    w = W(); api = Api(); api.attach(w)
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    sub = ok(api.add_group({"kind": "subject", "name": "수학", "semester": 1}))["id"]
    # 1) 붙여넣기 두 번 + 파일 두 개를 섞어 넣어도 앞의 학생이 빠지지 않음
    add(api, sub, "20301\t김철수\n20302\t이영희")
    add(api, sub, "학년\t반\t번호\t이름\n2\t4\t1\t박민수")
    import openpyxl
    for i, (no, nm) in enumerate([("20501", "최가람"), ("20601", "정다은")]):
        wb = openpyxl.Workbook(); wb.active.append(["학번", "이름"]); wb.active.append([int(no), nm]); wb.save(os.path.join(TMP, f"반{i}.xlsx"))
    with open(os.path.join(TMP, "반2.csv"), "w", encoding="cp949") as f:
        f.write("학번,이름\n20701,한별\n")
    w.files = tuple(os.path.join(TMP, n) for n in ("반0.xlsx", "반1.xlsx", "반2.csv"))
    r = ok(api.roster_from_xlsx())
    assert [f["file"] for f in r["files"]] == ["반0.xlsx", "반1.xlsx", "반2.csv"], r
    rows = []
    for f in r["files"]:
        rows += ok(api.roster_build(sub, f["raw"], f["header"], f["columns"], True))["rows"]
    ok(api.roster_apply(sub, rows, "add"))
    nos = [m["student_no"] for m in ok(api.members(sub))["members"]]
    assert nos == ["20301", "20302", "20401", "20501", "20601", "20701"], nos
    # 이미 있는 학생은 알림만(막지 않음), 성취수준은 덮어쓰지 않음
    ok(api.set_level(sub, "20301", "B"))
    rows = ok(api.roster_build(sub, [["20301", "김철수"]], False, {"student_no": 0, "name": 1}, True))["rows"]
    assert not rows[0]["issues"] and any("이미 명렬에 있음" in n for n in rows[0]["notes"]), rows
    ok(api.roster_apply(sub, rows, "add"))
    assert [m for m in ok(api.members(sub))["members"] if m["student_no"] == "20301"][0]["level"] == "B"
    # 2) 전입: 한 줄
    add(api, hr, "20301\t김철수\n20302\t이영희")
    ok(api.roster_apply(hr, [{"student_no": "20315", "name": "전입생"}], "add"))
    assert "20315" in [m["student_no"] for m in ok(api.members(hr))["members"]]
    # 3) 전출: 비활성 / 삭제(기록도 지움, 백업)
    ok(api.set_active(hr, ["20302"], False, True))
    assert not [m for m in ok(api.members(sub))["members"] if m["student_no"] == "20302"][0]["active"]
    ok(api.add_record(hr, "career", "20301", {"content": "기록"}))
    ok(api.edit_final(hr, "career", "20301", "최종안"))
    im = ok(api.member_impact(hr, ["20301"], True))
    assert im["records"] == 1 and im["finals"] == 1, im
    r = ok(api.remove_members(hr, ["20301"], True))
    assert r["removed"] == 2 and r["backup"], r  # 담임반·수학 두 소속
    assert "20301" not in [m["student_no"] for m in ok(api.members(hr))["members"]]
    assert "20301" not in [m["student_no"] for m in ok(api.members(sub))["members"]]
    assert not api.student_view(hr, "career", "20301")["ok"]
    # 4) 바꾸기 모드는 그대로(첫 등록 마법사 등)
    res = add(api, hr, "20315\t전입생", mode="replace")
    assert res["count"] == 1
    # 5) v0.11: 반·번호·이름(학년 열 없음) + 정해 준 학년, 한 줄 입력의 학번 자동, 다른 담당 명렬 복사(활성만)
    rows = ok(api.roster_build(sub, [["5", "3", "홍길동"]], False, {"class_no": 0, "number": 1, "name": 2, "grade_value": "2"}, True))["rows"]
    assert rows[0]["student_no"] == "20503" and not rows[0]["issues"], rows
    v = ok(api.roster_validate(sub, [{"grade": "2", "class_no": "5", "number": "4", "name": "임꺽정"}], True))["rows"][0]
    assert v["student_no"] == "20504" and not v["issues"], v
    club = ok(api.add_group({"kind": "club", "name": "과학반"}))["id"]
    src = ok(api.roster_copy_source(sub))
    assert "20302" not in [r["student_no"] for r in src["rows"]] and src["label"] == "수학", src  # 20302는 비활성
    ok(api.roster_apply(club, src["rows"], "add"))
    assert len(ok(api.members(club))["members"]) == len(src["rows"])
    # 6) 내보내기 칸: 학년·반·번호·이름·상태·최종안·바이트
    from app import export
    assert [c[1] for c in export.columns("full")] == ["학년", "반", "번호", "이름", "상태", "최종안", "바이트"]
    ex = ok(api.export_preview(club, "club"))["rows"][0]
    assert ex["number"] is not None and ex["grade"] is not None, ex
    # 7) v0.14 선택과목 수업: 명렬 입력 때 지정, 나중에 바꾸기, 비우면 유지(추가 입력), 다른 담당 가져오기에 따라감
    ok(api.roster_apply(sub, [{"student_no": "20681", "name": "물리일", "section": "물리 A반"}, {"student_no": "20682", "name": "물리이", "section": "물리 B반"}], "add"))
    sec = {m["student_no"]: m["section"] for m in ok(api.members(sub))["members"]}
    assert sec["20681"] == "물리 A반" and sec["20682"] == "물리 B반", sec
    ok(api.roster_apply(sub, [{"student_no": "20681", "name": "물리일"}], "add"))  # 수업 칸이 비면 그대로
    assert {m["student_no"]: m["section"] for m in ok(api.members(sub))["members"]}["20681"] == "물리 A반"
    assert ok(api.set_section(sub, ["20681", "20682"], "물리 C반"))["changed"] == 2
    assert {m["section"] for m in ok(api.members(sub))["members"] if m["student_no"] in ("20681", "20682")} == {"물리 C반"}
    assert ok(api.slot_view(sub, "subject"))["students"][0].get("section") is not None
    assert any(r["section"] == "물리 C반" for r in ok(api.roster_copy_source(sub))["rows"])
    ok(api.set_section(sub, ["20681"], ""))
    assert {m["student_no"]: m["section"] for m in ok(api.members(sub))["members"]}["20681"] == ""
    # 직접 입력: 여러 모양을 읽고 확인까지(고친 값은 roster_validate로 다시 확인)
    from app import roster as R
    got = R.parse_lines("20301 김철수\n\n2 3 2 이영희\n2학년 3반 3번 박민수\n2-3-4\t최가람\n홍길동")
    assert [(x["line"], x["student_no"], x["grade"], x["class_no"], x["number"], x["name"]) for x in got] == [
        (1, "20301", "", "", "", "김철수"), (3, "", "2", "3", "2", "이영희"), (4, "", "2", "3", "3", "박민수"), (5, "", "2", "3", "4", "최가람"), (6, "", "", "", "", "홍길동")]
    dr = ok(api.roster_direct(sub, "2 3 2 이영희\n홍길동"))["rows"]
    assert dr[0]["student_no"] == "20302" and dr[0]["line"] == 1 and dr[1]["issues"], dr
    fixed = ok(api.roster_validate(sub, [{**dr[1], "student_no": "20399"}], True))["rows"][0]
    assert fixed["student_no"] == "20399" and not [i for i in fixed["issues"] if "학번" in i], fixed
    ok(api.save_now())
    print("ROSTER INPUT OK")
