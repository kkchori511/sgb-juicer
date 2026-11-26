"""단 나누기 설정(사용자 지정 2026-11-26): 저장할 때 배치, 읽은 뒤 바꾸면 다시 부르지 않고 다시 배치, 고른 것 정리."""
import os
import sys
import tempfile

os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter  # noqa: E402
from app.api import Api  # noqa: E402
from tests.test_ocr_layout import page  # noqa: E402

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


def test_store_and_switch():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "clova_url": "https://x", "clova_secret": "s"})
    api = Api()
    api.attach(W())
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 1, "class_no": 3}))["id"]
    bid = ok(api.inbox_create("2단", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid))
    ib = api._ib()
    ib.scan_set_mode(bid, "clova", 1)
    ib.scan_store(bid, "clova", pages=[page(), page(deg=3)])
    r = ok(api.inbox_scan_compare(bid, 0))
    assert r["layout"]["cols"] == 2 and r["final"].split("\n")[0].startswith("L0_0") and r["final"].split("\n")[8].startswith("R0_0"), r["final"]
    g = ok(api.inbox_scan_groups(bid, [0, 1], []))
    assert g["cols"] == "auto" and g["has_words"] and g["layouts"][1]["cols"] == 2

    # 나누지 않음으로 바꾸면 CLOVA 줄 그대로(다시 부르지 않음)
    res = ok(api.inbox_scan_set_cols(bid, "off"))
    assert res["changed"] == [0, 1]
    assert ok(api.inbox_scan_compare(bid, 0))["final"] == "섞인 원래 줄"
    # 다시 자동으로
    ok(api.inbox_scan_set_cols(bid, "auto"))
    assert ok(api.inbox_scan_compare(bid, 1))["final"].startswith("L0_0")
    assert not api.inbox_scan_set_cols(bid, "x")["ok"]

    # 읽을 단: 오른쪽만 → 오른쪽 단 줄만, 그림 위치(cut)도 알려 줌
    ok(api.inbox_scan_set_cols(bid, "auto", "right"))
    r = ok(api.inbox_scan_compare(bid, 0))
    assert r["final"].split("\n")[0].startswith("R0_0") and "L0_0" not in r["final"], r["final"]
    assert r["layout"]["side"] == "right" and len(r["layout"]["cut"]) == 2
    from app import ocr_layout
    assert 0.4 < ocr_layout.cut_frac({"w": 1400, "layout": r["layout"]}) < 0.6

    # Qwen 결과가 있는 하이브리드에서 읽을 단을 바꾸면 Qwen 결과는 지움(그림 범위가 달라짐)
    ib.scan_set_mode(bid, "hybrid", 1, 0.1, "q")
    ib.scan_store(bid, "ai", ai_page=(0, {"lines": [{"text": "R0_0", "unreadable": False}], "figures": [], "cost": 0}))
    res = ok(api.inbox_scan_set_cols(bid, "auto", "both"))
    assert res["ai_reset"] == 1
    assert not any(ib._scan(bid)[1]["ai"]["pages"])
    # 단 나누기만 바꾸면 Qwen 결과는 그대로
    ib.scan_store(bid, "ai", ai_page=(0, {"lines": [{"text": "x", "unreadable": False}], "figures": [], "cost": 0}))
    assert ok(api.inbox_scan_set_cols(bid, "two", "both"))["ai_reset"] == 0


def test_crop_png():
    from app import ocr_vision
    full = ocr_vision.render_png(PDF, 0, 0.0, width=400)
    right = ocr_vision.render_png(PDF, 0, 0.1, width=400, keep=("right", 0.5))
    left = ocr_vision.render_png(PDF, 0, 0.0, width=400, keep=("left", 0.3))
    import struct
    wh = lambda png: struct.unpack(">II", png[16:24])  # noqa: E731 — PNG IHDR 너비·높이
    assert wh(full)[0] == 400 and wh(right) == (200, wh(full)[1]) and wh(left)[0] == 120, (wh(full), wh(right), wh(left))


if __name__ == "__main__":
    test_store_and_switch()
    test_crop_png()
    print("LAYOUT STORE OK")
