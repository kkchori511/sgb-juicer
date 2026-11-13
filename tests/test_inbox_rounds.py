"""자료 인박스: 보낸 뒤에도 같은 묶음에 자료를 더 넣어 안 보낸 행만 보낸다(회차별 기록·태그 이어받기·회차별 지우기·예전 묶음 이어 쓰기)."""
import json, os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter, db

openrouter.chat = lambda *a, **k: ("결과", 0.0)
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402
from app.updater import CONFIRM_WORD  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def put(api, bid, text):
    src = ok(api.inbox_source_text(bid, text))
    return ok(api.inbox_import(bid, {"structure": "multi", **src["opts"]}))["count"]


def test_rounds():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    club = ok(api.add_group({"kind": "club", "name": "과학탐구반"}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.add_tag("봉사"))
    tag = ok(api.tags())["tags"][0]["id"]
    bid = ok(api.inbox_create("봉사 활동", hr, "autonomy"))["id"]
    assert put(api, bid, "학번\t이름\t내용\n20301\t김하나\t1차 봉사\n20302\t이두리\t1차 봉사2") == 2
    ok(api.inbox_stage(bid, "review"))
    r1 = ok(api.inbox_send(bid))
    assert r1["records"] == 2
    v = ok(api.inbox_view(bid))
    assert v["batch"]["stage"] == "sent" and v["counts"]["sent"] == 2 and all(r["round"] == 1 for r in v["rows"])
    info = ok(api.inbox_sent_info(bid))
    assert len(info["record_ids"]) == 2 and info["rounds"][0]["n"] == 1
    # 보낸 뒤 묶음 단위로 태그를 붙이면 다음 회차에도 그대로
    ok(api.tag_records_undoable(info["record_ids"], [tag], "add"))
    # 보낸 행은 고치거나 다시 보낼 수 없음
    sent_row = v["rows"][0]["id"]
    assert not api.inbox_edit_row(sent_row, {"content": "x"})["ok"]
    assert not api.inbox_exclude([sent_row], "x")["ok"]
    assert not api.inbox_send(bid)["ok"]
    # 보낸 행이 있으면 대상 명렬 못 바꿈
    assert not api.inbox_update(bid, {"group_id": club, "item": "club"})["ok"]
    # 같은 묶음에 자료 더 넣기: 보낸 행은 두고 덧붙임
    ok(api.inbox_stage(bid, "import"))
    assert "raw" not in ok(api.inbox_view(bid))["batch"]["meta"]  # 지난번 원본 표는 비움(같은 자료 두 번 방지)
    assert put(api, bid, "학번\t이름\t내용\n20303\t박세나\t2차 봉사") == 1
    v = ok(api.inbox_view(bid))
    assert v["counts"]["sent"] == 2 and v["counts"]["confirmed"] == 1 and v["batch"]["stage"] == "match"
    assert [r["state"] for r in v["rows"]] == ["sent", "sent", "confirmed"]
    new = [r for r in v["rows"] if r["state"] != "sent"]
    ok(api.inbox_reorder(bid, [r["id"] for r in new]))  # 안 보낸 행만으로 순서
    # 다시 가져오면 안 보낸 행만 바뀜
    assert put(api, bid, "학번\t이름\t내용\n20303\t박세나\t2차 봉사 고침") == 1
    assert ok(api.inbox_view(bid))["counts"]["sent"] == 2
    ok(api.inbox_stage(bid, "review"))
    r2 = ok(api.inbox_send(bid))
    assert r2["records"] == 1
    d = db.open_year(2026)
    srcs = {x["student_no"]: x["source"] for x in d.q("SELECT student_no, source FROM records")}
    assert srcs == {"20301": f"inbox:{bid}", "20302": f"inbox:{bid}", "20303": f"inbox:{bid}:2"}
    new_rid = d.q("SELECT id FROM records WHERE student_no='20303'")[0]["id"]
    assert d.q("SELECT 1 FROM record_tags WHERE record_id=? AND tag_id=?", (new_rid, tag))  # 태그 이어받음
    v = ok(api.inbox_view(bid))
    assert v["batch"]["sent_summary"] == "3명 · 3건 · 2회" and [x["n"] for x in v["batch"]["meta"]["rounds"]] == [1, 2]
    lst = [b for b in ok(api.inbox_list())["batches"] if b["id"] == bid][0]
    assert lst["rounds"] == 2 and lst["n_sent"] == 3 and lst["n"] == 0
    # 회차별 지우기: 1회만 지우면 그 행이 다시 '안 보냄'
    assert len(ok(api.inbox_sent_info(bid, 1))["record_ids"]) == 2
    assert not api.inbox_delete_sent(bid, "아니", 1)["ok"]
    dr = ok(api.inbox_delete_sent(bid, CONFIRM_WORD, 1))
    assert dr["deleted"] == 2
    v = ok(api.inbox_view(bid))
    assert v["counts"]["confirmed"] == 2 and v["counts"]["sent"] == 1 and [x["n"] for x in v["batch"]["meta"]["rounds"]] == [2]
    assert v["batch"]["stage"] == "review"
    r3 = ok(api.inbox_send(bid))  # 다시 보내면 3회
    assert r3["records"] == 2 and d.q("SELECT COUNT(*) n FROM records WHERE source=?", (f"inbox:{bid}:3",))[0]["n"] == 2

    # 예전 '보내기 완료' 묶음: 열면 1회 보낸 것으로 이어 쓰기
    old = ok(api.inbox_create("예전 묶음", hr, "autonomy"))["id"]
    put(api, old, "학번\t이름\t내용\n20301\t김하나\t옛 기록")
    with d.tx() as c:
        c.execute("UPDATE inbox_batches SET stage='sent', sent_at='2026-05-01 10:00', sent_summary='1명 · 1건' WHERE id=?", (old,))
        c.execute("INSERT INTO records(group_id,item,student_no,kind,seq,content,source) VALUES(?,?,?,'record',9,'옛 기록',?)", (hr, "autonomy", "20301", f"inbox:{old}"))
    v = ok(api.inbox_view(old))
    assert v["counts"]["sent"] == 1 and v["batch"]["meta"]["rounds"][0]["summary"] == "1명 · 1건"
    ok(api.inbox_stage(old, "import"))
    put(api, old, "학번\t이름\t내용\n20302\t이두리\t새 기록")
    ok(api.inbox_stage(old, "review"))
    ok(api.inbox_send(old))
    assert d.q("SELECT COUNT(*) n FROM records WHERE source=?", (f"inbox:{old}:2",))[0]["n"] == 1


if __name__ == "__main__":
    test_rounds()
    print("test_inbox_rounds OK")
