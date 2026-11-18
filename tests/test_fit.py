"""비중으로 분량 맞추기(v0.23): 고정 지침, 기록별 태그로 받기, 몫을 넘은 기록만 다시 줄이기, 너무 짧으면 그 기록만 다시."""
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
from app.textutil import count_bytes  # noqa: E402


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
    a = ok(api.add_record(hr, "career", "20301", {"content": "가나다라마함. " * 40}))["id"]  # 280자, 약 680B
    b = ok(api.add_record(hr, "career", "20301", {"content": "바사아자차함. " * 40}))["id"]
    # 몫: a 630B, b 270B. 첫 결과: a는 몫 안, b는 몫을 넘음 → b만 다시 줄이기
    REPLY[:] = ["<기록1>\n" + "가나다라마함. " * 30 + "\n</기록1>\n<기록2>\n" + "바사아자차함. " * 20 + "\n</기록2>", "바사아자차함. " * 13]
    out = ok(api.ai_synth(hr, "career", "20301", [a, b], {str(a): 70, str(b): 30}, None, True))
    sys_, user = SENT[0]
    assert "덜어내는 편집" in sys_ and "<기록1>" in sys_ and "(1) 가나다라마함." in user and "반영 비율 70%" in user
    assert len(SENT) == 2 and "약" in SENT[1][0] and SENT[1][1].startswith("바사")  # 넘은 기록만
    v = ok(api.student_view(hr, "career", "20301"))
    res = [x for x in v["results"] if x["id"] == out["id"]][0]
    assert res["text"].count("가나다라마함.") == 30 and res["text"].count("바사아자차함.") == 13 and "<기록" not in res["text"]
    assert res["meta"]["prompt_name"] == "분량 맞추기(기본 지침)" and res["meta"]["parts"][1]["first"] > res["meta"]["parts"][1]["bytes"]
    assert out["bytes"] == count_bytes(res["text"]) <= 900

    # 너무 짧게 줄인 기록은 그 기록만 원문에서 다시
    SENT.clear()
    REPLY[:] = ["<기록1>\n가나다라마함.\n</기록1>\n<기록2>\n" + "바사아자차함. " * 13 + "\n</기록2>", "<기록1>\n" + "가나다라마함. " * 28 + "\n</기록1>"]
    out = ok(api.ai_synth(hr, "career", "20301", [a, b], {str(a): 70, str(b): 30}, None, True))
    assert len(SENT) == 2 and "[기록 1] 반영 비율 70%" in SENT[1][1] and "바사" not in SENT[1][1]
    v = ok(api.student_view(hr, "career", "20301"))
    assert [x for x in v["results"] if x["id"] == out["id"]][0]["text"].count("가나다라마함.") == 28

    # 태그 없이 오면 통째로 쓰고, 목표를 넘으면 전체를 한 번 줄임
    SENT.clear()
    REPLY[:] = ["가나다라마함. " * 60, "가나다라마함. " * 20]
    out = ok(api.ai_synth(hr, "career", "20301", [a, b], {str(a): 70, str(b): 30}, None, True))
    assert len(SENT) == 2 and out["bytes"] <= 900

    # 기록마다 몫 안(3% 이내)인데 합이 목표를 조금 넘으면: 가장 많이 넘은 기록 하나만 줄인다
    SENT.clear()
    A2, B2 = "가나다라마함. " * 32, "바사아자차함. " * 13 + "더하기함."
    assert count_bytes(A2.strip()) + count_bytes(B2) + 1 > 900 and count_bytes(A2.strip()) <= 630 * 1.03
    REPLY[:] = [f"<기록 1>\n{A2}\n</기록 1>\n<기록 2>\n{B2}\n</기록 2>", "가나다라마함. " * 30]
    out = ok(api.ai_synth(hr, "career", "20301", [a, b], {str(a): 70, str(b): 30}, None, True))
    assert len(SENT) == 2 and SENT[1][1].startswith("가나다") and out["bytes"] <= 900

    # 이미 몫보다 짧은 기록은 '그대로 둠'
    c = ok(api.add_record(hr, "career", "20301", {"content": "짧은 기록임."}))["id"]
    SENT.clear()
    REPLY[:] = ["<기록1>\n" + "가나다라마함. " * 30 + "\n</기록1>\n<기록2>\n짧은 기록임.\n</기록2>"]
    ok(api.ai_synth(hr, "career", "20301", [a, c], {str(a): 70, str(c): 30}, None, True))
    assert "→ 그대로 둠" in SENT[0][1] and len(SENT) == 1

    # 모두 몫 안이면 AI 없이 원문을 잇는다
    SENT.clear()
    out = ok(api.ai_synth(hr, "career", "20301", [c], {str(c): 100}, None, True))
    assert not SENT and out["cost"] == 0 and out["bytes"] == count_bytes("짧은 기록임.")


if __name__ == "__main__":
    test_all()
    print("test_fit OK")
