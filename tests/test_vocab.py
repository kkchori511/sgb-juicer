"""v0.31 세특 어휘: 기본 목록, 저장·끄기, 세특(subject) AI 호출에만 붙음, 엑셀 읽기(머리글 없음 3열 / 머리글 있음)."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter, vocab  # noqa: E402

CALLS = []
openrouter.chat = lambda key, model, system, user, privacy_block=False, history=None: (CALLS.append(system) or "결과", 0.0)
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_all():
    import openpyxl
    api = Api()
    v = ok(api.vocab_get())
    assert v["is_default"] and v["vocab"]["on"] and "탁월하다" in v["vocab"]["evals"] and "지어내다" not in v["vocab"]["verbs"]
    assert "나무랄 데 없다" in v["vocab"]["evals"] and len(set(v["vocab"]["verbs"])) == len(v["vocab"]["verbs"])
    # 세특에만 붙는다
    api._call_ai("k", "m", "기본", "글", False, item="subject")
    assert "[세특 어휘" in CALLS[-1] and "탁월하다" in CALLS[-1]
    api._call_ai("k", "m", "기본", "글", False, item="career")
    assert "[세특 어휘" not in CALLS[-1]
    # 저장(겹침 정리)·끄기
    s = ok(api.vocab_save({"on": True, "verbs": ["분석하다", "분석하다", " 탐구하다 "], "evals": ["돋보이다"]}))["vocab"]
    assert s["verbs"] == ["분석하다", "탐구하다"] and not ok(api.vocab_get())["is_default"]
    api._call_ai("k", "m", "기본", "글", False, item="subject")
    assert "분석하다, 탐구하다" in CALLS[-1] and "탁월하다" not in CALLS[-1]
    ok(api.vocab_save({"on": False, "verbs": ["분석하다"], "evals": []}))
    api._call_ai("k", "m", "기본", "글", False, item="subject")
    assert "[세특 어휘" not in CALLS[-1]
    # 엑셀: 머리글 없음 3열(원본 모양) → 1·2열 동사, 3열 평가
    p = os.path.join(DATA, "v.xlsx")
    wb = openpyxl.Workbook(); ws = wb.active
    for r in [["가려내다", "세분하다", "우월하다"], ["기술하다", "가려내다", "매우"], [None, None, "잘"]]:
        ws.append(r)
    wb.save(p)
    n = ok(api.vocab_import(p))["vocab"]
    assert n["verbs"] == ["가려내다", "세분하다", "기술하다"] and n["evals"] == ["우월하다", "매우", "잘"] and n["on"] is False  # 켜짐 여부는 그대로
    # 내려받기 모양(머리글 있음)도 다시 읽힌다
    vocab.to_xlsx(n, p)
    assert vocab.from_xlsx(p)["verbs"] == n["verbs"]
    # 기본으로
    assert ok(api.vocab_reset())["vocab"]["on"] and ok(api.vocab_get())["is_default"]


if __name__ == "__main__":
    test_all()
    print("VOCAB OK")
