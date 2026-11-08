import os, sys, tempfile, time
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, ocr, openrouter, scan
from app.api import Api

HERE = os.path.dirname(__file__)
PDF = os.path.join(HERE, "fixtures", "scan_sample.pdf")  # 6쪽: 학생 3명 × 2쪽(마지막 쪽 백지)
OCR_TEXT = ["2학년 3반 1번 이름: 김철수\n진로 독서 감상문\n책을 읽고 감명받음.", "(뒷면) 실험 실패를 기록하겠다.",
            "학번 20302 성명 이영희\n직업 탐색 보고서", "(뒷면) 윤리 문제도 생각함.", "20303 박민순\n꿈 발표 준비", ""]
CALLS = []
def fake_ocr(path, url, secret, lang, progress=None, should_stop=None):
    CALLS.append(path)
    if progress: progress(0, 1, 6)
    return list(OCR_TEXT)
ocr.ocr_pdf = fake_ocr
SENT = []
openrouter.chat = lambda key, model, system, user, privacy_block=False: (SENT.append(user) or ("정제: " + user, 0.0))
openrouter.balance = lambda key: 1.0

def ok(r):
    assert r.get("ok"), r
    return r

def wait_idle(api):
    for _ in range(100):
        if api._busy.acquire(blocking=False):
            api._busy.release(); return
        time.sleep(0.05)
    raise AssertionError("OCR이 끝나지 않음")

class FakeWindow:
    def __init__(self): self.events = []
    def create_file_dialog(self, *a, **k): return (PDF,)
    def evaluate_js(self, js): self.events.append(js)

def test():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api(); w = FakeWindow(); api.attach(w)
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김철수\n20302\t이영희\n20303\t박민수")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    bid = ok(api.inbox_create("진로 학습지", hr, "career"))["id"]
    assert not ok(api.clova_ready())["ready"]
    sc = ok(api.inbox_scan_pick(bid))["scan"]; assert sc["pages"] == 6 and scan.pdf_path(2026, bid).exists()
    assert not api.inbox_scan_ocr(bid, 2)["ok"]  # CLOVA 키 없음
    config.save({"clova_url": "https://x", "clova_secret": "s"})
    ok(api.inbox_scan_ocr(bid, 2)); wait_idle(api)
    assert any("ocr_done" in e for e in w.events), w.events
    g = ok(api.inbox_scan_groups(bid))
    assert [x["pages"] for x in g["groups"]] == [[0, 1], [2, 3], [4, 5]]
    assert [(x["ext_no"], x["ext_name"]) for x in g["groups"]] == [("20301", "김철수"), ("20302", "이영희"), ("20303", "박민순")]
    assert "김철수" not in g["groups"][0]["content"] and "20301" not in g["groups"][0]["content"] and "진로 독서" in g["groups"][0]["content"]
    # 다시 묶기: 6쪽(백지) 빼고 1쪽만 따로
    g2 = ok(api.inbox_scan_groups(bid, [0, 1, 2, 4], [5]))
    assert [x["pages"] for x in g2["groups"]] == [[0], [1], [2, 3], [4]]
    assert ok(api.inbox_scan_confirm(bid, [0, 2, 4], [5]))["count"] == 3
    v = ok(api.inbox_view(bid))
    st = [(r["source_ref"], r["state"], r["student_no"]) for r in v["rows"]]
    assert st == [("1~2쪽", "confirmed", "20301"), ("3~4쪽", "confirmed", "20302"), ("5쪽", "suggested", "20303")], st
    assert v["rows"][0]["pages"] == "0,1"
    assert ok(api.inbox_scan_text(bid, [0]))["pages"][0]["text"].startswith("2학년")
    assert ok(api.inbox_page_image(bid, 0))["src"].startswith("data:image/png;base64,")
    ok(api.inbox_confirm_suggested(bid)); ok(api.inbox_stage(bid, "refine"))
    for r in v["rows"]:
        ok(api.ai_inbox_row(r["id"]))
    for u in SENT:
        for leak in ("김철수", "20301", "이영희", "20302", "박민순", "20303"):
            assert leak not in u, (leak, u)
    ok(api.inbox_stage(bid, "review")); res = ok(api.inbox_send(bid)); assert res["records"] == 3
    rec = ok(api.student_view(hr, "career", "20301"))["records"][0]
    assert rec["title"] == "진로 학습지" and rec["content"].startswith("정제:")
    # 묶음 삭제하면 스캔 파일도 지움
    b2 = ok(api.inbox_create("x", hr, "career"))["id"]; ok(api.inbox_scan_pick(b2)); assert scan.pdf_path(2026, b2).exists()
    ok(api.inbox_delete(b2)); assert not scan.pdf_path(2026, b2).exists()
    print("SCAN OK")

if __name__ == "__main__":
    test()
