"""엑셀 전체 백업·복구: 저장 → 자료를 바꿈 → 엑셀로 복구하면 모든 표가 저장 때와 같아야 한다. 최종안만 파일은 복구 불가."""
import json
import os
import sqlite3
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, db, openrouter  # noqa: E402

openrouter.chat = lambda key, model, system, user, privacy_block=False, history=None: ("AI 결과 글", 0.0)
openrouter.balance = lambda key: 1.0
from app import xlsx_backup  # noqa: E402
from app.api import Api  # noqa: E402
from openpyxl import load_workbook  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def dump(year):
    db.open_year(year).checkpoint()
    con = sqlite3.connect(db.year_path(year))
    out = {}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        out[t] = sorted(json.dumps(list(r), ensure_ascii=False) for r in con.execute(f"SELECT * FROM {t}"))
    con.close()
    return out


def test_all():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    sub = ok(api.add_group({"kind": "subject", "name": "공통수학1", "semester": 1}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리")
    rows = api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]
    ok(api.roster_apply(hr, rows)); ok(api.roster_apply(sub, rows))
    tag = ok(api.add_tag("발표"))["id"]
    long_text = "가" * 40000 + "\n\x01제어문자\t탭"  # 엑셀 칸 한도·제어 문자
    r1 = ok(api.add_record(hr, "career", "20301", {"content": "=SUM(A1) 수식처럼 보이는 글", "title": "진로 발표", "date": "2026-05-01", "tag_ids": [tag]}))["id"]
    ok(api.add_record(hr, "career", "20302", {"content": long_text}))
    ok(api.ai_record(r1))
    ok(api.confirm_record(r1, "확정본 글"))
    ok(api.edit_final(hr, "career", "20301", "최종안 글입니다."))
    ok(api.set_closed(hr, "career", "20301", True))
    ok(api.edit_final(sub, "subject", "20302", "세특 최종안"))
    ok(api.standards_save(sub, "[10공수1-01-01] 성취기준", "붙여넣기"))
    before = dump(2026)

    full = os.path.join(DATA, "전체.xlsx")
    xlsx_backup.save(2026, full)
    wb = load_workbook(full)
    names = wb.sheetnames
    assert names[0] == "안내" and "진로활동" in names and "자율활동" in names and "세특_공통수학1(1학기)" in names and "명렬" in names
    assert wb["_복구_records"].sheet_state == "hidden" and "_복구_긴글" in names
    car = wb["진로활동"]
    vals = [c.value for c in car[2]]
    assert vals[:3] == ["20301", "김하나", "최종안"] and vals[7] == "마감" and vals[9] == "최종안 글입니다."
    assert any(r[0].value == "20301" and r[8].value == "=SUM(A1) 수식처럼 보이는 글" and r[8].data_type == "s" for r in car.iter_rows(min_row=2))
    wb.close()

    only = os.path.join(DATA, "최종안.xlsx")
    xlsx_backup.save(2026, only, only_final=True)
    wb = load_workbook(only)
    assert "_복구정보" not in wb.sheetnames and "명렬" not in wb.sheetnames
    head = [c.value for c in wb["진로활동"][1]]
    assert head[:5] == ["학번", "이름", "최종안", "바이트", "상태"]
    assert [c.value for c in wb["진로활동"][2]][:5][2:] == ["최종안 글입니다.", 24, "마감"] or [c.value for c in wb["진로활동"][2]][4] == "마감"
    wb.close()
    try:
        xlsx_backup.read_info(only)
        raise AssertionError("최종안만 파일은 복구 불가여야 함")
    except db.DbError:
        pass

    # 자료를 바꾼 뒤 엑셀로 복구 → 저장 때와 같음
    ok(api.set_closed(hr, "career", "20301", False))
    ok(api.edit_final(hr, "career", "20301", "바뀐 최종안"))
    ok(api.add_record(hr, "career", "20302", {"content": "나중에 더한 기록"}))
    assert dump(2026) != before
    api._xlsx_restore = full
    assert not api.xlsx_restore_run("확인")["ok"]
    out = ok(api.xlsx_restore_run("확인했어요"))
    assert out["year"] == 2026 and out["safety"]
    after = dump(2026)
    for t in before:
        assert before[t] == after[t], t
    v = ok(api.student_view(hr, "career", "20302"))
    assert any(r["content"] == long_text for r in v["records"])
    assert ok(api.student_view(hr, "career", "20301"))["final"]["closed"]

    # 숨김 시트를 건드리면(행 삭제) 멈추고 자료는 그대로
    wb = load_workbook(full)
    wb["_복구_records"].delete_rows(3)
    bad = os.path.join(DATA, "고친것.xlsx")
    wb.save(bad)
    api._xlsx_restore = bad
    r = api.xlsx_restore_run("확인했어요")
    assert not r["ok"] and "맞지 않습니다" in r["error"], r
    assert dump(2026) == after


if __name__ == "__main__":
    test_all()
    print("test_xlsx_backup OK")
