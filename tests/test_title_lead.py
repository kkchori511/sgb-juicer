"""제목 넣어 시작(v0.31.2): 체크하면 기록 제목을 결과 글 앞쪽에 넣으라는 지침을 붙인다(한 건 정제·분량 맞추기)."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter  # noqa: E402

SENT = []
REPLY = []


def fake_chat(key, model, system, user, privacy_block=False):
    SENT.append((system, user))
    return (REPLY.pop(0) if REPLY else "가", 0.001)


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_all():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    ok(api.set_target("career", 900))
    a = ok(api.add_record(hr, "career", "20301", {"content": "식을 다시 세워 풀이함.", "title": "방정식의 재구조화"}))["id"]
    b = ok(api.add_record(hr, "career", "20301", {"content": "그래프를 그림."}))["id"]

    # 한 건 정제: 끄면 지침 없음, 켜면 제목 지침 + 정보(meta)
    ok(api.ai_record(a))
    assert "제목 넣어 시작" not in SENT[-1][0]
    api.ai_extra_set("", "", "", "", True)
    out = ok(api.ai_record(a))
    assert "「방정식의 재구조화」" in SENT[-1][0]
    v = ok(api.student_view(hr, "career", "20301"))
    res = [c for r in v["records"] for c in r.get("candidates", []) if c["id"] == out["id"]]
    assert res and res[0]["meta"].get("title_lead") is True
    n = len(SENT)
    ok(api.ai_record(b))  # 제목 없는 기록은 지침 없음
    assert len(SENT) == n + 1 and "제목 넣어 시작" not in SENT[-1][0]

    # 분량 맞추기: 모두 몫 안이어도 제목 넣기면 AI를 부르고, 제목을 함께 보낸다
    SENT.clear()
    REPLY[:] = ["<기록1>\n방정식의 재구조화 활동에서 식을 다시 세워 풀이함.\n</기록1>\n<기록2>\n그래프를 그림.\n</기록2>"]
    ok(api.ai_synth(hr, "career", "20301", [a, b], {}, None, False))
    assert len(SENT) == 1 and "제목: 「방정식의 재구조화」" in SENT[0][1] and "'그대로 둠' 기록도 제목은 앞에" in SENT[0][0]

    # 끄면 예전처럼 AI 없이 원문을 잇는다
    api.ai_extra_set("", "", "", "", False)
    SENT.clear()
    ok(api.ai_synth(hr, "career", "20301", [a, b], {}, None, False))
    assert not SENT


if __name__ == "__main__":
    test_all()
    print("TITLE LEAD OK")
