"""v0.12 이미 쓴 생기부 가져오기(NEIS 형식·반/번호·이름만) + 줄 순서 바꾸기."""
import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, existing, openrouter
from app.api import Api

openrouter.chat = lambda key, model, system, user, privacy_block=False: ("결과", 0.0)
openrouter.balance = lambda key: 1.0
SENT = []


class W:
    def create_file_dialog(self, *a, **k): return ()
    def evaluate_js(self, js): pass


def ok(r):
    assert r.get("ok"), r
    return r


M = [{"student_no": "20101", "name": "김철수", "grade": 2, "class_no": 1, "number": 1, "active": 1},
     {"student_no": "20102", "name": "이영희", "grade": 2, "class_no": 1, "number": 2, "active": 1},
     {"student_no": "20201", "name": "김철수", "grade": 2, "class_no": 2, "number": 1, "active": 1},
     {"student_no": "20202", "name": "박민수", "grade": 2, "class_no": 2, "number": 2, "active": 1}]


def test_parse():
    # NEIS 공식 업로드 파일 머리글
    raw = [["학년도", "학기", "학생개인번호", "과목", "과목코드", "반/번호", "성명", "학적변동 구분", "내용"],
           ["2026", "1", "1234567890", "수학", "M01", "1/2", "이영희", "", "수학 내용"],
           ["2026", "1", "1234567891", "수학", "M01", "2/1", "김철수", "전출", "다른 반 철수"]]
    d = existing.detect(raw)
    c = d["columns"]
    assert d["header"] and c["clsnum"] == 5 and c["name"] == 6 and c["content"] == 8 and c["change"] == 7 and c["student_no"] is None, d
    rows = existing.build(raw, True, c, M)
    assert [(r["student_no"], r["state"]) for r in rows] == [("20102", "confirmed"), ("20201", "confirmed")], rows  # 동명이인을 반/번호로 가림
    assert rows[1]["change"] == "전출"
    # 이름·내용 두 칸만(머리글 없음)
    raw = [["이영희", "긴 내용입니다 " * 5], ["박민수", "또 다른 긴 내용 " * 5], ["김철수", "동명이인 내용 " * 5]]
    d = existing.detect(raw)
    assert d["columns"]["name"] == 0 and d["columns"]["content"] == 1, d
    rows = existing.build(raw, d["header"], d["columns"], M)
    assert [r["state"] for r in rows] == ["confirmed", "confirmed", "none"], rows
    assert "동명이인" in rows[2]["note"]
    # 반/번호 여러 표기
    assert existing.class_options("1/1", None) == [(None, 1, 1)]
    assert existing.class_options("1반 2번", None) == [(None, 1, 2)]
    assert existing.class_options("2-1-3", None) == [(2, 1, 3)]
    assert existing.class_options("1-1", None) == [(None, 1, 1), (1, 1, None)]  # 반-번호일 수도, 학년-반일 수도
    assert existing.class_options("2-1", "gradecls") == [(2, 1, None)]
    # '1-1'(머리글 없음): 반-번호로 읽어 김철수(2-1-1)와 맞으면 확정
    raw = [["1-1", "김철수", "가 " * 30], ["2-2", "김철수", "나 " * 30]]
    d = existing.detect(raw)
    rows = existing.build(raw, d["header"], d["columns"], M)
    assert [(r["student_no"], r["state"]) for r in rows] == [("20101", "confirmed"), ("20201", "confirmed")], rows
    # 이름은 같은데 반·번호가 다름 → 추천
    rows = existing.build([["3/9", "이영희", "내용"]], False, {"clsnum": 0, "name": 1, "content": 2}, M)
    assert rows[0]["state"] == "suggested" and "반·번호가 다름" in rows[0]["note"], rows


def test_api_and_reorder():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api(); api.attach(W())
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 1}))["id"]
    ok(api.roster_apply(hr, [{"student_no": "20101", "name": "김철수"}, {"student_no": "20102", "name": "이영희"}], "add"))
    pz = ok(api.existing_parse(hr, "behavior", "반/번호\t성명\t내용\n1/1\t김철수\t행특 내용\n1/2\t이영희\t다른 내용"))
    b = ok(api.existing_build(hr, "behavior", pz["raw"], pz["header"], pz["columns"]))
    assert [r["state"] for r in b["rows"]] == ["confirmed", "confirmed"] and len(b["members"]) == 2
    assert ok(api.existing_apply(hr, "behavior", b["rows"]))["count"] == 2
    # 학생관찰기록 순서 바꾸기 → 종합 때 그 순서로 보냄
    ids = [ok(api.add_record(hr, "career", "20101", {"content": f"기록{i}"}))["id"] for i in range(3)]
    ok(api.reorder_records(hr, "career", "20101", [ids[2], ids[0], ids[1]]))
    got = [r["id"] for r in ok(api.student_view(hr, "career", "20101"))["records"]]
    assert got == [ids[2], ids[0], ids[1]], got
    assert not api.reorder_records(hr, "career", "20101", ids[:2])["ok"]  # 목록이 다르면 거부
    sent = []
    openrouter.chat = lambda key, model, system, user, privacy_block=False: (sent.append(user) or "결과", 0.0)
    ok(api.ai_synth(hr, "career", "20101", ids, {}))
    assert sent[-1].index("기록2") < sent[-1].index("기록0") < sent[-1].index("기록1"), sent[-1]
    ok(api.add_record(hr, "career", "20101", {"content": "새 기록"}))  # 새 기록은 맨 뒤
    assert ok(api.student_view(hr, "career", "20101"))["records"][-1]["content"] == "새 기록"
    # 인박스 행 순서
    bid = ok(api.inbox_create("순서", hr, "career"))["id"]
    s = ok(api.inbox_source_text(bid, "학번\t이름\t내용\n20101\t김철수\t첫째\n20102\t이영희\t둘째"))
    ok(api.inbox_import(bid, {"structure": "multi", **s["opts"]}))
    rows = ok(api.inbox_view(bid))["rows"]
    ok(api.inbox_reorder(bid, [rows[1]["id"], rows[0]["id"]]))
    assert [r["content"] for r in ok(api.inbox_view(bid))["rows"]] == ["둘째", "첫째"]
    return hr


def test_record_bulk_and_finals(hr):
    """v0.13: 학생관찰기록 일괄 입력(한 학생 여러 줄·회차 이어 붙임·날짜는 기본 안 씀) + 기존 완성문 → 최종안 일괄."""
    assert existing.norm_date("2026.3.5") == "2026-03-05" and existing.norm_date("2026-03-05 00:00:00") == "2026-03-05"
    assert existing.norm_date("2026년 3월 5일") == "2026-03-05" and existing.norm_date("3월") == ""
    raw = [["이름", "날짜", "활동명", "내용"], ["김철수", "2026.4.1", "독서", "첫 기록"], ["김철수", "2026.4.2", "토론", "둘째 기록"]]
    d = existing.detect(raw)
    c = d["columns"]
    assert c["title"] == 2 and c["date"] is None and c["content"] == 3, c  # 날짜는 머리글이 있어도 기본 (없음)
    api = Api(); api.attach(W())
    ok(api.roster_apply(hr, [{"student_no": "20103", "name": "박민수"}, {"student_no": "20104", "name": "최다희"}, {"student_no": "20105", "name": "정우성"}], "add"))
    ok(api.add_record(hr, "autonomy", "20101", {"content": "직접 쓴 기록"}))
    b = ok(api.existing_build(hr, "autonomy", raw, True, {**c, "date": 1}))
    assert b["rows"][0]["date"] == "2026-04-01" and b["rows"][1]["title"] == "토론"
    r = ok(api.existing_apply(hr, "autonomy", b["rows"], "record"))
    assert r["count"] == 2 and r["students"] == 1, r
    recs = ok(api.student_view(hr, "autonomy", "20101"))["records"]
    assert [(x["seq"], x["kind"], x["date"], x["title"]) for x in recs] == [(1, "record", "", ""), (2, "record", "2026-04-01", "독서"), (3, "record", "2026-04-02", "토론")], recs
    # 이미 쓴 생기부는 여전히 학생당 한 줄
    e = api.existing_apply(hr, "autonomy", [{"student_no": "20103", "content": "a"}, {"student_no": "20103", "content": "b"}])
    assert not e["ok"] and "두 줄" in e["error"], e
    # 기존 완성문 → 최종안 일괄
    ok(api.existing_apply(hr, "autonomy", [{"student_no": "20103", "content": "박 옛 글"}, {"student_no": "20104", "content": "최 옛 글"}, {"student_no": "20105", "content": "정 옛 글"}]))
    ok(api.existing_apply(hr, "autonomy", [{"student_no": "20103", "content": "박 새 글"}]))  # 박민수는 두 개
    ok(api.edit_final(hr, "autonomy", "20104", "최 지금 최종안"))
    ok(api.edit_final(hr, "autonomy", "20105", "정 마감본")); ok(api.set_closed(hr, "autonomy", "20105", True))
    v = {x["student_no"]: x for x in ok(api.finals_bulk_view(hr, "autonomy"))["students"]}
    assert [e["content"] for e in v["20103"]["existing"]] == ["박 옛 글", "박 새 글"] and v["20104"]["final"] == "최 지금 최종안" and v["20105"]["closed"]
    latest = v["20103"]["existing"][-1]["id"]
    assert ok(api.finals_from_existing(hr, "autonomy", [{"student_no": "20103", "record_id": latest}]))["count"] == 1
    assert ok(api.student_view(hr, "autonomy", "20103"))["final"]["text"] == "박 새 글"
    # 마감 학생·남의 기록은 거부(전부 취소)
    e = api.finals_from_existing(hr, "autonomy", [{"student_no": "20104", "record_id": v["20104"]["existing"][0]["id"]},
                                                {"student_no": "20105", "record_id": v["20105"]["existing"][0]["id"]}])
    assert not e["ok"], e
    assert ok(api.student_view(hr, "autonomy", "20104"))["final"]["text"] == "최 지금 최종안"  # 함께 취소됨
    e = api.finals_from_existing(hr, "autonomy", [{"student_no": "20104", "record_id": latest}])
    assert not e["ok"] and "바뀌었" in e["error"], e
    ok(api.finals_from_existing(hr, "autonomy", [{"student_no": "20104", "record_id": v["20104"]["existing"][0]["id"]}]))  # 덮어쓰기
    assert ok(api.student_view(hr, "autonomy", "20104"))["final"]["text"] == "최 옛 글"


def test_ux_fixes(hr):
    """Codex UX 검토(docs/review/codex_ux_v013.md) U02·U03·U04·U06·U11."""
    # U02: 학번과 이름이 다른 학생을 가리키면 확정하지 않는다
    rows = existing.build([["20102", "김철수", "내용"]], False, {"student_no": 0, "name": 1, "content": 2}, M)
    assert rows[0]["state"] == "none" and rows[0]["student_no"] is None and "이영희" in rows[0]["note"], rows
    rows = existing.build([["20199", "이영희", "내용"]], False, {"student_no": 0, "name": 1, "content": 2}, M)
    assert rows[0]["state"] == "suggested" and "명렬에 없음" in rows[0]["note"], rows
    rows = existing.build([["20101", "김철수", "2/9", "내용"]], False, {"student_no": 0, "name": 1, "clsnum": 2, "content": 3}, M)
    assert rows[0]["state"] == "suggested" and "반·번호가 다름" in rows[0]["note"], rows
    # U11: 연도 없는 날짜는 학년도로, 달력에 없는 날짜는 거부, 엑셀 일련번호
    assert existing.norm_date("3/5", 2026) == "2026-03-05" and existing.norm_date("2월 3일", 2026) == "2027-02-03"
    assert existing.norm_date("2026-02-31") == "" and existing.norm_date("46086") == "2026-03-05"
    assert existing.norm_date("3/5") == ""  # 학년도를 모르면 못 읽음(화면에서 확인 필요)
    b = ok(api_.existing_build(hr, "career", [["김철수", "3/5", "가"], ["김철수", "모름", "나"]], False, {"name": 0, "date": 1, "content": 2}))["rows"]
    assert [(r["date"], r["date_raw"]) for r in b] == [("2026-03-05", "3/5"), ("", "모름")], b
    # U04: 같은 요청 번호는 한 번만
    n0 = len(ok(api_.student_view(hr, "career", "20102"))["records"])
    rows = [{"student_no": "20102", "content": "한 번만"}]
    r1 = ok(api_.existing_apply(hr, "career", rows, "record", "req-1"))
    r2 = ok(api_.existing_apply(hr, "career", rows, "record", "req-1"))
    assert r1["count"] == 1 and r2.get("repeated") and len(ok(api_.student_view(hr, "career", "20102"))["records"]) == n0 + 1
    # U03: 최종안 일괄 되돌리기(그 뒤 고친 학생은 그대로)
    ok(api_.existing_apply(hr, "career", [{"student_no": "20101", "content": "철수 완성문"}, {"student_no": "20102", "content": "영희 완성문"}]))
    ok(api_.edit_final(hr, "career", "20101", "철수 직접 쓴 최종안"))
    v = {x["student_no"]: x for x in ok(api_.finals_bulk_view(hr, "career"))["students"]}
    assert v["20101"]["existing"][-1]["created_at"]  # U06: 추가 시각 표시용
    picks = [{"student_no": s, "record_id": v[s]["existing"][-1]["id"]} for s in ("20101", "20102")]
    assert ok(api_.finals_from_existing(hr, "career", picks, "req-2"))["count"] == 2
    assert ok(api_.finals_from_existing(hr, "career", picks, "req-2")).get("repeated")
    ok(api_.edit_final(hr, "career", "20102", "영희 그 뒤 고침"))
    u = ok(api_.finals_bulk_undo())
    assert (u["count"], u["skipped"]) == (1, 1), u
    assert ok(api_.student_view(hr, "career", "20101"))["final"]["text"] == "철수 직접 쓴 최종안"
    assert ok(api_.student_view(hr, "career", "20102"))["final"]["text"] == "영희 그 뒤 고침"
    assert not api_.finals_bulk_undo()["ok"]


if __name__ == "__main__":
    test_parse()
    hr = test_api_and_reorder()
    test_record_bulk_and_finals(hr)
    api_ = Api(); api_.attach(W())
    test_ux_fixes(hr)
    print("EXISTING IMPORT OK")
