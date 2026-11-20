"""v0.31 예시 목록: 기본 예시 68개('[과목] 첫 구절'), 고치기·더하기·지우기·기본 되돌리기, 확인 창에서 고른 예시로 이번 실행의 예시 바꾸기."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter  # noqa: E402

openrouter.chat = lambda *a, **k: ("결과", 0.0)
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_all():
    api = Api()
    L = ok(api.examples_list())["examples"]
    assert len(L) == 68 and all(e["builtin"] and e["item"] == "subject" for e in L)
    first = L[0]
    assert first["label"].startswith(f"[{first['subject']}] ") and first["source"].startswith("교과세특 기재 예시 도움 자료(고)")
    # 고치기(기본 예시도), 이름 직접 주기
    e = ok(api.example_save({**first, "name": "내 이름", "text": "고친 예시 글임."}))["example"]
    assert e["id"] == first["id"] and e["builtin"] and e["label"] == "내 이름"
    # 새 예시
    n = ok(api.example_save({"item": "career", "subject": "", "text": "진로 예시 글임. 둘째 문장."}))["example"]
    assert n["id"].startswith("my_") and not n["builtin"] and n["label"] == "진로 예시 글임."
    assert not api.example_save({"text": "  "})["ok"]
    # 지우기 → 기본 되돌리기: 기본은 처음 모양으로, 직접 만든 것은 남음
    ok(api.example_delete(L[1]["id"]))
    assert len(ok(api.examples_list())["examples"]) == 68  # 68 - 1 + 새 예시 1
    R = ok(api.examples_reset_builtin())["examples"]
    assert len(R) == 69 and R[0]["text"] == first["text"] and R[0]["name"] == "" and any(x["id"] == n["id"] for x in R)
    # 확인 창에서 고른 예시: 이번 실행의 예시만 바뀐다
    base = api._prompt("refine")["example"]
    ok(api.ai_extra_set("", "", "", L[5]["id"]))
    assert api._prompt("refine")["example"] == L[5]["text"]
    ok(api.ai_extra_set("", "", "", "none"))
    assert api._prompt("refine")["example"] == ""
    ok(api.ai_extra_set("", "", "", ""))
    assert api._prompt("refine")["example"] == base
    assert config.load()["example_lib"]


if __name__ == "__main__":
    test_all()
    print("EXAMPLES OK")
