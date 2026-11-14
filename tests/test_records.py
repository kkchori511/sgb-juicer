import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, openrouter, export
from app.api import Api

SENT = []
def fake_chat(key, model, system, user, privacy_block=False):
    SENT.append((system, user, privacy_block))
    return f"결과{len(SENT)}: " + user[:20], 0.001
openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.5

def ok(r):
    assert r.get("ok"), r
    return r

def test_all():
    config.save({"openrouter_key": "sk-test", "models": ["m/free", "", "", ""]})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    sub = ok(api.add_group({"kind": "subject", "name": "공통수학1", "semester": 1}))["id"]
    p = api.roster_from_text("20301\t김철수\n20302\t이영희\n20303\t박민수")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.roster_apply(sub, api.roster_build(sub, p["raw"], p["header"], p["columns"])["rows"]))

    slots = ok(api.slots())["slots"]
    assert [s["item"] for s in slots] == ["autonomy", "career", "behavior", "subject"]
    assert slots[2]["target"] == 900

    # 기록·태그
    t1 = ok(api.add_tag("독서"))["id"]; t2 = ok(api.add_tag("탐구"))["id"]
    assert not api.add_tag("독서")["ok"]
    r1 = ok(api.add_record(hr, "career", "20301", {"content": "진로 독서 감상문을 씀. " * 10, "title": "독서", "date": "2026-03-15", "tag_ids": [t1]}))["id"]
    r2 = ok(api.add_record(hr, "career", "20301", {"content": "직업 탐색 발표", "title": "발표"}))["id"]
    assert not api.add_record(hr, "career", "20301", {"content": " "})["ok"]
    assert not api.add_record(hr, "subject", "20301", {"content": "x"})["ok"]  # 담임반에 없는 항목
    v = ok(api.student_view(hr, "career", "20301"))
    assert [r["seq"] for r in v["records"]] == [1, 2] and v["records"][0]["tags"][0]["name"] == "독서"
    ok(api.tag_records([r1, r2], [t2]))
    assert ok(api.tags())["tags"][1]["used"] == 2

    # 기록 정제: 기록 한 건의 결과 묶음은 개수 제한 없음(v0.19, 지워지지 않음)
    ids = [ok(api.ai_record(r1))["id"] for _ in range(4)]
    out = ok(api.ai_record(r1)); assert out["dropped"] is None and out["balance"] == 1.5
    assert len([r for r in ok(api.student_view(hr, "career", "20301"))["records"] if r["id"] == r1][0]["candidates"]) == 5
    ok(api.apply_candidate(out["id"]))
    rec = [r for r in ok(api.student_view(hr, "career", "20301"))["records"] if r["id"] == r1][0]
    assert rec["content"].startswith("결과") and rec["original"].startswith("진로 독서")

    # 종합: 비중, 학번·이름 미전송
    bad = api.ai_synth(hr, "career", "20301", [r1, r2], {str(r1): 70, str(r2): 50}, None, True)
    assert not bad["ok"] and "100%" in bad["error"]
    s1 = ok(api.ai_synth(hr, "career", "20301", [r1, r2], {str(r1): 60, str(r2): ""}, None, True))
    assert s1["ratios"] == [60.0, 40.0]
    sys_, user, priv = SENT[-1]
    for leak in ("20301", "김철수", "20302", "이영희"):
        assert leak not in sys_ and leak not in user, leak
    assert "반영 비율 60%" in user and "약 1500바이트" in sys_
    # 학습 차단 옵션 전달
    config.save({"privacy_block": True}); ok(api.ai_synth(hr, "career", "20301", [r1], None)); assert SENT[-1][2] is True
    config.save({"privacy_block": False})

    # 최종안·마감
    assert not api.set_closed(hr, "career", "20301", True)["ok"]  # 최종안 없음
    ok(api.adopt_result(s1["id"]))
    v = ok(api.student_view(hr, "career", "20301")); assert v["final"]["text"].startswith("결과") and not v["final"]["stale"]
    ok(api.add_record(hr, "career", "20301", {"content": "추가 기록"}))
    assert ok(api.student_view(hr, "career", "20301"))["final"]["stale"]
    ok(api.edit_final(hr, "career", "20301", "직접 고친 최종안"))
    ok(api.set_closed(hr, "career", "20301", True))
    for r in (api.add_record(hr, "career", "20301", {"content": "x"}), api.update_record(r1, {"content": "y"}),
              api.delete_record(r2), api.ai_record(r1), api.edit_final(hr, "career", "20301", "z"), api.tag_records([r1], [t1])):
        assert not r["ok"] and "마감" in r["error"], r
    st = ok(api.slot_view(hr, "career"))["students"]; assert st[0]["status"] == "closed" and st[1]["status"] == "none"
    d = ok(api.dashboard()); hrg = d["groups"][0]; assert hrg["summary"]["closed"] == 1
    ok(api.set_closed(hr, "career", "20301", False))

    # 이미 쓴 생기부 일괄 넣기(탭 고정, 매칭 확실할 때만)
    text = "학번\t이름\t내용\n20302\t이영희\t수업 시간에 적극적, 질문이 많음\n20399\t없는\t내용\n20303\t박민순\t성실함"
    pz = ok(api.existing_parse(sub, "subject", text))
    assert pz["columns"]["content"] == 2 and pz["columns"]["student_no"] == 0 and pz["columns"]["name"] == 1
    b = ok(api.existing_build(sub, "subject", pz["raw"], pz["header"], pz["columns"]))["rows"]
    assert [x["state"] for x in b] == ["confirmed", "none", "suggested"], b  # 박민순 → 비슷한 이름 박민수 추천
    assert b[2]["student_no"] == "20303"
    assert not api.existing_apply(sub, "subject", [{"student_no": "20399", "content": "x"}])["ok"]
    assert not api.existing_apply(sub, "subject", [b[0], b[0]])["ok"]  # 같은 학생 두 줄
    assert ok(api.existing_apply(sub, "subject", [b[0], b[2]]))["count"] == 2
    v = ok(api.student_view(sub, "subject", "20302")); assert v["records"][0]["kind"] == "existing"
    pol = ok(api.ai_record(v["records"][0]["id"])); assert SENT[-1][0].count("다듬") >= 1
    ok(api.adopt_record(v["records"][0]["id"]))

    # 내보내기
    rows = ok(api.export_preview(sub, "subject"))["rows"]
    assert [r["student_no"] for r in rows] == ["20301", "20302", "20303"] and rows[1]["text"].startswith("수업")
    tsv = export.to_tsv([{"student_no": "20301", "grade": 2, "class_no": 3, "number": 1, "name": "가", "closed": False, "text": 'a\n"b"', "bytes": 3}], "full", True)
    assert tsv.split("\r\n")[0] == "학년\t반\t번호\t이름\t상태\t최종안\t바이트"
    assert tsv.split("\r\n")[1] == '2\t3\t1\t가\t미마감\t"a\n""b"""\t3'
    p = os.path.join(os.environ["SGB_DATA_DIR"], "t.xlsx")
    export.write_xlsx(p, rows, "full", "공통수학1")
    from openpyxl import load_workbook
    ws = load_workbook(p).active
    assert ws.max_row == 4 and ws["E2"].value == "미마감" and ws["A1"].value == "학년" and not ws.merged_cells.ranges
    ok(api.export_copy(sub, "subject", False, "no", "text", False))

    # 명렬 다시 넣기: 기록 있는 학생은 비활성화, 없는 학생은 빠짐
    p2 = api.roster_from_text("20301\t김철수")
    res = ok(api.roster_apply(sub, api.roster_build(sub, p2["raw"], p2["header"], p2["columns"])["rows"]))
    assert res["deactivated"] == 2 and res["removed"] == 0, res  # 20302·20303 둘 다 기록 있음

    # 프롬프트 목록: 기본 3개, 새로 만들기, 실행할 때 고르기(작업별 기억), 기본은 못 지우고 되돌리기
    from app.prompt_default import DEFAULT_TEXT
    pl = ok(api.prompt_list())
    assert [x["id"] for x in pl["prompts"]][:3] == ["default", "refine", "polish"] and pl["picks"] == {"synth": "default", "refine": "refine", "polish": "polish"}
    ok(api.ai_synth(hr, "career", "20301", [r1], None))
    assert SENT[-1][0].startswith("# 역할") and "50% 이상 다르게" in SENT[-1][0]
    nid = ok(api.prompt_save({"name": "내 종합", "prompt": "내 지침", "example": "내 예시"}))["id"]
    ok(api.ai_extra_set("", nid, "synth")); ok(api.ai_synth(hr, "career", "20301", [r1], None)); ok(api.ai_extra_set("", "", ""))
    assert SENT[-1][0].startswith("내 지침") and "내 예시" in SENT[-1][0] and "반드시" in SENT[-1][0]
    assert ok(api.prompt_list())["picks"]["synth"] == nid
    ok(api.ai_synth(hr, "career", "20301", [r1], None)); assert SENT[-1][0].startswith("내 지침")  # 마지막에 고른 것을 기억
    ok(api.lock_result(ids[0], False)); ok(api.ai_record(r1)); assert SENT[-1][0].startswith("# 역할") and "정제" in SENT[-1][0] and "고치지 않아도 되는 문장은 한 글자도 바꾸지 않습니다" in SENT[-1][0]  # 정제는 정제 기본(따로 기억)
    assert not api.prompt_delete("default")["ok"]
    ok(api.prompt_save({"id": "default", "name": "바꾼 이름", "prompt": "고친 기본", "example": ""}))
    d0 = [x for x in ok(api.prompt_list())["prompts"] if x["id"] == "default"][0]
    assert d0["name"] == "기본 프롬프트" and d0["prompt"] == "고친 기본"
    ok(api.prompt_reset("default")); assert [x for x in ok(api.prompt_list())["prompts"] if x["id"] == "default"][0]["prompt"] == DEFAULT_TEXT
    ok(api.prompt_delete(nid)); pl = ok(api.prompt_list())
    assert pl["picks"]["synth"] == "default" and nid not in [x["id"] for x in pl["prompts"]]
    assert not api.prompt_save({"name": "  "})["ok"]

    # 태그 삭제는 기록에서도 빠짐
    ok(api.delete_tag(t1)); assert all(t["name"] != "독서" for r in ok(api.student_view(hr, "career", "20301"))["records"] for t in r["tags"])
    print("RECORDS OK")

if __name__ == "__main__":
    test_all()
