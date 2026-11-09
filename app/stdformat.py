"""성취기준 붙여넣기 정리: 원문 글자는 한 글자도 바꾸지 않고, 줄의 역할만 판단해 보기 좋게 다시 배치한다.

- 규칙으로 먼저 판단한다(단원 '1) …', 성취기준 '[코드] …', 수준 표시 'A'~'E', 표 머리글).
- 규칙으로 판단이 안 되는 줄만 AI에 '역할'을 묻는다. AI는 글을 쓰지 않고 줄 번호별 역할만 돌려준다.
- 결과는 원문 줄을 그대로 가져다 만든다. 끝에 원문 내용 줄이 순서대로 모두 들어 있는지 검사한다.
- 빈 수준이 B·D뿐이면 그 성취기준은 3단계(A·C·E)로 표시한다.
"""
import json
import re

ROLES = ("unit", "standard", "label", "text", "header")
UNIT_RE = re.compile(r"^\s*(?:\d{1,2}\s*[).]|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\s*[.)]?|\(\d{1,2}\))\s*\S")
STD_RE = re.compile(r"^\s*\[[^\]\s]{3,}\]")
LABEL_RE = re.compile(r"^\s*([A-E])\s*$")
INLINE_RE = re.compile(r"^\s*([A-E])\s*[:：.)]\s*(\S.*)$")
HEADERS = {"성취기준", "성취기준별성취수준", "성취수준", "성취기준별성취수준진술", "성취기준성취기준별성취수준", "영역", "단원", "수준"}
# 복사하다 수식이 빠진 듯한 곳: 두 칸 이상 빈칸, 조사·'꼴'·'축' 앞의 빈 자리
GAP_RE = re.compile(r"\S {2,}\S|^\s+(꼴|의|에)\s|\s(꼴|의|에)\s|(^|[\s,])축(,|\s|$)")


def _norm(s):
    return re.sub(r"\s", "", s or "")


def split_lines(text):
    return [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")]


def classify(lines):
    """줄마다 역할(빈 줄은 None). 규칙으로 정하지 못한 줄은 'unknown'."""
    roles = []
    state = None  # 바로 앞의 의미 있는 역할
    for ln in lines:
        s = ln.strip()
        if not s:
            roles.append(None)
            continue
        if _norm(s) in HEADERS:
            r = "header"
        elif STD_RE.match(s):
            r = "standard"
        elif LABEL_RE.match(s):
            r = "label"
        elif INLINE_RE.match(s):
            r = "inline"
        elif UNIT_RE.match(s) and len(s) <= 40:
            r = "unit"
        elif state in ("label", "text", "inline"):
            r = "text"
        else:
            r = "unknown"
        roles.append(r)
        if r != "header":
            state = r
    return roles


def ai_prompt():
    return ("너는 교육과정 성취기준 문서의 줄 역할을 분류한다. 글을 고치거나 새로 쓰지 않는다.\n"
            "입력은 '번호<TAB>원문 줄' 목록이다. '?' 표시 줄의 역할만 정한다. 앞뒤 줄은 참고용이다.\n"
            "역할: unit(단원·영역 제목), standard(성취기준 문장), label(수준 기호 A~E만 있는 줄), "
            "text(바로 앞 수준 기호의 설명 문장 또는 앞 문장의 이어지는 부분), header(표 머리글 같은 내용 없는 줄).\n"
            "반드시 JSON 객체 하나만 출력한다. 예: {\"12\":\"text\",\"30\":\"header\"}")


def ai_user(lines, roles):
    out = []
    for i, (ln, r) in enumerate(zip(lines, roles)):
        if r is None:
            continue
        out.append(f"{i}\t{'?' if r == 'unknown' else r}\t{ln.strip()}")
    return "\n".join(out)


def apply_ai(roles, answer):
    """AI 답(JSON)을 unknown 줄에만 반영한다. 모르는 값은 text로."""
    m = re.search(r"\{.*\}", answer or "", re.S)
    data = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = {}
    out = list(roles)
    for i, r in enumerate(roles):
        if r == "unknown":
            v = str(data.get(str(i), "")).strip().lower()
            out[i] = v if v in ROLES else "text"
    return out


def build(lines, roles):
    """역할대로 원문 줄을 다시 배치한다. → (정리한 글, 3단계 성취기준 코드, 뺀 머리글 줄 번호, 남은 unknown 수)"""
    out, three, headers = [], [], []
    cur = None  # 지금 성취기준: {"line": 원문, "levels": {A: [줄들]}, "order": [A..]}
    unknown = 0

    def flush():
        if not cur:
            return
        lv = cur["levels"]
        empty = [k for k in cur["order"] if not lv[k]]
        has = [k for k in cur["order"] if lv[k]]
        note = ""
        if empty and set(empty) == {"B", "D"} and set(has) == {"A", "C", "E"}:
            note = " (3단계: A·C·E)"
            code = re.match(r"^\s*(\[[^\]]+\])", cur["line"])
            three.append(code.group(1) if code else cur["line"][:20])
        out.append(cur["line"].strip() + note)
        for k in cur["order"]:
            if lv[k]:
                out.append(f"  {k}: " + " ".join(x.strip() for x in lv[k]))
            elif not note:
                out.append(f"  {k}: (원문에 내용 없음)")
        for t in cur["extra"]:
            out.append("  " + t.strip())

    last_label = None
    for i, (ln, r) in enumerate(zip(lines, roles)):
        if r is None:
            continue
        if r == "header":
            headers.append(i)
            continue
        if r == "unit":
            flush()
            cur, last_label = None, None
            if out:
                out.append("")
            out.append(ln.strip())
        elif r == "standard":
            flush()
            cur, last_label = {"line": ln, "levels": {}, "order": [], "extra": []}, None
        elif r in ("label", "inline"):
            m = LABEL_RE.match(ln) or INLINE_RE.match(ln)
            k = m.group(1)
            if cur is None:
                cur = {"line": "", "levels": {}, "order": [], "extra": []}
            if k not in cur["levels"]:
                cur["levels"][k] = []
                cur["order"].append(k)
            if r == "inline":
                cur["levels"][k].append(m.group(2))
            last_label = k
        else:  # text 또는 남은 unknown
            if r == "unknown":
                unknown += 1
            if cur is not None and last_label:
                cur["levels"][last_label].append(ln)
            elif cur is not None and not cur["order"]:
                cur["line"] = cur["line"].rstrip() + " " + ln.strip()  # 성취기준 문장이 다음 줄로 이어짐
            elif cur is not None:
                cur["extra"].append(ln)
            else:
                out.append(ln.strip())
    flush()
    return "\n".join(out).strip() + "\n", three, headers, unknown


def verify(lines, roles, result):
    """원문 내용 줄(머리글 제외)이 결과에 순서대로 그대로 들어 있는지. 공백만 다른 것은 같다고 본다.
    → 빠진 줄 번호 목록(비면 통과)"""
    hay = _norm(result)
    pos, missing = 0, []
    for i, (ln, r) in enumerate(zip(lines, roles)):
        if r in (None, "header", "label"):  # 수준 기호 줄은 구조로 다시 쓰므로(빈 B·D는 3단계로 뺌) 내용 줄만 본다
            continue
        m = INLINE_RE.match(ln) if r == "inline" else None
        s = _norm(m.group(2) if m else ln)
        j = hay.find(s, pos)
        if j < 0:
            missing.append(i)
        else:
            pos = j + len(s)
    return missing


def gaps(lines, roles):
    """수식이 빠진 듯한 줄(번호, 원문)."""
    return [(i, ln.strip()) for i, (ln, r) in enumerate(zip(lines, roles)) if r not in (None, "header") and GAP_RE.search(ln)]
