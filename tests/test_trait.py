"""행특 설계 카드(v0.22): 사전·설계 저장·AI 변환(결과 묶음)·확정·일괄 대상·설계 엑셀·사전 엑셀·인적사항 경고."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter  # noqa: E402

CALLS = []


def fake_chat(key, model, system, user, privacy_block=False, history=None):
    CALLS.append((system, user))
    return ("성실한 성격으로 맡은 일을 끝까지 해냄.", 0.0)


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0
from app import db, trait, trait_dict  # noqa: E402
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_all():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))

    # 사전: 기본(10유형, 영역 키워드)
    dd = ok(api.trait_dict_get())
    assert dd["is_default"] and len(dd["dict"]["types"]) == 10 and len(dd["dict"]["areas"]["academic"]) > 50
    t0 = dd["dict"]["types"][0]

    # 설계 저장: 빈 설계는 기록을 만들지 않음
    assert ok(api.trait_save(hr, "20301", {}))["id"] is None
    design = {"type": t0["name"], "desc": t0["descs"][0],
              "areas": {"academic": {"kws": ["문제해결력", "직접키워드"], "case": "수학 마스터로 친구들에게 풀이를 설명함"},
                        "attitude": {"kws": ["집중력"], "case": ""},
                        "social": {"kws": [], "case": "이두리와 함께 청소 당번 010-1234-5678", "off": True}}}
    r = ok(api.trait_save(hr, "20301", design))
    rid = r["id"]
    assert rid and any("이름" in w for w in r["warnings"]) and any("전화" in w for w in r["warnings"])
    assert "[학업 역량]" in r["summary"] and "인성" not in r["summary"]  # 뺀 영역은 요약·생성에서 빠짐
    # 키워드 4개는 거절
    bad = dict(design, areas={**design["areas"], "attitude": {"kws": ["a", "b", "c", "d"]}})
    assert not api.trait_save(hr, "20301", bad)["ok"]

    v = ok(api.student_view(hr, "behavior", "20301"))
    tr = [x for x in v["records"] if x["kind"] == "trait"]
    assert len(tr) == 1 and tr[0]["design"]["type"] == t0["name"]
    # 다시 저장해도 학생마다 하나
    ok(api.trait_save(hr, "20301", design))
    assert len([x for x in ok(api.student_view(hr, "behavior", "20301"))["records"] if x["kind"] == "trait"]) == 1

    # AI 변환: 행특 생성 프롬프트, 설계 글(사전 설명 포함), 목표 분량, 학번·이름 없음
    ok(api.ai_record(rid, 0))
    system, user = CALLS[-1]
    assert "행동특성 및 종합의견" in system and "바이트" in system
    assert "- 문제해결력: " in user and "<키워드 뜻 참고" in user and "직접키워드" in user and "수학 마스터" in user and "사례·기록: 없음 →" in user and "[분량]" in user
    assert "청소 당번" not in user and "20301" not in user and "김하나" not in user
    rec = next(x for x in ok(api.student_view(hr, "behavior", "20301"))["records"] if x["id"] == rid)
    assert rec["bundle"][0]["op"] == "trait" and rec["bundle"][0]["meta"]["prompt_name"] == "행특 생성"

    # 목표(행특 기본 1500B)를 넘으면 한 번 줄이기, 빈 줄 정리
    target = ok(api.student_view(hr, "behavior", "20301"))["target"]
    seq = iter(["가" * (target // 3 + 50) + "\n\n둘째 문단", "줄인 첫 문단\n\n줄인 둘째 문단"])
    openrouter.chat = lambda key, model, system, user, privacy_block=False, history=None: (CALLS.append((system, user)) or next(seq), 0.0)
    n0 = len(CALLS)
    ok(api.ai_record(rid, 0))
    assert len(CALLS) == n0 + 2 and "분량만 줄인다" in CALLS[-1][0]
    top = next(x for x in ok(api.student_view(hr, "behavior", "20301"))["records"] if x["id"] == rid)["bundle"][0]
    assert top["text"] == "줄인 첫 문단\n줄인 둘째 문단" and top["meta"]["shrunk_from"] > target
    openrouter.chat = fake_chat
    # 확정 → 확정 기록(최종안 이어 붙이기 대상), 확정 뒤 설계를 고쳐도 확정본은 그대로
    ok(api.confirm_record(rid, "성실한 성격으로 맡은 일을 끝까지 해냄."))
    ok(api.trait_save(hr, "20301", dict(design, desc="바뀐 설명")))
    rec = next(x for x in ok(api.student_view(hr, "behavior", "20301"))["records"] if x["id"] == rid)
    assert rec["confirmed"] and rec["content"] == "성실한 성격으로 맡은 일을 끝까지 해냄." and "바뀐 설명" in rec["orig"]

    # 태그별 기록에는 설계 카드가 나오지 않음
    tv = ok(api.tag_view(0, {}))
    assert all(x["kind"] != "trait" for x in tv["records"])

    # 일괄 대상: 마감 학생 제외
    ok(api.trait_save(hr, "20302", {"type": t0["name"], "areas": {"attitude": {"kws": ["책임감"]}}}))
    ok(api.edit_final(hr, "behavior", "20303", "최종안"))
    ok(api.set_closed(hr, "behavior", "20303", True))
    tg = ok(api.trait_targets(hr))
    st = {x["student_no"]: x for x in tg["students"]}
    assert set(st) == {"20301", "20302"} and tg["skipped_closed"] == 1
    assert st["20301"]["confirmed"] and st["20302"]["filled"] and st["20302"]["results"] == 0

    # 설계 엑셀: 양식 → 채우기 → 확인 → 넣기
    path = os.path.join(DATA, "설계.xlsx")
    members = [m for m in db.open_year(2026).members(hr)]
    trait.template(path, members, {}, trait_dict.load())
    from openpyxl import load_workbook
    wb = load_workbook(path)
    ws = wb["행특 설계"]
    assert [c.value for c in ws[1]][:4] == ["학번", "이름", "성격유형", "성격 설명"]
    row = {r[0].value: r[0].row for r in ws.iter_rows(min_row=2)}
    ws.cell(row=row["20302"], column=3, value="도전성취형")
    ws.cell(row=row["20302"], column=5, value="실험 동아리에서 보고서를 씀")
    ws.cell(row=row["20302"], column=6, value="분석적사고")
    ws.cell(row=row["20303"], column=3, value="성실책임형")  # 마감 → 오류
    wb.save(path)
    chk = ok(api.trait_import_check(hr, path))
    by = {x["sno"]: x for x in chk["rows"]}
    assert by["20302"]["state"] == "over" and by["20303"]["state"] == "error" and "20301" not in by
    out = ok(api.trait_import_apply(hr, [by["20302"]["row"], by["20303"]["row"]]))
    assert out["done"] == 1
    d2 = next(x for x in ok(api.student_view(hr, "behavior", "20302"))["records"] if x["kind"] == "trait")["design"]
    assert d2["type"] == "도전성취형" and d2["areas"]["academic"]["kws"] == ["분석적사고"]

    # 사전 엑셀: 내보내기 → 고쳐서 올리기(diff) → 바꾸기 → 되돌리기
    dpath = os.path.join(DATA, "사전.xlsx")
    trait_dict.to_xlsx(trait_dict.load(), dpath)
    back = trait_dict.from_xlsx(dpath)
    assert trait_dict.diff(trait_dict.load(), back) == {"types": {"add": 0, "change": 0, "gone": 0}, "areas": {a: {"add": 0, "change": 0, "gone": 0} for a in trait_dict.AREAS}}
    wb = load_workbook(dpath)
    ws = wb["역량요소"]
    ws.append(["새유형", "새 설명입니다", "새키워드", "새 키워드 설명", None, None, None, None])
    wb.save(dpath)
    c = ok(api.trait_dict_import_check(dpath))
    assert c["diff"]["types"]["add"] == 1 and c["diff"]["areas"]["academic"]["add"] == 1
    ok(api.trait_dict_import_apply())
    assert any(t["name"] == "새유형" for t in ok(api.trait_dict_get())["dict"]["types"])
    ok(api.trait_dict_undo())
    assert not any(t["name"] == "새유형" for t in ok(api.trait_dict_get())["dict"]["types"])
    # 쓰는 중 사전에 추가
    ok(api.trait_dict_add("social", "나눔실천", "어려운 친구를 먼저 도움", t0["name"]))
    assert any(e["kw"] == "나눔실천" for e in ok(api.trait_dict_get())["dict"]["areas"]["social"])
    ok(api.trait_dict_reset())
    assert ok(api.trait_dict_get())["is_default"]


if __name__ == "__main__":
    test_all()
    print("test_trait OK")
