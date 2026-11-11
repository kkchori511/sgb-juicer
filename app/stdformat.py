"""성취기준 붙여넣기 정리: 원문 글자는 한 글자도 바꾸지 않고, 줄의 역할만 판단해 보기 좋게 다시 배치한다.

- 규칙으로 먼저 판단한다(단원 '1) …', 성취기준 '[코드] …', 수준 표시 'A'~'E', 표 머리글).
- 규칙으로 판단이 안 되는 줄만 AI에 '역할'을 묻는다. AI는 글을 쓰지 않고 줄 번호별 역할만 돌려준다.
- 결과는 원문 줄을 그대로 가져다 만든다. 끝에 원문 내용 줄이 순서대로 모두 들어 있는지 검사한다.
- 빈 수준이 B·D뿐이면 그 성취기준은 3단계(A·C·E)로 표시한다.
"""
import json
import re

ROLES = ("unit", "standard", "label", "text", "header")
# AI 답은 줄을 지우지 못한다: AI가 머리글이라고 한 줄은 'keep'(그대로 남김)으로 바꾸고 교사에게 알린다.
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


def apply_ai(lines, roles, answer):
    """AI 답(JSON)을 unknown 줄에만 반영한다. → (새 역할, AI 머리글 판단 줄, 확인 필요 줄)
    - AI는 줄을 지울 수 없다: 'header'라고 해도 'keep'으로 남긴다.
    - 줄 모양과 맞지 않는 답(A~E가 아닌 줄을 label로, '[' 없는 줄을 standard로)이나 빠진 답은 'keep'(확인 필요)."""
    m = re.search(r"\{.*\}", answer or "", re.S)
    data = {}
    if m:
        try:
            data = json.loads(m.group(0))
        except ValueError:
            data = {}
    out, ai_headers, check = list(roles), [], []
    for i, r in enumerate(roles):
        if r != "unknown":
            continue
        v = str(data.get(str(i), "")).strip().lower()
        ln = lines[i]
        if v == "header":
            out[i] = "keep"
            ai_headers.append(i)
        elif v == "text" or (v == "unit" and len(ln.strip()) <= 60):
            out[i] = v
        elif v == "label" and LABEL_RE.match(ln):
            out[i] = "label"
        elif v == "standard" and STD_RE.match(ln):
            out[i] = "standard"
        else:
            out[i] = "keep"
            check.append(i)
    return out, ai_headers, check


def build(lines, roles):
    """역할대로 원문 줄을 다시 배치한다. → (정리한 글, 3단계 성취기준 코드, 뺀 머리글 줄 번호, 남은 unknown 수)"""
    out, three, headers = [], [], []
    cur = None  # 지금 성취기준: {"line": 원문, "levels": {A: [줄들]}, "order": [A..]}
    unknown = 0

    def flush():
        if not cur:
            return
        lv = cur["levels"]
        has = [k for k in cur["order"] if lv[k]]
        # 비어 있거나 아예 없는 수준(있는 수준 사이의 빈 곳만): B·D뿐이면 3단계
        if has:
            span = "ABCDE"[: "ABCDE".index(max(has)) + 1]
            empty = [k for k in span if k >= min(has) and not lv.get(k)]
        else:
            empty = []
        note = ""
        if empty and set(empty) == {"B", "D"} and set(has) == {"A", "C", "E"}:
            note = " (3단계: A·C·E)"
            code = re.match(r"^\s*(\[[^\]]+\])", cur["line"])
            three.append(code.group(1) if code else cur["line"][:20])
        out.append(cur["line"].strip() + note)
        shown = cur["order"] + sorted(k for k in ([] if note else empty) if k not in cur["order"])
        if not note:
            shown = sorted(shown, key="ABCDE".index)
        for k in shown:
            if lv.get(k):
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
        elif r == "keep":  # AI가 머리글이라 했거나 확인이 필요한 줄: 지우지 않고 그 자리에 둔다
            if cur is not None:
                cur["extra"].append(ln)
            else:
                out.append(ln.strip())
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
    """원문 내용 줄이 결과에 순서대로 그대로 들어 있는지. 공백만 다른 것은 같다고 본다.
    AI 판단과 상관없이 원문만 보고 정한다: 빈 줄, 규칙으로 정한 표 머리글(HEADERS), A~E 기호만 있는 줄만 뺀다.
    → 빠진 줄 번호 목록(비면 통과)"""
    hay = _norm(result)
    pos, missing = 0, []
    for i, ln in enumerate(lines):
        st = ln.strip()
        if not st or _norm(st) in HEADERS or LABEL_RE.match(st):
            continue
        m = INLINE_RE.match(ln)
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


# ---------- 수식 빈칸 채우기(AI) ----------
# 원문 글자는 그대로 두고, 수식이 빠져 비어 보이는 곳만 말로 채우거나 앞뒤를 잇는다(덧붙이기만).

def gap_lines(text):
    """수식이 빠진 듯한 줄(번호, 줄)."""
    return [(i, ln) for i, ln in enumerate((text or "").replace("\r", "").split("\n")) if ln.strip() and GAP_RE.search(ln)]


def fill_prompt():
    return ("너는 교육과정 성취기준 문서에서 복사할 때 수식이 빠져 비어 보이는 곳을 고친다.\n"
            "입력은 '번호<TAB>줄' 목록이다. 줄마다 수식이 있던 자리(두 칸 이상 빈 곳, 홀로 남은 조사 등)를 찾아\n"
            "수식을 쓰지 말고 짧은 말(예: '다항식', '이차함수의 그래프', '두 점 사이의 거리')로 채우거나, 앞뒤가 자연스럽게 이어지게 낱말을 덧붙인다.\n"
            "- 원문 글자는 하나도 지우거나 바꾸지 않는다. 덧붙이기만 한다(빈칸 공백은 줄여도 된다).\n"
            "- 확실하지 않으면 그 줄은 원문 그대로 둔다. 수식·기호(x, y, ², √ 등)는 쓰지 않는다.\n"
            "반드시 JSON 객체 하나만 출력한다. 예: {\"3\":\"고친 줄\",\"7\":\"고친 줄\"}")


def fill_user(gl):
    return "\n".join(f"{i}\t{ln.strip()}" for i, ln in gl)


def only_added(before, after):
    """after가 before의 글자를 순서대로 모두 담고 있는지(공백 제외) = 덧붙이기만 했는지."""
    a = re.sub(r"\s+", "", before or "")
    b = re.sub(r"\s+", "", after or "")
    j = 0
    for ch in b:
        if j < len(a) and ch == a[j]:
            j += 1
    return j == len(a) and len(b) >= len(a)


def apply_fill(text, gl, answer):
    """AI 답을 반영한 새 글과 바뀐 줄 목록. 원문을 지우거나 바꾼 줄은 쓰지 않는다(rejected)."""
    import json
    m = re.search(r"\{.*\}", answer or "", re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
    except ValueError:
        data = {}
    lines = (text or "").replace("\r", "").split("\n")
    changed, rejected = [], []
    for i, ln in gl:
        new = data.get(str(i))
        if not isinstance(new, str) or not new.strip() or new.strip() == ln.strip():
            continue
        lead = ln[: len(ln) - len(ln.lstrip())]
        if only_added(ln, new):
            lines[i] = lead + new.strip()
            changed.append({"line": i, "before": ln.strip(), "after": new.strip()})
        else:
            rejected.append({"line": i, "before": ln.strip(), "after": new.strip()})
    return "\n".join(lines), changed, rejected
