"""v0.35 하이브리드 OCR: 저장된 실제 응답(더미 학습지)으로 비교·검토·최종 글, API 한 번만 부르기, 머리글 가림."""
import json, os, sys, tempfile, time
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, ocr, ocr_compare as oc, ocr_vision as ov, openrouter, scan
from app.api import Api

FX = os.path.join(os.path.dirname(__file__), "fixtures", "ocr_dummy")
PDF = os.path.join(FX, "dummy.pdf")
CLOVA = json.load(open(os.path.join(FX, "clova_raw.json"), encoding="utf-8"))
QWEN = [json.load(open(os.path.join(FX, f"qwen_p{i}.json"), encoding="utf-8"))["result"] for i in (1, 2)]

CALLS = {"clova": 0, "ai": []}


def fake_call_once(url, secret, data, name, lang):
    CALLS["clova"] += 1
    return CLOVA


SENT = []  # (쪽, 가림 비율)
REAL_RENDER = ov.render_png


def fake_render(pdf, page, mask=0.0, width=ov.RENDER_WIDTH):
    SENT.append((page, mask))
    return f"P{page}".encode()


def fake_read_page(key, model, png, post=None):
    page = int(png.decode()[1:])
    CALLS["ai"].append(page)
    if FAIL.get(page):
        FAIL[page] -= 1
        raise ov.VisionError("OpenRouter가 응답하지 않습니다(HTTP 503).", "down")
    q = QWEN[page]
    return {"lines": q["lines"], "figures": q["figures"], "cost": 0.0015, "provider": "Parasail", "model": model}


FAIL = {}
ocr.call_once = fake_call_once
ov.read_page = fake_read_page
ov.render_png = fake_render
openrouter.balance = lambda key: 1.0


def ok(r):
    assert r.get("ok"), r
    return r


def wait_idle(api):
    for _ in range(200):
        if api._busy.acquire(blocking=False):
            api._busy.release(); return
        time.sleep(0.05)
    raise AssertionError("OCR이 끝나지 않음")


class FakeWindow:
    def __init__(self): self.events = []
    def create_file_dialog(self, *a, **k): return (PDF,)
    def evaluate_js(self, js): self.events.append(js)


def test_pure():
    """비교 엔진: 가린 머리글 빼기, ℃/°C 같게, 그림 속 글자, 고른 대로 최종 글."""
    cp = ocr.image_lines(CLOVA["images"][0])
    assert cp["lines"][0]["box"] and cp["w"] == 1190
    c = oc.compare(cp, QWEN[0], 0.14)
    got = [(d["kind"], d["clova"], d["ai"]) for d in c["diffs"]]
    assert got == [("text", "햇", "했"), ("figure", "온도계\n비커\n알코올램프", ""), ("text", "열", "얼")], got
    assert oc.unreviewed(c, {}) == 2
    t = oc.resolve(c, {}, True)
    assert "실험햇다" in t and "넣어 준 열은" in t and "학번: 10399" in t  # 기본은 CLOVA, 머리글은 그대로
    assert "[그림:" in t and "\n온도계\n비커\n" not in t  # 그림 설명이 이름표 줄을 대신
    t2 = oc.resolve(c, {"d": {"d0": {"pick": "ai"}, "d2": {"pick": "edit", "text": "열"}}}, False)
    assert "실험했다" in t2 and "[그림:" not in t2 and "\n온도계\n비커\n알코올램프\n" in t2
    c2 = oc.compare(ocr.image_lines(CLOVA["images"][1]), QWEN[1], 0.14)
    assert [(d["clova"], d["ai"]) for d in c2["diffs"]] == [("잎", "일"), ("골라", ""), (".", "")]
    t3 = oc.resolve(c2, {"d": {"d2": {"pick": "ai"}}}, True)
    assert "5분에는 3개, 10분에는" in t3  # 지운 뒤 겹 띄어쓰기 없음
    # 머리글을 안 가렸으면 머리글이 차이로 잡힌다(가림 비율을 맞게 넘기는지 확인용)
    assert any("10399" in d["clova"] for d in oc.compare(cp, QWEN[0], 0)["diffs"])
    # 크게 다른 페이지는 통째로
    big = oc.compare(cp, {"lines": [{"text": "전혀 다른 글자들 가나다라마바사", "unreadable": False}], "figures": []}, 0.14)
    assert big["big"] and oc.unreviewed(big, {}) == 1 and oc.unreviewed(big, {"page": "ai"}) == 0
    # AI 단독 글과 그림 설명 끄기
    assert ov.page_text(QWEN[0], True).count("[그림:") == 1 and "[그림:" not in ov.page_text(QWEN[0], False)
    # 그림 설명이 그림 없는 쪽에 끼어들어도 끄면 빠진다
    # 모델 답 검사
    try:
        ov.parse("not json"); raise AssertionError
    except ov.VisionError:
        pass
    v = ov.parse('```json\n{"lines":[{"text":"가","unreadable":false}],"figures":[{"after_line":99,"desc":"그림"}]}\n```')
    assert v["figures"][0]["after_line"] == 0


def test_mask_png():
    """머리글 가림: 위쪽 비율만큼 흰색."""
    import struct, zlib
    png = REAL_RENDER(PDF, 0, 0.14, width=300)
    w, h = struct.unpack(">II", png[16:24])
    # IDAT 풀어서 맨 윗줄과 가린 영역 바로 아래 줄 비교
    idat = b"".join(png[i + 8:i + 8 + struct.unpack(">I", png[i:i + 4])[0]] for i in range(8, len(png) - 12) if png[i + 4:i + 8] == b"IDAT")
    raw = zlib.decompress(idat)
    ch = (len(raw) // h - 1) // w
    row = lambda y: raw[y * (w * ch + 1) + 1:(y + 1) * (w * ch + 1)]
    assert set(row(int(h * 0.14) - 1)) == {255}
    assert ov.payload("m", png)["provider"]["data_collection"] == "deny" and ov.payload("m", png)["provider"]["zdr"] is True


def test_api():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "clova_url": "https://x", "clova_secret": "s"})
    api = Api(); w = FakeWindow(); api.attach(w)
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 1, "class_no": 3}))["id"]
    p = api.roster_from_text("10399\t가나다\n10398\t라마바")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    bid = ok(api.inbox_create("과학 활동지", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid))
    ov.render_png = REAL_RENDER
    assert ok(api.inbox_scan_mask_preview(bid, 0.14))["src"].startswith("data:image/png")
    ov.render_png = fake_render
    FAIL[1] = 1  # 2쪽은 처음 한 번 실패
    ok(api.inbox_scan_ocr(bid, 1, "hybrid", {"mask": 0.14})); wait_idle(api)
    assert CALLS["clova"] == 1 and sorted(CALLS["ai"]) == [0, 1], CALLS
    assert any('"ocr_done"' in e and '"ai_failed": 1' in e for e in w.events), w.events[-3:]
    g = ok(api.inbox_scan_groups(bid))
    assert g["mode"] == "hybrid" and g["review"][0]["left"] == 2 and g["review"][1].get("ai_error")
    assert [(x["ext_no"], x["ext_name"]) for x in g["groups"]] == [("10399", "가나다"), ("10399", "가나다")]
    # 다시 실행: CLOVA는 다시 부르지 않고, 실패한 2쪽만 AI로
    ok(api.inbox_scan_ocr(bid, 1, "hybrid", {"mask": 0.3})); wait_idle(api)
    assert CALLS["clova"] == 1 and sorted(CALLS["ai"]) == [0, 1, 1], CALLS
    assert {m for _, m in SENT} == {0.14}, SENT
    g = ok(api.inbox_scan_groups(bid))
    assert g["review"][1]["left"] == 3
    # 이미 보낸 쪽이 있으면 가림 비율은 처음 값(0.14) 그대로
    assert ok(api.inbox_scan_compare(bid, 0))["cmp"]["diffs"][0]["clova"] == "햇"
    # 검토: 한 곳 고르기, 이 쪽 모두 AI, 그림 설명 끄기
    cmpr = ok(api.inbox_scan_decide(bid, 0, {"d": {"d0": {"pick": "ai"}}}))
    assert cmpr["unreviewed"] == 1 and "실험했다" in cmpr["final"]
    cmpr = ok(api.inbox_scan_decide(bid, 1, {"all_ai": True}))
    assert cmpr["unreviewed"] == 0 and "일이 빛을" in cmpr["final"]
    cmpr = ok(api.inbox_scan_decide(bid, 0, {"figs": False}))
    assert "[그림:" not in cmpr["final"] and "알코올램프\n그림처럼" in cmpr["final"]
    cmpr = ok(api.inbox_scan_decide(bid, 0, {"page": "edit", "text": "직접 쓴 글"}))
    assert cmpr["final"] == "직접 쓴 글"
    ok(api.inbox_scan_decide(bid, 0, {"reset": True}))
    d = ok(api.inbox_scan_compare(bid, 0))
    assert d["unreviewed"] == 2 and d["figs"] is False and "실험햇다" in d["final"]
    crop = ok(api.inbox_scan_crop(bid, 0, d["cmp"]["diffs"][0]["box"], d["w"], d["h"]))
    assert crop["src"].startswith("data:image/png")
    # 학생 묶기 확정: 최종 글이 쓰이고 학번·이름은 빠짐
    assert ok(api.inbox_scan_confirm(bid, [0, 1], []))["count"] == 2
    v = ok(api.inbox_view(bid))
    assert "일이 빛을" in v["rows"][1]["content"] and "가나다" not in v["rows"][1]["content"]
    # AI 단독: 가리지 않고 보내려면 동의가 필요
    bid2 = ok(api.inbox_create("AI 단독", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid2))
    r = api.inbox_scan_ocr(bid2, 1, "ai", {"mask": 0})
    assert not r["ok"] and "동의" in r["error"]
    config.save({"ocr_ai_consent": True})
    CALLS["ai"].clear()
    ok(api.inbox_scan_ocr(bid2, 1, "ai", {"mask": 0})); wait_idle(api)
    assert CALLS["clova"] == 1 and sorted(CALLS["ai"]) == [0, 1]
    g = ok(api.inbox_scan_groups(bid2))
    assert g["mode"] == "ai" and "[그림:" in g["page_texts"][0]
    # 키가 없으면 그 방식은 시작하지 않음
    config.save({"clova_secret": ""})
    assert not api.inbox_scan_ocr(bid2, 1, "hybrid")["ok"]
    # [OCR 다시 하기]
    ok(api.inbox_scan_reset(bid2, "all"))
    assert ok(api.inbox_view(bid2))["batch"]["meta"]["scan"]["ocr"] is None


if __name__ == "__main__":
    test_pure()
    test_mask_png()
    test_api()
    print("OCR HYBRID OK")
