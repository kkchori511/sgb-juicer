"""v0.31 기재 유의어: 기본 목록(다음·라인·웨이브·줌은 영어로만, 메타인지·메타버스 제외), 찾기 규칙, AI 지침, 저장·엑셀."""
import json
import os
import re
import shutil
import subprocess
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
from app.textutil import count_bytes  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLES = ["‘책’을 읽고 “좋다”고 함", "국어·수학, 1·2학기", "① 발표 → 토론 10㎝ 漢字 😀 끝", 'a"b`c', "줄\n바꿈\r\n끝",
           "평범한 글(50%), 질문? 감탄! 1/2 ~ 3: 'ok' - 끝.", "탭\t*#@<>[]{}&+=_;ㅋㅋ", ""]


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


def test_chars_and_bytes():
    # 쓸 수 있는 글자 밖은 한 글자씩 형광펜(사용자 지정 2026-11-23)
    hits = lambda t: [(h[2], h[3]) for h in banned.find(t, [])]
    assert hits("평범한 글(50%), 질문? 감탄! 1/2 ~ 3: 'ok' - 끝.\n다음 줄") == []
    assert hits("‘책’과 “말” 그리고 \"x\"") == [("‘", "작은따옴표(')로"), ("’", "작은따옴표(')로"), ("“", "작은따옴표(')로"),
                                             ("”", "작은따옴표(')로"), ('"', "작은따옴표(')로"), ('"', "작은따옴표(')로")]
    assert [w for w, _ in hits("국어·수학 ①→㎝漢😀ㅋ*#")] == ["·", "①", "→", "㎝", "漢", "😀", "ㅋ", "*", "#"]
    assert hits("국어·수학")[0][1] == "쉼표나 '와/과'로"
    assert "[쓰는 글자" in banned.rule()
    # 바이트: UTF-8 + 줄바꿈 2
    assert count_bytes("가a 1") == 6
    assert count_bytes("·") == 2 and count_bytes("‘’") == 6 and count_bytes("①漢") == 6 and count_bytes("😀") == 4
    assert count_bytes("가\n나") == 8 and count_bytes("가\r\n나") == 8 and count_bytes("") == 0 and count_bytes(None) == 0


def test_js_same_rules():
    """app.js의 BAN_CHAR·banCharRepl·bytesOf가 Python과 같은 결과인지 node로 대조(node 없으면 건너뜀)."""
    node = shutil.which("node")
    if not node:
        print("node 없음: JS 대조 건너뜀")
        return
    js = open(os.path.join(ROOT, "app", "web", "app.js"), encoding="utf-8").read()
    pick = lambda pat: re.search(pat, js, re.S).group(0)
    code = "\n".join([pick(r"const BAN_CHAR = [^\n]+"), pick(r"const banCharRepl = [^\n]+"), pick(r"const UTF8 = [^\n]+"),
                      pick(r"function bytesOf\(t\) \{.*?\n  \}"),
                      "const S = JSON.parse(process.argv[1]);",
                      "console.log(JSON.stringify(S.map((t) => [[...t.matchAll(BAN_CHAR)].map((m) => [m[0], banCharRepl(m[0])]), bytesOf(t)])));"])
    out = json.loads(subprocess.run([node, "-e", code, json.dumps(SAMPLES)], capture_output=True, text=True, check=True).stdout)
    want = [[[[h[2], h[3]] for h in banned.find(t, [])], count_bytes(t)] for t in SAMPLES]
    assert out == want, (out, want)


if __name__ == "__main__":
    test_all()
    test_chars_and_bytes()
    test_js_same_rules()
    print("BANNED OK")
