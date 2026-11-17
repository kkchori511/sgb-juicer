"""태그 AI 변환 이어 고치기: 대화 누적(v0.20, 원문 → 결과1 → 요청2 …), 대화는 빼지 않고 모두 씀."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter

CALLS = []


def fake_chat(key, model, system, user, privacy_block=False, history=None):
    CALLS.append((system, user, list(history or [])))
    return f"결과{len(CALLS)}", 0.001


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402
from app.tagwork import norm_chain, signature  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_src():
    # 끈 값은 단계에 넣지 않음(예전 단계와 서명 같음), 첫 단계에는 붙지 않음
    old = {"src": "original", "steps": [{"prompt": "p", "example": "", "request": ""}, {"prompt": "", "example": "", "request": "짧게"}]}
    assert signature(norm_chain(old)) == signature(norm_chain({**old, "steps": [old["steps"][0], {**old["steps"][1], "with_src": False}]}))
    assert "with_src" not in norm_chain({"steps": [{"prompt": "p", "with_src": True}]})["steps"][0]
    assert norm_chain({"steps": [{"prompt": "p"}, {"request": "r", "only_here": True}]})["steps"][1] == {"prompt": "", "example": "", "request": "r", "with_src": True, "only_here": True}

    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리\n20303\t박세나")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.add_tag("독서"))
    tag = ok(api.tags())["tags"][0]["id"]
    rids = [ok(api.add_record(hr, "career", f"2030{i}", {"content": f"원문{i} 책을 읽고 토론함", "tag_ids": [tag]}))["id"] for i in (1, 2, 3)]
    w = ok(api.tag_work(tag))["work"]
    s1 = {"prompt": "지침", "example": "", "request": ""}
    c1 = ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1]}))["id"]
    # 대화 누적: 원문 → 결과1 → 이번 요청
    s2 = {"prompt": "", "example": "", "request": "토론 내용도 넣어"}
    c2 = ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1, s2]}, c1))["id"]
    sysm, user, hist = CALLS[-1]
    assert "[이어서 고치기 — 대화]" in sysm and hist == [("원문1 책을 읽고 토론함", "결과1")] and "토론 내용도 넣어" in user, (hist, user)
    assert ok(api.tag_work(tag))  # 후보에 앞 대화 저장
    from app.api import Api as _A  # noqa
    # 3단계: 앞 대화 모두(원문 → 결과1 → 요청2 → 결과2)
    s3 = {"prompt": "", "example": "", "request": '원문의 "토론함" 내용을 넣어 줘', "with_src": True, "only_here": True}
    c3 = ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1, s2, s3]}, c2))["id"]
    hist = CALLS[-1][2]
    assert len(hist) == 2 and hist[0] == ("원문1 책을 읽고 토론함", "결과1") and "토론 내용도 넣어" in hist[1][0] and hist[1][1] == "결과2", hist
    # 앞 후보(c1)가 지워져도 대화는 c3에 저장돼 이어짐
    ok(api.tag_cand_delete(c1)); ok(api.tag_cand_delete(c2))
    ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1, s2, s3, {"prompt": "", "example": "", "request": "짧게"}]}, c3))
    assert [h[1] for h in CALLS[-1][2]] == ["결과1", "결과2", "결과3"], CALLS[-1][2]
    # v0.20: 대화는 빼지 않음 — (예전처럼 단계 그대로 확정한 설정이 있으면) 나머지 변환도 모든 단계를 대화로
    ok(api.tag_confirm(c3, True))
    run = ok(api.tag_run_create(w["id"], rids[1:]))["run"]
    assert len(run["chain"]["steps"]) == 3
    n = len(CALLS)
    ok(api.tag_run_item(run["id"], rids[1]))
    assert len(CALLS) == n + 3
    assert CALLS[-3][1] == "원문2 책을 읽고 토론함" and CALLS[-3][2] == []
    assert CALLS[-2][2] == [("원문2 책을 읽고 토론함", f"결과{n + 1}")] and "토론 내용도 넣어" in CALLS[-2][1]
    # 프롬프트 제작: 모든 요청을 재료로
    ok(api.prompt_compose({"src": "original", "steps": [s1, s2, s3]}))
    assert "토론 내용도 넣어" in CALLS[-1][1] and "토론함\" 내용" in CALLS[-1][1]
    # 붙여넣은 글 대화: orig → 앞 결과들 누적
    ok(api.prompt_chat_free({"src": "original", "steps": [s1, s2]}, "앞 결과", None, "붙여넣은 원문", ["앞 결과"]))
    assert CALLS[-1][2] == [("붙여넣은 원문", "앞 결과")]
    ok(api.prompt_chat_free({"src": "original", "steps": [s1, s2, s3]}, "결과B", None, "붙여넣은 원문", ["결과A", "결과B"]))
    assert [h[1] for h in CALLS[-1][2]] == ["결과A", "결과B"]
    # 스킬화 재료(v0.20): 실제 대화 순서(중간 결과 포함), 이 기록만 요청은 표시
    ok(api.tag_skill_compose(c3))
    assert "<요청들>" in CALLS[-1][1]  # 가짜 AI가 분석을 빼먹어 분석만 다시 물음
    m = CALLS[-2][1]
    assert "[재료: 실제 대화" in m and "[1] AI 결과:\n결과1" in m and "[2] AI 결과:\n결과2" in m and '원문의 "토론함" 내용' in m and "(아래 <목표 결과>)" in m, m
    # 붙여넣은 글 스킬화: 화면의 원문·결과로
    r = ok(api.skill_compose_free({"src": "original", "steps": [s1, s2]}, "붙여넣은 원문", "결과B"))
    assert "<원문>\n붙여넣은 원문" in CALLS[-2][1] and "결과B" in CALLS[-2][1]
    ok(api.skill_compose_free({"src": "original", "steps": [s1, s2, s3]}, "붙여넣은 원문", "결과C", None, None, ["결과A", "결과B"]))
    assert "[1] AI 결과:\n결과A" in CALLS[-2][1] and "[2] AI 결과:\n결과B" in CALLS[-2][1]


if __name__ == "__main__":
    test_src()
    print("test_tag_src OK")
