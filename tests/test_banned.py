"""v0.31 기재 유의어: 기본 목록(다음·라인·웨이브·줌은 영어로만, 메타인지·메타버스 제외), 찾기 규칙, AI 지침, 저장·엑셀."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import banned, openrouter  # noqa: E402

CALLS = []
openrouter.chat = lambda key, model, system, user, privacy_block=False, history=None: (CALLS.append(system) or "결과", 0.0)
openrouter.balance = lambda key: 1.0
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def words(t):
    return [h[2] for h in banned.find(t)]


def test_all():
    api = Api()
    lib = ok(api.banned_get())["lib"]
    assert len(lib) == 61 and ok(api.banned_get())["is_default"]
    # 영어로만: 다음·라인·웨이브·줌은 한글로 찾지 않음
    assert words("다음 시간에 라인을 긋고 웨이브와 줌 기능") == []
    assert words("Daum, LINE, wave, Zoom 사용") == ["Daum", "LINE", "wave", "Zoom"]
    # 한글로도: 알로·블로·테드
    assert words("알로와 블로로 편집하고 테드 강연") == ["알로", "블로", "테드"]
    # 메타: 찾되 메타인지·메타버스는 제외
    assert words("메타인지와 메타버스, 메타 플랫폼") == ["메타"]
    # 대소문자·띄어쓰기·낱말 전체
    assert words("chatgpt와 Chat GPT, ChatGPT") == ["chatgpt", "Chat GPT", "ChatGPT"]
    assert words("UNESCO와 UN, FUN 게임") == ["UNESCO", "UN"]
    assert words("구글문서로 공유") == ["구글문서"]  # 긴 것 우선(구글문서 > 구글)
    # AI 지침: 항목이 있는 호출에 붙음
    api._call_ai("k", "m", "기본", "글", False, item="career")
    assert "[기재 유의어" in CALLS[-1] and "유튜브" in CALLS[-1]
    api._call_ai("k", "m", "기본", "글", False)
    assert "[기재 유의어" not in CALLS[-1]
    # 저장·되돌리기·엑셀
    s = ok(api.banned_save([{"terms": "Notion, 노션", "repl": "협업 도구", "except": ""}, {"terms": " ", "repl": "x"}]))["lib"]
    assert s == [{"terms": ["Notion", "노션"], "repl": "협업 도구", "except": []}] and not ok(api.banned_get())["is_default"]
    assert words("노션에 정리") == ["노션"]
    p = os.path.join(DATA, "b.xlsx")
    banned.to_xlsx(banned.load(), p)
    assert ok(api.banned_import(p))["lib"] == s
    assert len(ok(api.banned_reset())["lib"]) == 61


if __name__ == "__main__":
    test_all()
    print("BANNED OK")
