"""Qwen이 못 읽은 쪽 [이 쪽 다시 시도](사용자 지정 2026-11-25): 그 쪽만 다시 보내 저장, 실패·중지·이미 읽은 쪽 처리."""
import os
import sys
import tempfile

os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, ocr_vision, openrouter  # noqa: E402
from app.api import Api  # noqa: E402

PDF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "ocr_dummy", "dummy.pdf")
openrouter.balance = lambda key: 1.0


class W:
    def create_file_dialog(self, *a, **k):
        return (PDF,)

    def evaluate_js(self, js):
        pass


def ok(r):
    assert r.get("ok"), r
    return r


def L(t):
    return {"lines": [{"text": x, "box": None} for x in t.split("\n")]}


def test_retry():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "clova_url": "https://x", "clova_secret": "s", "ocr_ai_model": "qm"})
    api = Api()
    api.attach(W())
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 1, "class_no": 3}))["id"]
    bid = ok(api.inbox_create("다시", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid))
    ib = api._ib()
    ib.scan_set_mode(bid, "hybrid", 1, 0.14, "qm")
    ib.scan_store(bid, "clova", pages=[L("첫 쪽 글"), L("둘째 쪽 글")])
    ib.scan_store(bid, "ai", ai_page=(0, {"error": "OpenRouter가 응답하지 않습니다", "sent": True}))
    ib.scan_store(bid, "ai", ai_page=(1, {"lines": [{"text": "둘째 쪽 글", "unreadable": False}], "figures": [], "cost": 0}))
    r = ok(api.inbox_scan_compare(bid, 0))
    assert r["ai_error"] and r["ai"] is None

    sent = []
    ocr_vision.render_png = lambda pdf, i, mask: (sent.append((i, mask)) or b"png")

    # 실패: 이유를 알리고 오류를 저장(다른 쪽은 보내지 않음)
    def bad(key, model, png, post=None):
        raise ocr_vision.VisionError("형식이 올바르지 않습니다", "bad")

    ocr_vision.read_page = bad
    openrouter.reset()
    r = api.inbox_scan_retry_ai(bid, 0)
    assert not r["ok"] and "다시 읽지 못했습니다" in r["error"], r
    assert sent == [(0, 0.14)], sent  # 그 쪽만, 처음 가림 비율 그대로

    # 성공: 그 쪽 결과 저장, 비교가 생김
    def good(key, model, png, post=None):
        assert model == "qm"
        return {"lines": [{"text": "첫 쪽 글", "unreadable": False}], "figures": [], "cost": 0.002, "provider": "p", "model": "qm"}

    ocr_vision.read_page = good
    r = ok(api.inbox_scan_retry_ai(bid, 0))
    assert r["ai"] == "첫 쪽 글" and not r["ai_error"] and r["retry_cost"] == 0.002, r
    # 이미 읽은 쪽은 다시 보내지 않음
    r = api.inbox_scan_retry_ai(bid, 1)
    assert not r["ok"] and "이미 읽었습니다" in r["error"]

    # [바로 중지] 뒤에 온 답은 저장하지 않음
    ib.scan_store(bid, "ai", ai_page=(0, {"error": "x", "sent": True}))

    def late(key, model, png, post=None):
        openrouter.cancel()
        return good(key, model, png)

    ocr_vision.read_page = late
    r = api.inbox_scan_retry_ai(bid, 0)
    assert not r["ok"] and "중지" in r["error"]
    assert ok(api.inbox_scan_compare(bid, 0))["ai_error"] == "x"
    openrouter.reset()

    # CLOVA만 읽은 묶음에서는 막힘
    ib.scan_set_mode(bid, "clova", 1, None, None)
    r = api.inbox_scan_retry_ai(bid, 0)
    assert not r["ok"]


if __name__ == "__main__":
    test_retry()
    print("QWEN RETRY OK")
