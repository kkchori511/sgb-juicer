"""Codex 검토(docs/review/codex_ocr_hybrid.md) H1~L1 회귀 시험: 실제 API 없이 가짜 응답으로."""
import json, os, sys, tempfile, threading, time
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import requests
from app import config, ocr, ocr_compare as oc, ocr_vision as ov, openrouter
from app.api import Api

FX = os.path.join(os.path.dirname(__file__), "fixtures", "ocr_dummy")
PDF = os.path.join(FX, "dummy.pdf")
QWEN = [json.load(open(os.path.join(FX, f"qwen_p{i}.json"), encoding="utf-8"))["result"] for i in (1, 2)]
openrouter.balance = lambda key: 1.0


def ok(r):
    assert r.get("ok"), r
    return r


def L(t):
    return {"lines": [{"text": x, "box": None} for x in t.split("\n")]}


def Q(t, f=()):
    return {"lines": [{"text": x, "unreadable": False} for x in t.split("\n")], "figures": list(f)}


def test_pure():
    # M4 ℃ 일부만 다름, M5 끼워 넣기 띄어쓰기·줄, 빠진 글자
    for a, b in [("물은 100℃에서", "물은 100°F에서"), ("물을 끓였다.", "물을 더 끓였다."),
                 ("비커 준비\n물 가열", "비커 준비\n온도 측정\n물 가열"), ("잎 2장을 골라 물에", "잎 2장을 물에")]:
        c = oc.compare(L(a), Q(b))
        assert oc.resolve(c, {"d": {d["id"]: {"pick": "ai"} for d in c["diffs"]}}, False) == b, (a, b)
        assert oc.resolve(c, {}, False) == a
    # L1 같은 줄 뒤 그림 설명 여러 개는 순서대로
    c = oc.compare(L("첫 줄\n둘째 줄"), Q("첫 줄\n둘째 줄", [{"after_line": 0, "desc": "첫 그림"}, {"after_line": 0, "desc": "둘째 그림"}]))
    t = oc.resolve(c, {}, True)
    assert t.index("첫 그림") < t.index("둘째 그림")
    # M9 후보 글자를 재배열해 만든 낱말은 ⚠
    d = {"id": "d0", "kind": "text", "clova": "가나다", "ai": "라마바"}
    assert oc.parse_fix({"items": [{"id": "d0", "pick": "merge", "text": "바나나"}]}, [d])["d0"]["new"] is True
    assert oc.parse_fix({"items": [{"id": "d0", "pick": "merge", "text": "가마"}]}, [d])["d0"]["new"] is False
    # M1 CLOVA 실패 쪽은 정상 Qwen 글, 둘 다 실패면 빈 글(실패 문구가 내용에 들어가지 않음)
    sc = {"pages": 2, "mode": "hybrid", "clova": [{"lines": [], "fail": "CLOVA 인식 실패"}, {"lines": [], "fail": "x"}],
          "ai": {"pages": [Q("Qwen 본문"), {"error": "e"}]}}
    assert oc.final_texts(sc) == ["Qwen 본문", ""]
    # 방식을 CLOVA만으로 바꾸면 Qwen 그림 설명이 끼어들지 않음
    sc2 = {"pages": 1, "mode": "clova", "clova": [L("본문")], "ai": {"pages": [Q("본문", [{"after_line": 0, "desc": "그림"}])]}}
    assert oc.final_texts(sc2) == ["본문"]


def test_vision_retry():
    """M11: 보낸 뒤 끊기면 다시 보내지 않고, 연결 전 실패만 한 번 더."""
    for exc, n, code in [(requests.ConnectTimeout("x"), 2, "down"), (requests.ReadTimeout("x"), 1, "unknown"),
                         (requests.ConnectionError("RemoteDisconnected"), 1, "unknown")]:
        calls = []
        def post(*a, **k):
            calls.append(1)
            raise exc
        try:
            ov.read_page("k", "m", b"x", post=post)
            raise AssertionError
        except ov.VisionError as e:
            assert len(calls) == n and e.code == code, (exc, calls, e.code)


def test_render_threads():
    """H1: 여러 스레드가 동시에 그려도 잠금으로 하나씩(충돌 없이 모두 PNG)."""
    out, errs = [], []
    def go(i):
        try:
            out.append(ov.render_png(PDF, i % 2, 0.1, width=300))
        except Exception as e:
            errs.append(e)
    ts = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errs and len(out) == 6 and all(p.startswith(b"\x89PNG") for p in out)


class W:
    def __init__(self): self.events = []
    def create_file_dialog(self, *a, **k): return (PDF,)
    def evaluate_js(self, js): self.events.append(js)


def wait_idle(api):
    for _ in range(200):
        if api._busy.acquire(blocking=False):
            api._busy.release(); return
        time.sleep(0.05)
    raise AssertionError


def test_api():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "clova_url": "https://x", "clova_secret": "s"})
    api = Api(); w = W(); api.attach(w)
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 1, "class_no": 3}))["id"]
    sent = []
    ov.render_png = lambda pdf, page, mask=0.0, width=1400: (sent.append((page, mask)), f"P{page}".encode())[1]
    ov.read_page = lambda key, model, png, post=None: {**QWEN[int(png.decode()[1:])], "cost": 0.001, "provider": "x", "model": model}
    # H2: 하이브리드도 가림 0%는 동의 없이 못 보냄, 비정상 값도 거부
    bid = ok(api.inbox_create("가림", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid))
    r = api.inbox_scan_ocr(bid, 1, "hybrid", {"mask": 0})
    assert not r["ok"] and "동의" in r["error"] and not sent
    for bad in (-0.1, 0.9, "x"):
        assert not api.inbox_scan_ocr(bid, 1, "hybrid", {"mask": bad})["ok"]
    # M3: CLOVA 첫 묶음 뒤 중지 → 받은 쪽은 저장, 다시 하면 남은 쪽만
    clova_calls = []
    def fake_pages(path, url, secret, lang, progress=None, should_stop=None, pages=None, on_chunk=None):
        pages = list(range(2)) if pages is None else list(pages)
        clova_calls.append(list(pages))
        first = {pages[0]: L(f"CLOVA {pages[0]}쪽")}
        on_chunk(first)
        if len(pages) > 1 and not FAIL_DONE:
            FAIL_DONE.append(1)
            raise ocr.OcrError("뒤 묶음 실패")
        rest = {p: L(f"CLOVA {p}쪽") for p in pages[1:]}
        if rest:
            on_chunk(rest)
        return []
    FAIL_DONE = []
    ocr.ocr_pdf_pages = fake_pages
    ok(api.inbox_scan_ocr(bid, 1, "clova")); wait_idle(api)
    assert any('"ocr_error"' in e for e in w.events)
    ok(api.inbox_scan_ocr(bid, 1, "clova")); wait_idle(api)
    assert clova_calls == [[0, 1], [1]], clova_calls
    assert ok(api.inbox_scan_groups(bid))["page_texts"] == ["CLOVA 0쪽", "CLOVA 1쪽"]
    # M2: CLOVA가 전부 실패해도 이미 받은 Qwen 결과만으로 'Qwen만'으로 바꾸면 다시 부르지 않고 넘어감
    bid2 = ok(api.inbox_create("부분 성공", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid2))
    def boom(*a, **k):
        clova_calls.append("boom")
        raise ocr.OcrError("CLOVA 키 오류")
    ocr.ocr_pdf_pages = boom
    ok(api.inbox_scan_ocr(bid2, 1, "hybrid", {"mask": 0.14})); wait_idle(api)
    n_sent = len(sent)
    assert n_sent == 2
    r = ok(api.inbox_scan_ocr(bid2, 1, "ai", {"mask": 0.14})); wait_idle(api)
    assert r["ai_pages"] == 0 and len(sent) == n_sent
    g = ok(api.inbox_scan_groups(bid2))
    assert g["mode"] == "ai" and g["page_texts"][0].startswith("탐구 주제")
    # M6: 같은 쪽 두 고르기를 동시에 저장해도 둘 다 남음
    ib = api._ib()
    from app import ocr as _o
    clova = json.load(open(os.path.join(FX, "clova_raw.json"), encoding="utf-8"))
    bid3 = ok(api.inbox_create("동시", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid3))
    ib.scan_set_mode(bid3, "hybrid", 1, 0.14, "m")
    ib.scan_store(bid3, "clova", pages=[_o.image_lines(im) for im in clova["images"]])
    for i in (0, 1):
        ib.scan_store(bid3, "ai", ai_page=(i, {**QWEN[i], "cost": 0}))
    ids = [d["id"] for d in ib.scan_compare(bid3, 0)["cmp"]["diffs"] if d["kind"] == "text"]
    ts = [threading.Thread(target=lambda k=k: api.inbox_scan_decide(bid3, 0, {"d": {k: {"pick": "ai"}}})) for k in ids]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert set(ib.scan_compare(bid3, 0)["review"]["d"]) == set(ids)
    # R5: 없는 쪽은 오류
    assert not api.inbox_scan_compare(bid3, 2)["ok"] and not api.inbox_scan_compare(bid3, -1)["ok"]
    # R4: 매칭으로 넘어간 뒤에는 검토 저장·AI 제안을 받지 않음
    ok(api.inbox_scan_confirm(bid3, [0, 1], []))
    r = api.inbox_scan_decide(bid3, 0, {"d": {ids[0]: {"pick": "clova"}}})
    assert not r["ok"] and "매칭" in r["error"]
    assert not api.inbox_scan_suggest(bid3, 0)["ok"]
    # R8: Qwen만 → 하이브리드로 CLOVA만 더함(Qwen 다시 안 보냄)
    n_sent = len(sent)
    ocr.ocr_pdf_pages = lambda *a, pages=None, on_chunk=None, **k: on_chunk({p: L(f"CLOVA {p}") for p in pages}) or []
    r = ok(api.inbox_scan_ocr(bid2, 1, "hybrid", {"mask": 0.3})); wait_idle(api)
    assert r["clova"] and r["ai_pages"] == 0 and len(sent) == n_sent
    g = ok(api.inbox_scan_groups(bid2))
    assert g["mode"] == "hybrid" and len(g["review"]) == 2


def test_round2():
    """Codex 재검토(docs/review/codex_ocr_hybrid_2.md) R1~R6."""
    from app import scan
    import pypdfium2.raw as raw
    # R1: 비트맵 해제도 PDFium 잠금 안에서
    seen = []
    real = raw.FPDFBitmap_Destroy
    def watch(bm):
        seen.append(scan.PDFIUM_LOCK._is_owned())
        return real(bm)
    raw.FPDFBitmap_Destroy = watch
    try:
        REAL_RENDER(PDF, 0, 0.1, width=200)
    finally:
        raw.FPDFBitmap_Destroy = real
    assert seen and all(seen), seen
    # R2: n학년 n반 n번 세 숫자 모두 지움
    assert oc.redact("1학년 3반 99번 이름: 마바사", [], [scan.RE_GCN, scan.RE_NAME_LABEL]) == "○학년 ○반 ○○번 이름: ○○○"
    # R3: 줄 끝을 바꾼 자리 뒤 그림 설명은 제 줄에
    c = oc.compare(L("가나다\n라 마바"), Q("가나타\n라 마바", [{"after_line": 0, "desc": "장치 그림"}]))
    assert oc.resolve(c, {"d": {"d0": {"pick": "ai"}}}, True) == "가나타\n[그림: 장치 그림]\n라 마바"
    assert oc.resolve(c, {}, True) == "가나다\n[그림: 장치 그림]\n라 마바"
    # R6: 후보 그대로면 긴 글이어도 ⚠ 아님, 긴 합친 글은 '확인 못 함'
    d = {"id": "d0", "kind": "text", "clova": "가" * 61, "ai": "나"}
    assert oc.parse_fix({"items": [{"id": "d0", "pick": "clova"}]}, [d])["d0"]["new"] is False
    m = oc.parse_fix({"items": [{"id": "d0", "pick": "merge", "text": "가" * 61 + "나"}]}, [d])["d0"]
    assert m["new"] is False and m["unchecked"] is True


REAL_RENDER = ov.render_png


if __name__ == "__main__":
    test_pure()
    test_vision_retry()
    test_render_threads()
    test_round2()
    test_api()
    print("OCR REVIEW FIXES OK")
