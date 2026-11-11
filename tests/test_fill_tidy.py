"""v0.17.1 성취기준 수식 빈칸 AI 채우기(덧붙이기만), 활동 개요 AI 다듬기(새 낱말 알림)."""
import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter, stdformat
from app.api import Api
from app.standards import new_words

ANSWER = {}
openrouter.chat = lambda key, model, system, user, privacy=False: (ANSWER["v"], 0.0)


def ok(r):
    assert r.get("ok"), r
    return r


def main():
    # 덧붙이기만 했는지
    assert stdformat.only_added("다항식의  을 구할 수 있다.", "다항식의 값을 구할 수 있다.")
    assert not stdformat.only_added("다항식의  을 구할 수 있다.", "다항식의 값을 계산할 수 있다.")
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api()
    ok(api.create_year(2026, "subject"))
    s1 = ok(api.add_group({"kind": "subject", "name": "수학", "semester": 1}))["id"]
    text = "[10공수1-01-01] 다항식의 사칙연산을 할 수 있다.\n[10공수1-01-02]  의 그래프를 그릴 수 있다.\n[10공수1-01-03] 두 점  사이의 거리를 구한다."
    gl = stdformat.gap_lines(text)
    assert [i for i, _ in gl] == [1, 2], gl
    ANSWER["v"] = '{"1": "[10공수1-01-02] 이차함수의 그래프를 그릴 수 있다.", "2": "[10공수1-01-03] 두 점 사이 거리를 구한다."}'
    r = ok(api.standards_fill_gaps(s1, text))
    assert [c["line"] for c in r["changed"]] == [1] and [c["line"] for c in r["rejected"]] == [2], r  # 2번은 '의'를 지워 버림
    assert r["text"].split("\n")[1] == "[10공수1-01-02] 이차함수의 그래프를 그릴 수 있다." and r["text"].split("\n")[2] == text.split("\n")[2]
    # 빈 곳이 없으면 AI를 부르지 않음
    assert ok(api.standards_fill_gaps(s1, "[10공수1-01-01] 다항식의 사칙연산을 할 수 있다."))["gaps"] == 0
    print("FILL TIDY OK (subject)")


def tidy():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api()
    r = api.create_year(2027, "homeroom")
    hr = ok(api.add_group({"kind": "homeroom", "grade": 1, "class_no": 1}))["id"]
    ANSWER["v"] = "4/12 · 과학의 날 — 포스터 제작, 발표\n\n5/3 · 진로 체험 — 보고서 작성"
    r = ok(api.outline_tidy(hr, "autonomy", "4월12일 과학의날  포스터제작\n진로 체험 5/3 보고서 작성"))
    assert r["text"] == "4/12 · 과학의 날 — 포스터 제작, 발표\n5/3 · 진로 체험 — 보고서 작성"
    assert "발표" in r["new_words"] and "포스터" not in r["new_words"], r["new_words"]
    assert not api.outline_tidy(hr, "behavior", "x")["ok"]
    assert new_words("과학의 날", "과학의 날") == []
    print("FILL TIDY OK")


def outage():
    """OpenRouter 장애·속도 제한 구분(code) — 화면은 이 code면 남은 건을 멈추고 안내 창을 띄운다."""
    import importlib
    import requests
    orr = importlib.reload(openrouter)  # 위에서 바꿔 둔 chat을 원래대로
    orr.time.sleep = lambda s: None

    class R:
        def __init__(self, code, body=None): self.status_code, self.ok, self._b = code, code < 400, body or {}
        def json(self): return self._b
    seq = []
    def post(*a, **k):
        x = seq.pop(0)
        if isinstance(x, Exception):
            raise x
        return x
    orr.requests.post = post
    def err(items):
        seq[:] = items
        try:
            orr.chat("sk", "m", "s", "u")
        except orr.LlmError as e:
            return e.code, str(e)
        return None, "ok"
    assert err([requests.ConnectionError()] * 3)[0] == "service_down"
    assert err([R(503)] * 3)[0] == "service_down"
    assert err([R(429)] * 3)[0] == "rate_limited"
    assert err([R(401, {"error": {"message": "bad key"}})])[0] is None  # 키 문제는 장애가 아님
    seq[:] = [R(502), R(200, {"choices": [{"message": {"content": "좋음"}}], "usage": {"cost": 0.1}})]
    assert orr.chat("sk", "m", "s", "u") == ("좋음", 0.1)  # 한 번 실패 뒤 성공
    print("OUTAGE OK")


if __name__ == "__main__":
    main()
    tidy()
    outage()
