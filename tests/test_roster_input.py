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
    print("ROSTER INPUT OK")
