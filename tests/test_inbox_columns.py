"""인박스 열 역할·나이스 파일 자동 인식·반/번호 나누기·엑셀 시트 고르기(가짜 자료)."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openpyxl import Workbook
from app import config, roster
from app.api import Api
from app.inbox import cls_text, detect, interpret

NEIS_HEAD = ["학년도", "학기", "학년", "학생개인번호", "과목", "과목코드", "반/번호", "성명", "학적변동_x000D_\n구분", "세부능력 및 특기사항", "영재·발명교육 기록사항"]
NEIS = [NEIS_HEAD,
        ["2026", "1", "2", "2026000104", "공통수학1", "0003000012", "3/1", "김철수", "재학", "다항식 내용", ""],
        ["2026", "1", "2", "2026000103", "공통수학1", "0003000012", "3/2", "이영희", "재학", "방정식 내용", ""],
        ["2026", "1", "2", "2026000298", "공통수학1", "0003000012", "3/3", "박민수", "자퇴", "부등식 내용", ""],
        ["2026", "1", "2", "2026000003", "공통수학1", "0003000012", "3/4", "최하나", "재학", "행렬 내용", ""]]


def ok(r):
    assert r.get("ok"), r
    return r


def xlsx(path, sheets):
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets:
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    wb.save(path)
    return path


def test_units():
    o = detect(NEIS)
    assert o["neis"] and o["header"] and o["orient"] == "rows", o
    assert o["roles"] == {"2": "grade", "6": "clsnum", "7": "name", "8": "change", "9": "content"}, o["roles"]  # 학생개인번호·학년도는 안 씀
    recs = interpret(NEIS, {"structure": "multi", **o}, 2026)
    assert len(recs) == 4 and recs[0]["ext_no"] == "" and recs[0]["ext_cls"] == "2학년 3반 1번" and recs[0]["label"] == "세부능력 및 특기사항"
    # 사용자가 고른 역할: 학년·반·번호 따로, 내용 두 열
    raw = [["학년", "반", "번호", "이름", "1차", "2차", "비고"], ["2", "3", "2", "이영희", "가", "나", "x"]]
    recs = interpret(raw, {"structure": "multi", "orient": "rows", "header": True,
                           "roles": {"0": "grade", "1": "class_no", "2": "number", "3": "name", "4": "content", "5": "content"}}, 2026)
    assert [(r["ext_cls"], r["label"], r["content"]) for r in recs] == [("2학년 3반 2번", "1차", "가"), ("2학년 3반 2번", "2차", "나")]
    assert cls_text({"cls": "1반 7번"}) == "1반 7번"


def test_flow():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김철수\n20302\t이영희\n20303\t박민수\n20304\t최하나\n20305\t이영희")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))

    # 시트 여러 개: 빈 시트·안내 시트·나이스 시트
    path = xlsx(os.path.join(DATA, "세특.xlsx"), [("빈 시트", []), ("안내", [["이 파일은 시험용"]]), ("과목별세부능력및특기사항", NEIS)])
    sheets = roster.xlsx_sheets(path)
    assert [(x["name"], x["rows"]) for x in sheets] == [("빈 시트", 0), ("안내", 1), ("과목별세부능력및특기사항", 5)], sheets
    rows, pick = api._xlsx_pick(path)
    assert rows is None and pick["file"] == "세특.xlsx" and len(pick["sheets"]) == 3
    one = xlsx(os.path.join(DATA, "하나.xlsx"), [("빈", []), ("명단", [["20301", "김철수"]])])
    rows, pick = api._xlsx_pick(one)  # 내용 있는 시트가 하나면 묻지 않고 그 시트
    assert pick is None and rows == [["20301", "김철수"]]

    bid = ok(api.inbox_create("세특", hr, "career"))["id"]
    src = ok(api.inbox_source_xlsx(bid, api._xlsx_token(path), "과목별세부능력및특기사항"))
    assert src["opts"]["neis"] and len(src["raw"]) == 5
    assert not api.inbox_source_xlsx(bid, "없는표시", "x")["ok"]
    opts = {"structure": "multi", **src["opts"]}
    pv = ok(api.inbox_preview(bid, {**opts, "roles": None}))  # 방향·머리글을 바꾸면 다시 짐작
    assert pv["neis"] and pv["roles"] == src["opts"]["roles"] and len(pv["rows"]) == 4
    assert ok(api.inbox_import(bid, opts))["count"] == 4
    v = ok(api.inbox_view(bid))
    st = {r["ext_name"]: (r["student_no"], r["state"], r["note"], r["ext_cls"]) for r in v["rows"]}
    assert st["김철수"][:2] == ("20301", "confirmed") and st["김철수"][3] == "2학년 3반 1번", st
    assert st["이영희"][:2] == ("20302", "confirmed"), st  # 동명이인이지만 반/번호로 한 명
    assert st["박민수"][:2] == ("20303", "suggested") and "자퇴" in st["박민수"][2], st  # 학적변동은 확인 받기
    ok(api.inbox_rematch(bid))
    assert {r["ext_name"]: r["state"] for r in ok(api.inbox_view(bid))["rows"]}["이영희"] == "confirmed"
    # 학생 열을 하나도 고르지 않으면 가져오지 않음
    b2 = ok(api.inbox_create("x", hr, "career"))["id"]
    s2 = ok(api.inbox_source_xlsx(b2, api._xlsx_token(path), "과목별세부능력및특기사항"))
    assert not api.inbox_import(b2, {"structure": "multi", **s2["opts"], "roles": {"9": "content"}})["ok"]

    # 명렬: 시트 여러 개를 골라 시트마다 명렬 하나로
    rp = xlsx(os.path.join(DATA, "명렬.xlsx"), [("1반", [["학번", "이름"], ["20301", "김철수"]]), ("2반", [["학번", "이름"], ["20302", "이영희"]]), ("빈", [])])
    r = ok(api.roster_from_xlsx(api._xlsx_token(rp), ["1반", "2반"]))
    assert [f["file"] for f in r["files"]] == ["명렬.xlsx › 1반", "명렬.xlsx › 2반"] and r["ask"] == []

    # 이미 쓴 생기부: 고른 시트로
    gid = hr
    e = ok(api.existing_parse(gid, "career", None, True, api._xlsx_token(path), "과목별세부능력및특기사항"))
    assert e["columns"]["clsnum"] == 6 and e["columns"]["content"] == 9 and e["columns"]["change"] == 8, e["columns"]


if __name__ == "__main__":
    test_units()
    test_flow()
    print("test_inbox_columns OK")
