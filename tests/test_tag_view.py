"""v0.16 태그별 기록: 태그로 모아 보기, 반·수업 필터, 바로 고치기 되돌리기, 일괄 태그 되돌리기."""
import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, openrouter
from app.api import Api

openrouter.chat = lambda *a, **k: ("결과", 0.0)
openrouter.balance = lambda key: 1.0


class W:
    def create_file_dialog(self, *a, **k): return ()
    def evaluate_js(self, js): pass


def ok(r):
    assert r.get("ok"), r
    return r


def main():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api(); api.attach(W())
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    ok(api.roster_apply(hr, [{"student_no": "20301", "name": "김철수"}, {"student_no": "20302", "name": "이영희"}], "add"))
    m1 = ok(api.add_group({"kind": "subject", "name": "수학", "semester": 1}))["id"]
    m2 = ok(api.add_group({"kind": "subject", "name": "과학", "semester": 1}))["id"]
    ok(api.roster_apply(m1, [{"student_no": "20301", "name": "김철수"}, {"student_no": "20401", "name": "박민수"}], "add"))
    ok(api.roster_apply(m2, [{"student_no": "20301", "name": "김철수"}], "add"))
    ok(api.set_section(m1, ["20301", "20401"], "A반"))
    ok(api.set_section(m2, ["20301"], "A반"))
    t = ok(api.add_tag("독서"))["id"]
    t2 = ok(api.add_tag("탐구"))["id"]
    a = ok(api.add_record(hr, "career", "20301", {"content": "진로 독서", "tag_ids": [t]}))["id"]
    b = ok(api.add_record(m1, "subject", "20301", {"content": "수학 독서", "tag_ids": [t, t2]}))["id"]
    c = ok(api.add_record(m1, "subject", "20401", {"content": "4반 수학 독서", "tag_ids": [t]}))["id"]
    d = ok(api.add_record(m2, "subject", "20301", {"content": "과학 독서", "tag_ids": [t]}))["id"]
    e = ok(api.add_record(hr, "autonomy", "20302", {"content": "태그 없음"}))["id"]

    v = ok(api.tag_view(t, {}))
    assert [r["id"] for r in v["records"]] == [a, b, d, c], [r["id"] for r in v["records"]]  # 2-3반 김철수(진로→수학→과학), 2-4반 박민수
    assert v["students"] == 2 and v["untagged"] == 1
    assert {x["name"]: x["count"] for x in v["tags"]} == {"독서": 4, "탐구": 1}
    assert [o["key"] for o in v["options"]["classes"]] == ["c:2-3", "c:2-4"]
    labels = [o["label"] for o in v["options"]["sections"]]
    assert labels == ["과학(1학기) · A반", "수학(1학기) · A반"], labels  # 같은 'A반'도 담당으로 구분
    # 학년-반: 그 반 학생의 모든 기록 / 수업: 그 담당·수업의 기록만
    assert [r["id"] for r in ok(api.tag_view(t, {"scope": "c:2-3"}))["records"]] == [a, b, d]
    assert [r["id"] for r in ok(api.tag_view(t, {"scope": f"s:{m1}:A반"}))["records"]] == [b, c]
    assert [r["id"] for r in ok(api.tag_view(t, {"slot": "i:career"}))["records"]] == [a]
    assert [r["id"] for r in ok(api.tag_view(t, {"slot": f"g:{m2}:subject"}))["records"]] == [d]
    assert [r["id"] for r in ok(api.tag_view(t, {"q": "4반"}))["records"]] == [c]
    assert [r["id"] for r in ok(api.tag_view(0, {}))["records"]] == [e]
    # 태그별 수는 태그 선택을 뺀 다른 필터 적용
    assert {x["name"]: x["count"] for x in ok(api.tag_view(t, {"scope": f"s:{m1}:A반"}))["tags"]} == {"독서": 2, "탐구": 1}

    # 바로 고치기 → 되돌리기
    r1 = ok(api.update_record(a, {"content": "진로 독서 고침"}))["record"]
    assert r1["content"] == "진로 독서 고침"
    r2 = ok(api.revert_record(a, {"content": "진로 독서"}, {"content": "진로 독서 고침"}))["record"]
    assert r2["content"] == "진로 독서"
    # 그 뒤 다른 곳에서 다시 고쳤으면 되돌리지 않음
    ok(api.update_record(a, {"content": "1차"}))
    ok(api.update_record(a, {"content": "2차"}))
    assert not api.revert_record(a, {"content": "진로 독서"}, {"content": "1차"})["ok"]
    # 불러온 뒤 다른 곳에서 바뀌었으면 덮지 않음
    assert not api.update_record(a, {"content": "덮기", "expect": {"content": "옛 내용"}})["ok"]
    ok(api.update_record(a, {"content": "3차", "expect": {"content": "2차"}}))
    # 태그 빼기 되돌리기
    ok(api.update_record(b, {"tag_ids": [t2]}))
    r3 = ok(api.revert_record(b, {"tag_ids": [t, t2]}, {"tag_ids": [t2]}))["record"]
    assert r3["tag_ids"] == sorted([t, t2])
    # 마감되면 되돌리지 않음
    ok(api.update_record(d, {"content": "과학 고침"}))
    ok(api.edit_final(m2, "subject", "20301", "최종"))
    ok(api.set_closed(m2, "subject", "20301", True))
    assert not api.revert_record(d, {"content": "과학 독서"}, {"content": "과학 고침"})["ok"]
    assert ok(api.tag_view(t, {"status": "closed"}))["records"][0]["id"] == d
    assert d not in [r["id"] for r in ok(api.tag_view(t, {"status": "open"}))["records"]]

    # 일괄 태그 + 되돌리기(이미 있던 태그는 되돌릴 때 건드리지 않음)
    pairs = ok(api.tag_records_undoable([a, b], [t2], "add"))["pairs"]
    assert [p[:2] for p in pairs] == [[a, t2]], pairs
    ok(api.undo_tag_records(pairs, "add"))
    assert t2 not in ok(api.tag_view(t, {}))["records"][0]["tags"]
    assert t2 in [r for r in ok(api.tag_view(t, {}))["records"] if r["id"] == b][0]["tags"]
    pairs = ok(api.tag_records_undoable([a], [t], "remove"))["pairs"]
    assert a not in [r["id"] for r in ok(api.tag_view(t, {}))["records"]]
    ok(api.undo_tag_records(pairs, "remove"))
    assert a in [r["id"] for r in ok(api.tag_view(t, {}))["records"]]
    # W05: 일괄로 붙인 뒤 다른 곳에서 뺐다가 다시 붙였으면 되돌리기가 건드리지 않음
    pairs = ok(api.tag_records_undoable([a], [t2], "add"))["pairs"]
    ok(api.update_record(a, {"tag_ids": [t]})); ok(api.update_record(a, {"tag_ids": [t, t2]}))
    u = ok(api.undo_tag_records(pairs, "add"))
    assert u["done"] == 0 and u["changed"] == 1, u
    assert t2 in [r for r in ok(api.tag_view(t, {}))["records"] if r["id"] == a][0]["tags"]
    ok(api.update_record(a, {"tag_ids": [t]}))
    # W03: 충돌·마감 오류는 code로 구분
    assert api.update_record(a, {"content": "x", "expect": {"content": "옛"}})["code"] == "conflict"
    assert api.update_record(d, {"content": "x"})["code"] == "closed"
    # W11: 학년도가 다르면 저장하지 않음
    assert not api.update_record(a, {"content": "x", "year": 2025})["ok"]
    # W04: 확인과 쓰기 사이에 다른 저장이 끼지 못함(같은 잠금) — 확인 중에 다른 스레드가 쓰려 하면 기다린다
    import threading, time
    from app import records as R
    rec = api._rec()
    orig_same = R.Records._same
    def slow_same(cur, want):
        time.sleep(0.3)
        return orig_same(cur, want)
    R.Records._same = staticmethod(slow_same)
    cur = ok(api.tag_view(t, {}))["records"][0]["content"]
    th = threading.Thread(target=lambda: rec.update_record(a, {"content": "탭 화면 수정", "expect": {"content": cur}}))
    th.start(); time.sleep(0.1)
    R.Records._same = staticmethod(orig_same)
    rec2 = R.Records(rec.d)
    rec2.update_record(a, {"content": "다른 곳 수정"})  # 앞 저장이 끝난 뒤에 실행됨
    th.join()
    assert [r for r in ok(api.tag_view(t, {}))["records"] if r["id"] == a][0]["content"] == "다른 곳 수정"
    # 비활성 학생 기록은 기본 숨김, '비활성 포함'이면 보임(active=False 표시)
    ok(api.set_active(m1, ["20401"], False))
    assert c not in [r["id"] for r in ok(api.tag_view(t, {}))["records"]]
    rc = [r for r in ok(api.tag_view(t, {"inactive": True}))["records"] if r["id"] == c][0]
    assert rc["active"] is False
    print("TAG VIEW OK")


if __name__ == "__main__":
    main()
