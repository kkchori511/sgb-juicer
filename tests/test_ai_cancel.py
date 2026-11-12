"""AI 바로 중지·스트리밍 응답 읽기(가짜 응답)."""
import json, os, sys, tempfile, threading, time
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import openrouter as orr


class Stream:
    """SSE 응답 흉내. gate가 있으면 첫 조각 뒤에 기다린다(중지 시험)."""
    status_code, ok = 200, True
    headers = {"Content-Type": "text/event-stream"}

    def __init__(self, chunks, gate=None):
        self.chunks, self.gate, self.closed = chunks, gate, False

    def iter_lines(self, decode_unicode=False):
        for i, c in enumerate(self.chunks):
            if self.closed:
                raise ConnectionError("closed")
            yield c.encode()
            if self.gate and i == 1:
                while not self.closed:
                    time.sleep(0.01)
                raise ConnectionError("closed")

    def close(self):
        self.closed = True


def sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False)


CHUNKS = [": OPENROUTER PROCESSING", sse({"choices": [{"delta": {"content": "탐구 과정을 "}}]}), "",
          sse({"choices": [{"delta": {"content": "꼼꼼히 기록함."}, "finish_reason": "stop"}]}),
          sse({"choices": [], "usage": {"cost": 0.0123}}), "data: [DONE]"]


def test_stream():
    orr.reset()
    seen = {}
    def post(url, **k):
        seen.update(k)
        return Stream(CHUNKS)
    orr.requests.post = post
    assert orr.chat("sk", "m", "s", "u") == ("탐구 과정을 꼼꼼히 기록함.", 0.0123)
    assert seen["json"]["stream"] is True and seen["stream"] is True


def test_cancel_now():
    """처리 중에 cancel() → 연결을 닫고 Cancelled, 다시 reset 전까지 새 요청도 막음."""
    orr.reset()
    res = Stream(CHUNKS, gate=True)
    orr.requests.post = lambda url, **k: res
    out = {}
    def run():
        try:
            out["r"] = orr.chat("sk", "m", "s", "u")
        except orr.LlmError as e:
            out["e"] = e
    t = threading.Thread(target=run)
    t.start()
    time.sleep(0.2)
    t0 = time.time()
    orr.cancel()
    t.join(3)
    assert not t.is_alive() and time.time() - t0 < 1, "바로 멈추지 않음"
    assert res.closed and out.get("e") is not None and out["e"].code == "cancelled", out
    try:
        orr.chat("sk", "m", "s", "u")
        raise AssertionError("중지 뒤 새 요청이 나감")
    except orr.Cancelled:
        pass
    orr.reset()
    orr.requests.post = lambda url, **k: Stream(CHUNKS)
    assert orr.chat("sk", "m", "s", "u")[0] == "탐구 과정을 꼼꼼히 기록함."


def test_api_discards_late_answer():
    """답이 중지 뒤에 도착하면 저장하지 않는다."""
    from app.api import Api
    api = Api()
    def late(*a, **k):
        orr.cancel()
        return "늦은 답", 0.01
    real = orr.chat
    orr.chat = late
    try:
        api._call_ai("sk", "m", "s", "u", False)
        raise AssertionError("늦은 답을 받아들임")
    except orr.Cancelled:
        pass
    finally:
        orr.chat = real
        orr.reset()
    assert api.ai_cancel()["ok"] and orr.cancelled()
    assert api.ai_cancel_reset()["ok"] and not orr.cancelled()


if __name__ == "__main__":
    test_stream()
    test_cancel_now()
    test_api_discards_late_answer()
    print("test_ai_cancel OK")
