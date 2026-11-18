"""나이스 행동특성 누가기록(v0.23): 쪽마다 머리글·쪽 번호, 번호·성명 세로 병합, 쪽에서 잘린 글 잇기, 줄마다 일자,
민감 정보(분류 제외·이름 가리기·경고), 인박스 가져오기→매칭→보내기."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, nuga  # noqa: E402
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def make_xlsx(path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws["F3"] = "행동특성 누가기록"
    ws["B5"] = "2026학년도 1학년 4반"
    r = 7

    def head():
        nonlocal r
        ws.cell(r, 2, "번호"); ws.cell(r, 3, "성명"); ws.cell(r, 4, "일자"); ws.cell(r, 5, "행동특성내용")
        ws.merge_cells(start_row=r, start_column=5, end_row=r, end_column=18)
        r += 1

    def put(no, name, items):
        nonlocal r
        top = r
        for d, t in items:
            ws.cell(r, 4, d); ws.cell(r, 5, t)
            ws.merge_cells(start_row=r, start_column=5, end_row=r, end_column=18)
            r += 1
        ws.cell(top, 2, no); ws.cell(top, 3, name)
        if r - top > 1:
            ws.merge_cells(start_row=top, start_column=2, end_row=r - 1, end_column=2)
            ws.merge_cells(start_row=top, start_column=3, end_row=r - 1, end_column=3)

    def page(n, m):
        nonlocal r
        r += 2
        ws.cell(r, 7, str(n)); ws.cell(r, 8, "/"); ws.cell(r, 9, str(m))
        r += 3

    head()
    put("1", "김하나", [("2026.03.05.", "학기초 상담 진행. 진로 고민을 나눔."), ("2026.05.14.", "쉬는 시간에 학급 문고를 정리함. 이두리와 함께 정리함."),
                       ("2026.06.10.", "복장 불량으로 지도카드 받음.")])
    put("2", "이두리", [("2026.03.09.", "학급자치회 부회장에 당선됨."), ("2026.05.20.", "")])
    put("3", "박세나", [("2026.06.01.", "체육대회에서 친구들을 끝까지 응원함. 여러 모로 ")])
    page(1, 2)
    head()
    put("3", "박세나", [("", "본받을 만함.")])  # 쪽에서 잘린 글
    ws.cell(r - 1, 4, "")
    put("3", "박세나", [("2026.10.12.", "사회 100점을 맞음. 하나 덕분이라고 함.")])
    put("4", "최네모", [("2026.04.01.", "경찰대학교 진학을 희망하며 체력 관리를 꾸준히 함.")])
    page(2, 2)
    wb.save(path)


def test_all():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 1, "class_no": 4}))["id"]
    p = api.roster_from_text("10401\t김하나\n10402\t이두리\n10403\t박세나\n10404\t최네모")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    path = os.path.join(DATA, "누가기록.xlsx")
    make_xlsx(path)

    rows = nuga.read_xlsx(path)
    assert nuga.is_nuga(rows)
    table, info = nuga.convert(rows)
    assert table[0] == nuga.OUT_HEAD
    assert info == {"students": 4, "entries": 7, "joined": 1, "empty": 1, "grade": 1, "class_no": 4}, info
    seo = [x for x in table if x[2] == "3"]
    assert seo[0][5] == "체육대회에서 친구들을 끝까지 응원함. 여러 모로 본받을 만함." and seo[0][3] == "박세나"
    assert seo[1][4] == "2026-10-12"
    assert nuga.categories("학부모 상담 진행") == ["counsel"] and nuga.categories("경찰대학교 희망") == [] and "score" in nuga.categories("사회 100점")
    assert nuga.categories("점심시간에 도서관에 감") == []

    bid = ok(api.inbox_create("누가기록", hr, "behavior"))["id"]
    tok = api._xlsx_token(path)
    src = ok(api.inbox_source_xlsx(bid, tok, None))
    o = src["opts"]
    assert o["nuga"]["entries"] == 7 and o["roles"]["4"] == "date" and o["sens"] == list(nuga.CAT_KEYS)
    prev = ok(api.inbox_preview(bid, o))["rows"]
    assert len(prev) == 7 and prev[0]["date"] == "2026-03-05" and prev[0]["ext_name"] == "김하나"
    o["sens"] = ["counsel", "discipline", "family"]  # 성적 점수는 빼지 않음
    assert ok(api.inbox_import(bid, o))["count"] == 7
    v = ok(api.inbox_view(bid))
    by = {(r["student_no"], r["date"]): r for r in v["rows"]}
    assert by[("10401", "2026-03-05")]["state"] == "excluded" and by[("10401", "2026-03-05")]["exclude_reason"] == "민감 정보(상담)"
    assert by[("10401", "2026-06-10")]["exclude_reason"] == "민감 정보(징계·출결)"
    clean = by[("10401", "2026-05-14")]
    assert clean["state"] == "confirmed" and "○○와 함께" in clean["content"] and "이두리" not in clean["content"] and "○○으로 가림" in clean["note"]
    sc = by[("10403", "2026-10-12")]
    assert sc["state"] == "confirmed" and "하나" in sc["note"]  # 성 뺀 이름 경고, 점수는 빼지 않음
    assert by[("10404", "2026-04-01")]["state"] == "confirmed"
    assert v["counts"]["excluded"] == 2 and v["counts"]["confirmed"] == 5
    # 보내기: 줄마다 날짜가 기록 날짜로
    ok(api.inbox_stage(bid, "refine")); ok(api.inbox_stage(bid, "review"))
    ok(api.inbox_send(bid))
    recs = ok(api.student_view(hr, "behavior", "10403"))["records"]
    assert sorted(r["date"] for r in recs) == ["2026-06-01", "2026-10-12"]

    # 행특의 모든 AI 변환에 고정 지침(부정 → 긍정·변화 가능성), 다른 항목에는 없음
    from app import openrouter
    sent = []
    openrouter.chat = lambda key, model, system, user, privacy_block=False, history=None: (sent.append(system) or "결과", 0.0)
    openrouter.balance = lambda key: 1.0
    ok(api.ai_record(recs[0]["id"]))
    assert "[행동특성 및 종합의견 — 항상 지킴" in sent[-1] and "변화 가능성" in sent[-1]
    long = ok(api.add_record(hr, "behavior", "10403", {"content": "수업 중 장난을 침. " * 120}))["id"]
    ok(api.ai_synth(hr, "behavior", "10403", [long], {str(long): 100}))
    assert all("항상 지킴" in x for x in sent[1:])
    cr = ok(api.add_record(hr, "career", "10403", {"content": "진로 탐색"}))["id"]
    ok(api.ai_record(cr))
    assert "항상 지킴" not in sent[-1]


if __name__ == "__main__":
    test_all()
    print("test_nuga OK")
