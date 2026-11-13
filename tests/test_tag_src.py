"""태그 AI 변환 이어 고치기: 원문도 함께 보내기(with_src)·원문에서 고른 부분(only_here, 나머지 변환에서 뺌)."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter

CALLS = []


def fake_chat(key, model, system, user, privacy_block=False):
    CALLS.append((system, user))
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
    # 원문 함께: 앞 결과와 원문을 나눠 보내고, 시스템에 원문 규칙
    s2 = {"prompt": "", "example": "", "request": "토론 내용도 넣어", "with_src": True}
    c2 = ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1, s2]}, c1))["id"]
    sysm, user = CALLS[-1]
    assert "[원문 함께 보기]" in sysm and "<지금 결과>\n결과1\n</지금 결과>" in user and "<원문>\n원문1 책을 읽고 토론함\n</원문>" in user, user
    # 원문 끄면 앞 결과만
    ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1, {"prompt": "", "example": "", "request": "짧게"}]}, c1))
    assert CALLS[-1][1] == "결과1" and "[원문 함께 보기]" not in CALLS[-1][0]
    # 이 기록만 단계 → 확정 후 나머지 변환에서는 빠짐
    s3 = {"prompt": "", "example": "", "request": '원문의 "토론함" 내용을 넣어 줘', "with_src": True, "only_here": True}
    c3 = ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1, s2, s3]}, c2))["id"]
    ok(api.tag_confirm(c3, True))
    run = ok(api.tag_run_create(w["id"], rids[1:]))["run"]
    assert len(run["chain"]["steps"]) == 2 and not any(s.get("only_here") for s in run["chain"]["steps"])
    n = len(CALLS)
    ok(api.tag_run_item(run["id"], rids[1]))
    assert len(CALLS) == n + 2
    assert CALLS[-2][1] == "원문2 책을 읽고 토론함"
    assert f"<지금 결과>\n결과{n + 1}\n</지금 결과>" in CALLS[-1][1] and "<원문>\n원문2 책을 읽고 토론함" in CALLS[-1][1]
    # 프롬프트 제작: 이 기록만 단계는 빼고, 원문 함께 단계는 표시
    ok(api.prompt_compose({"src": "original", "steps": [s1, s2, s3]}))
    assert "토론 내용도 넣어" in CALLS[-1][1] and "원문을 함께 보며" in CALLS[-1][1] and "토론함\" 내용" not in CALLS[-1][1]
    # 붙여넣은 글 대화: orig를 원문으로
    ok(api.prompt_chat_free({"src": "original", "steps": [s1, s2]}, "앞 결과", None, "붙여넣은 원문"))
    assert "<지금 결과>\n앞 결과\n</지금 결과>" in CALLS[-1][1] and "<원문>\n붙여넣은 원문\n</원문>" in CALLS[-1][1]


if __name__ == "__main__":
    test_src()
    print("test_tag_src OK")
