"""기재 유의어(v0.31): 생기부에 쓰지 않는 말(상표·서비스 이름 등)과 대체 표현.

- 설정(config.json)의 banned_lib = [{terms: [표기…], repl: 대체 표현, except: [빼고 볼 말…]}]. 없으면 기본 목록(banned_default).
- 화면: 기록·결과·최종안에서 찾은 말을 형광펜으로 표시하고 대체 표현을 보여 준다(찾기는 app.js의 banFind와 같은 규칙).
- AI: 모든 항목의 AI 변환 지침에 '이 말 대신 대체 표현'을 붙인다(rule).
- 찾는 규칙: 영어 등 로마자 표기는 대소문자·띄어쓰기를 가리지 않고 낱말 전체가 맞을 때만, 한글 표기는 글 속 어디든(except에 든 말 안이면 뺌).
"""
import copy
import re

from . import banned_default, config
from .db import DbError

MAX_ROWS = 500


def _split(v):
    if isinstance(v, (list, tuple)):
        items = v
    else:
        items = str(v or "").split(",")
    out = []
    for x in items:
        x = " ".join(str(x or "").split())[:60]
        if x and x not in out:
            out.append(x)
    return out


def normalize(lib):
    if not isinstance(lib, list):
        raise DbError("기재 유의어 형식이 아닙니다.")
    out = []
    for e in lib[:MAX_ROWS]:
        if not isinstance(e, dict):
            continue
        terms = _split(e.get("terms"))
        if not terms:
            continue
        out.append({"terms": terms, "repl": " ".join(str(e.get("repl") or "").split())[:120], "except": _split(e.get("except"))})
    return out


def load():
    lib = config.load().get("banned_lib")
    try:
        return normalize(lib) if isinstance(lib, list) else normalize(copy.deepcopy(banned_default.BANNED))
    except DbError:
        return normalize(copy.deepcopy(banned_default.BANNED))


def is_default():
    return not isinstance(config.load().get("banned_lib"), list)


def save(lib):
    new = normalize(lib)
    config.save({"banned_lib": new})
    return new


def reset():
    config.save({"banned_lib": None})
    return load()


def _latin(t):
    return bool(re.search(r"[A-Za-z]", t)) and not re.search(r"[가-힣]", t)


def _pattern(t):
    if _latin(t):  # 대소문자·띄어쓰기 무시, 낱말 전체
        body = r"\s*".join(re.escape(ch) for ch in t.replace(" ", ""))
        return re.compile(r"(?<![A-Za-z0-9])" + body + r"(?![A-Za-z0-9])", re.I)
    return re.compile(re.escape(t))


# 쓸 수 있는 글자(사용자 지정 2026-11-23): 한글·영문·숫자·띄어쓰기·줄바꿈과 문장부호 . , ' ( ) - ~ % : / ? !
# 그 밖(큰따옴표·둥근 따옴표·가운뎃점·특수기호·한자·이모지 등)은 한 글자씩 형광펜. app.js의 BAN_CHAR와 같아야 한다.
BAD_CHAR = re.compile(r"[^가-힣A-Za-z0-9 \n\r.,'()\-~%:/?!]")


def char_repl(ch):
    if ch in "‘’“”\"`´′″＇＂":
        return "작은따옴표(')로"
    if ch in "·ㆍ･・•∙":
        return "쉼표나 '와/과'로"
    return "빼거나 한글로"


def find(text, lib=None):
    """글에서 찾은 [(시작, 끝, 찾은 글, 대체 표현)] — 겹치면 긴 것 우선. 쓰면 안 되는 글자도 한 글자씩."""
    lib = load() if lib is None else lib
    hits = [(m.start(), m.end(), m.group(0), char_repl(m.group(0))) for m in BAD_CHAR.finditer(text or "")]
    for e in lib:
        ex = [(m.start(), m.end()) for w in e["except"] for m in re.finditer(re.escape(w), text)]
        for t in e["terms"]:
            for m in _pattern(t).finditer(text):
                if any(a <= m.start() and m.end() <= b for a, b in ex):
                    continue
                hits.append((m.start(), m.end(), m.group(0), e["repl"]))
    hits.sort(key=lambda h: (h[0], -(h[1] - h[0])))
    out, end = [], -1
    for h in hits:
        if h[0] >= end:
            out.append(h)
            end = h[1]
    return out


CHAR_RULE = ("\n\n[쓰는 글자 — 항상 지킴]\n"
             "- 한글·영문·숫자·띄어쓰기·줄바꿈과 문장부호 . , ' ( ) - ~ % : / ? ! 만 쓴다.\n"
             "- 따옴표는 작은따옴표(')만 쓴다. 큰따옴표(\")·둥근 따옴표(‘ ’ “ ”)는 쓰지 않는다.\n"
             "- 가운뎃점(·)은 쓰지 않고 쉼표나 '와/과'로 바꾼다. 특수기호(① → ㎝ ※ 등)·한자·이모지도 쓰지 않는다.")


def rule():
    lib = load()
    if not lib:
        return CHAR_RULE
    lines = [f"- {', '.join(e['terms'])} → {e['repl'] or '(일반적인 말로 바꿈)'}" for e in lib]
    return CHAR_RULE + ("\n\n[기재 유의어 — 생기부에 쓰지 않는 말, 항상 지킴]\n"
            "- 아래 왼쪽 말(상표·서비스·기관 이름 등)은 결과에 쓰지 않고 오른쪽 대체 표현으로 바꿔 쓴다. 자료에 그 말이 있어도 대체 표현으로 쓴다.\n"
            + "\n".join(lines))


def from_xlsx(path):
    """열: 기재 유의어 / 한글·다른 표기 / 대체 표현 / (제외할 말). 머리글 줄('유의어'·'대체' 글이 든 줄) 위는 건너뛴다."""
    import openpyxl
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception:
        raise DbError("엑셀 파일을 열지 못했습니다. xlsx 파일인지 확인해 주세요.")
    try:
        rows = [[("" if c is None else str(c).strip()) for c in r] for r in wb.worksheets[0].iter_rows(values_only=True)]
    finally:
        wb.close()
    rows = [r + [""] * (4 - len(r)) for r in rows if any(r)]
    head = next((i for i, r in enumerate(rows) if any("유의어" in c for c in r) and any("대체" in c for c in r)), None)
    if head is not None:
        h = rows[head]
        col = lambda key, d: next((i for i, c in enumerate(h) if key in c), d)
        cw, co, cr, ce = col("유의어", 0), col("표기", 1), col("대체", 2), col("제외", None)
        body = rows[head + 1:]
    else:
        cw, co, cr, ce, body = 0, 1, 2, 3, rows
    lib = []
    for r in body:
        terms = _split([r[cw]] + _split(r[co]))
        if terms:
            lib.append({"terms": terms, "repl": r[cr] if cr < len(r) else "", "except": _split(r[ce]) if ce is not None and ce < len(r) else []})
    lib = normalize(lib)
    if not lib:
        raise DbError("엑셀에서 기재 유의어를 찾지 못했습니다.")
    return lib


def to_xlsx(lib, path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "기재 유의어"
    ws.append(["기재 유의어", "한글·다른 표기", "대체 표현", "제외할 말"])
    for e in lib:
        ws.append([e["terms"][0], ", ".join(e["terms"][1:]), e["repl"], ", ".join(e["except"])])
    for c, w in zip("ABCD", (22, 26, 36, 20)):
        ws.column_dimensions[c].width = w
    wb.save(path)
