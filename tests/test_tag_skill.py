"""스킬화: 이어 고친 단계를 한 프롬프트로 종합(원문·목표 결과, 📌 단계 제외) → 같은 원문 검증(채점·길이) → 그 프롬프트로 확정·목록 저장 → 나머지 변환은 1단계.
태그 변환은 낮은 temperature, 채점은 0."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter

CALLS = []
JUDGE = {"v": '{"내용": 96, "문체": 92, "차이": ""}'}


def fake_chat(key, model, system, user, privacy_block=False):
    CALLS.append((system, user, getattr(openrouter._tl, "temp", None)))
    if "[유사도 채점]" in system:
        return "채점 결과: " + JUDGE["v"], 0.0001
    if "[목표] 아래 <원문>" in user:
        return "```\n# 역할\n종합 프롬프트\n```", 0.001
    return "결과글" + "가" * 20, 0.001


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0
from app.api import Api, TAG_TEMP  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_skill():
    p = openrouter.build_payload("m", "s", "u", False)
    assert "temperature" not in p
    openrouter.set_temperature(0.3)
    assert openrouter.build_payload("m", "s", "u", False)["temperature"] == 0.3
    openrouter.set_temperature(None)

    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나\n20302\t이두리")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.add_tag("독서"))
    tag = ok(api.tags())["tags"][0]["id"]
    rids = [ok(api.add_record(hr, "career", f"2030{i}", {"content": f"원문{i} 책을 읽고 토론함", "tag_ids": [tag]}))["id"] for i in (1, 2)]
    w = ok(api.tag_work(tag))["work"]
    s1 = {"prompt": "지침A", "example": "예시글", "request": ""}
    c1 = ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1]}))["id"]
    assert CALLS[-1][2] == TAG_TEMP
    s2 = {"prompt": "", "example": "", "request": "더 짧게"}
    c2 = ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1, s2]}, c1))["id"]
    s3 = {"prompt": "", "example": "", "request": '원문의 "토론함"을 넣어 줘', "with_src": True, "only_here": True}
    c3 = ok(api.tag_trial_run(w["id"], rids[0], {"src": "original", "steps": [s1, s2, s3]}, c2))["id"]
    # 종합: 단계·원문·목표 결과가 재료에, 📌 요청은 규칙에서 뺌
    r = ok(api.tag_skill_compose(c3))
    user = CALLS[-1][1]
    assert r["prompt"] == "# 역할\n종합 프롬프트" and r["example"] == "예시글" and r["copied"] is False
    from app.api import _copied
    assert _copied("[옳은예시] : 원문1 책을 읽고 토론함 내용", ["원문1 책을 읽고 토론함"], n=8) and not _copied("일반 규칙", ["원문1 책을 읽고 토론함"], n=8)
    assert "지침A" in user and "더 짧게" in user and "<원문>\n원문1 책을 읽고 토론함\n</원문>" in user and "<목표 결과>" in user
    assert "규칙으로 만들지 않습니다" in user and "3) 결과를 보고" not in user
    # 지난 시도의 차이를 넘기면 고치기 재료에 들어감
    ok(api.tag_skill_compose(c3, {"prompt": "옛 프롬프트", "out": "옛 결과", "diff": "평가 문장 빠짐"}))
    assert "<지난 프롬프트>\n옛 프롬프트" in CALLS[-1][1] and "평가 문장 빠짐" in CALLS[-1][1]
    # 검증: 같은 원문 한 번 변환(TAG_TEMP) + 채점(0), 점수 = 내용 50 + 문체 30 + 길이 20
    n = len(CALLS)
    v = ok(api.tag_skill_check(c3, "# 역할\n종합 프롬프트", "예시글"))
    assert len(CALLS) == n + 2 and CALLS[n][1] == "원문1 책을 읽고 토론함" and CALLS[n][2] == TAG_TEMP and CALLS[n + 1][2] == 0
    assert "예시글" in CALLS[n][0] and "토론함" in CALLS[n + 1][0]  # 예시는 함께, 📌 요청은 감점 빼기 안내
    assert v["content"] == 96 and v["style"] == 92 and v["length"] == 100 and v["score"] == round(96 * .5 + 92 * .3 + 100 * .2)
    JUDGE["v"] = "알 수 없음"
    assert not api.tag_skill_check(c3, "p", "")["ok"]
    JUDGE["v"] = '{"내용": 96, "문체": 92, "차이": ""}'
    # 확정: 기록 반영 + 설정은 그 프롬프트 1단계 + 목록에 '스킬화'로 저장(쓴 태그)
    cf = ok(api.tag_confirm_skill(c3, "# 역할\n종합 프롬프트", "예시글", {"scores": [93, 95], "tries": 1}, "독서 스킬"))
    w2 = ok(api.tag_work(tag))["work"]
    ch = w2["confirmed"]["chain"]
    assert ch == {"src": "original", "steps": [{"prompt": "# 역할\n종합 프롬프트", "example": "예시글", "request": ""}]}
    assert w2["confirmed"]["skill"]["scores"] == [93, 95] and len(w2["confirmed"]["skill"]["from_chain"]["steps"]) == 3
    e = [x for x in ok(api.prompt_list())["prompts"] if x["id"] == cf["lib_id"]][0]
    assert e["made"] == "스킬화" and e["tags"] == ["독서"] and e["name"] == "독서 스킬"
    run = ok(api.tag_run_create(w["id"], rids[1:]))["run"]
    n = len(CALLS)
    ok(api.tag_run_item(run["id"], rids[1]))
    assert len(CALLS) == n + 1 and CALLS[-1][1] == "원문2 책을 읽고 토론함" and "종합 프롬프트" in CALLS[-1][0]
    # 시험 후보가 아니면 스킬화 불가
    assert not api.tag_skill_compose(999999)["ok"]


if __name__ == "__main__":
    test_skill()
    print("test_tag_skill OK")
