"""프롬프트 마법사: 대화 종합(프롬프트 제작)·양식 AI 다듬기·붙여넣기 대화·쓴 태그 기록(가짜 AI)."""
import os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter

SEEN = []


def fake_chat(key, model, system, user, privacy_block=False):
    SEEN.append((system, user))
    if "프롬프트' 를" in system or "프롬프트'를 정교하게" in system:
        return "```\n# 역할\n완성된 프롬프트\n```", 0.002
    return "변환:" + user[:10], 0.001


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_wizard():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    chain = {"src": "original", "steps": [{"prompt": "지침A", "example": "예시A", "request": ""},
                                          {"prompt": "", "example": "", "request": "더 짧게"},
                                          {"prompt": "지침B", "example": "", "request": "탐구 과정 살리기"}]}
    r = ok(api.prompt_compose(chain))
    sysmsg, user = SEEN[-1]
    assert r["text"] == "# 역할\n완성된 프롬프트"  # 코드 블록 표시는 벗김
    assert "[참고: 기본 프롬프트]" in sysmsg and "# 업무 절차" in sysmsg
    assert "지침A" in user and "더 짧게" in user and "지침B" in user and "탐구 과정 살리기" in user and "예시A" in user
    f = ok(api.prompt_form_ai({"subject": "수학", "item": "세특"}))
    assert "수학" in f["assembled"] and f["text"].startswith("# 역할") and "<조립본>" in SEEN[-1][1]
    c = ok(api.prompt_chat_free({"src": "original", "steps": [{"prompt": "지침", "request": ""}]}, "붙여넣은 학생 글"))
    assert c["text"].startswith("변환:") and SEEN[-1][1] == "붙여넣은 학생 글"
    assert not api.prompt_chat_free({"src": "original", "steps": [{"prompt": "지침"}]}, "  ")["ok"]
    # 저장: 만든 방식·쓴 태그
    pid = ok(api.prompt_save({"name": "봉사 프롬프트", "prompt": "p", "example": "", "made": "대화", "tags": ["봉사"]}))["id"]
    ok(api.prompt_mark_tag(pid, "독서"))
    ok(api.prompt_mark_tag(pid, "독서"))
    e = [x for x in ok(api.prompt_list())["prompts"] if x["id"] == pid][0]
    assert e["made"] == "대화" and e["tags"] == ["봉사", "독서"], e
    # 고쳐 저장해도 태그 기록은 남음
    ok(api.prompt_save({"id": pid, "name": "봉사 프롬프트2", "prompt": "p2", "example": ""}))
    e = [x for x in ok(api.prompt_list())["prompts"] if x["id"] == pid][0]
    assert e["tags"] == ["봉사", "독서"] and e["name"] == "봉사 프롬프트2"
    # 태그 변환에서 목록 프롬프트로 시작해 확정하면 그 태그가 기록됨
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.add_tag("캠페인"))
    tag = ok(api.tags())["tags"][0]["id"]
    rid = ok(api.add_record(hr, "autonomy", "20301", {"content": "캠페인 원문", "tag_ids": [tag]}))["id"]
    w = ok(api.tag_work(tag, 2026))["work"]
    ok(api.tag_draft_save(w["id"], {"prompt": "p2", "lib_id": pid, "lib_name": "봉사 프롬프트2"}, 2026))
    cid = ok(api.tag_trial_run(w["id"], rid, {"src": "original", "steps": [{"prompt": "p2"}]}, None, None, 2026))["id"]
    ok(api.tag_confirm(cid, True, 2026))
    e = [x for x in ok(api.prompt_list())["prompts"] if x["id"] == pid][0]
    assert e["tags"] == ["봉사", "독서", "캠페인"], e


if __name__ == "__main__":
    test_wizard()
    print("test_prompt_wizard_ai OK")
