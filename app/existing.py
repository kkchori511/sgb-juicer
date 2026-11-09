"""이미 쓴 생기부 일괄 넣기: 파일마다 다른 형식을 읽고, 이름을 기준으로 학생과 연결한다.

- NEIS 공식 업로드 파일: 학년도, 학기, 학생개인번호, 과목, 과목코드, 반/번호, 성명, 학적변동 구분, 내용
- 꼭 필요한 칸은 이름과 내용. 학번·학년·반·번호·반/번호는 있으면 확인용으로 쓴다.
- 반/번호: '1/1', '1반 1번'은 반·번호. '1-1'은 머리글이 없으면 반-번호와 학년-반 둘 다 명렬과 맞춰 본다.
"""
import re

from .inbox import lev

HANGUL_NAME = re.compile(r"^[가-힣]{2,5}$")

# 머리글(공백·괄호 무시) → 역할. ignore는 쓰지 않는 열(학생개인번호를 학번으로 오해하지 않게).
HINTS = {
    "ignore": ("학년도", "학기", "학생개인번호", "개인번호", "과목", "과목코드", "과목명", "교과", "구분"),
    "student_no": ("학번",),
    "name": ("성명", "이름", "학생명", "학생이름"),
    "grade": ("학년",),
    "class_no": ("반",),
    "number": ("번호", "번"),
    "clsnum": ("반/번호", "반번호", "반-번호", "반·번호"),
    "gradecls": ("학년-반", "학년/반", "학년반"),
    "change": ("학적변동구분", "학적변동"),
    "title": ("활동명", "활동", "제목", "주제", "활동주제"),
    "date": ("날짜", "일자", "활동일", "활동일자", "일시"),
    "content": ("내용", "세부능력및특기사항", "세특", "특기사항", "행동특성및종합의견", "종합의견", "활동내용", "기록"),
}
# clsany: 머리글 없이 모양으로 찾은 반/번호 칸(뜻이 정해지지 않음 — '1-1'은 두 가지로 맞춰 본다)
ROLES = ("student_no", "name", "grade", "class_no", "number", "clsnum", "gradecls", "clsany", "change", "title", "date", "content")


def _norm(h):
    return re.sub(r"[\s()\[\]]", "", h or "")


def header_role(cell):
    c = _norm(cell)
    if not c:
        return None
    for role in ("clsnum", "gradecls", "change", "ignore", "student_no", "name", "grade", "class_no", "number", "title", "date", "content"):
        if any(c == _norm(h) for h in HINTS[role]):
            return role
    if len(c) <= 12 and ("내용" in c or "특기사항" in c or "의견" in c):  # 짧은 머리글만(본문 글에 '내용'이 들어간 경우 제외)
        return "content"
    return None


CLS_RE = re.compile(r"^\s*(\d{1,2})\s*(?:반)?\s*[/\-.·]\s*(\d{1,2})\s*(?:번)?\s*$|^\s*(\d{1,2})\s*반\s*(\d{1,2})\s*번\s*$")
TRIPLE_RE = re.compile(r"^\s*(\d)\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*$")


def detect(raw):
    """{'header': bool, 'columns': {role: index|None}}"""
    cols = {r: None for r in ROLES}
    if not raw:
        return {"header": False, "columns": cols}
    header = False
    for i, cell in enumerate(raw[0]):
        role = header_role(cell)
        if role:
            header = True
            if role != "ignore" and cols[role] is None:
                cols[role] = i
    body = raw[1:] if header else raw
    width = len(raw[0])
    ignored = {i for i, cell in enumerate(raw[0]) if header and header_role(cell) == "ignore"}
    used = {v for v in cols.values() if v is not None} | ignored

    def ratio(i, test):
        vals = [r[i] for r in body if i < len(r) and r[i].strip()]
        return (sum(1 for v in vals if test(v)) / len(vals)) if vals else 0

    def pick(role, test, need=0.8):
        if cols[role] is None:
            for i in range(width):
                if i not in used and ratio(i, test) >= need:
                    cols[role] = i
                    used.add(i)
                    return

    # 날짜 칸은 머리글이 있어도 기본으로 쓰지 않는다(누가기록 날짜는 선택 사항). 화면에서 고르면 쓴다.
    cols["date"] = None
    pick("student_no", lambda v: re.fullmatch(r"\d{5}", v.strip()) is not None)
    if cols["clsnum"] is None and cols["gradecls"] is None:
        pick("clsany", lambda v: CLS_RE.match(v) is not None or TRIPLE_RE.match(v) is not None)
    pick("name", lambda v: HANGUL_NAME.match(v.strip()) is not None)
    if cols["content"] is None:
        cands = [i for i in range(width) if i not in used]
        if cands:
            cols["content"] = max(cands, key=lambda i: sum(len(r[i]) for r in body if i < len(r)))
    return {"header": header, "columns": cols}


def class_options(value, kind):
    """반/번호 칸 값 → 가능한 해석 [(학년|None, 반|None, 번호|None)].
    kind: clsnum(반/번호 머리글) / gradecls(학년-반 머리글) / None(모름)"""
    v = (value or "").strip()
    if not v:
        return []
    m = TRIPLE_RE.match(v)
    if m:
        return [tuple(int(x) for x in m.groups())]
    m = CLS_RE.match(v)
    if not m:
        return []
    a, b = (int(x) for x in (m.group(1) or m.group(3), m.group(2) or m.group(4)))
    if "/" in v or "반" in v or kind == "clsnum":
        return [(None, a, b)]
    if kind == "gradecls":
        return [(a, b, None)]
    return [(None, a, b), (a, b, None)]  # '1-1': 반-번호일 수도, 학년-반일 수도


def _fits(m, opt):
    g, c, n = opt
    return (g is None or m["grade"] == g) and (c is None or m["class_no"] == c) and (n is None or m["number"] == n)


def match_row(ext, members):
    """ext: {student_no, name, grade, class_no, number, class_opts}
    → (student_no|None, state confirmed/suggested/none, note)"""
    by_no = {m["student_no"]: m for m in members}
    active = [m for m in members if m["active"]]
    name = ext.get("name", "")
    opts = list(ext.get("class_opts") or [])
    if ext.get("class_no") or ext.get("number") or ext.get("grade"):
        opts.append((ext.get("grade"), ext.get("class_no"), ext.get("number")))
    fits_any = lambda m: any(_fits(m, o) for o in opts)
    no = ext.get("student_no", "")
    if no and no in by_no:
        m = by_no[no]
        if name == m["name"]:
            return m["student_no"], "confirmed", ""
        if not name:
            return m["student_no"], "suggested", f"이름 없음 — 학번으로 추천({m['name']})"
    same = [m for m in active if name and m["name"] == name]
    if len(same) == 1:
        m = same[0]
        if not opts or fits_any(m):
            return m["student_no"], "confirmed", ""
        return m["student_no"], "suggested", f"이름은 같지만 반·번호가 다름(명렬 {m['grade']}-{m['class_no']}-{m['number']})"
    if len(same) > 1:
        narrowed = [m for m in same if opts and fits_any(m)]
        if len(narrowed) == 1:
            return narrowed[0]["student_no"], "confirmed", ""
        return None, "none", f"동명이인 {len(same)}명 — 학생을 골라 주세요"
    # 이름이 명렬에 없음: 비슷한 이름, 또는 반·번호
    near = [m for m in active if len(name) >= 2 and lev(name, m["name"]) == 1]
    if len(near) == 1:
        return near[0]["student_no"], "suggested", f"비슷한 이름({near[0]['name']}) 추천"
    by_cls = [m for m in active if opts and any(o[2] is not None and _fits(m, o) for o in opts)]
    if len(by_cls) == 1:
        return by_cls[0]["student_no"], "suggested", f"반·번호로 추천(명렬 이름 {by_cls[0]['name']})"
    return None, "none", "명렬에서 찾지 못함" if name else "이름 없음"


DATE_RE = re.compile(r"^\s*(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")


def norm_date(v):
    """'2026.3.5', '2026-03-05 00:00:00', '2026년 3월 5일' → '2026-03-05'. 못 읽으면 ''."""
    m = DATE_RE.match(v or "")
    if not m:
        return ""
    y, mo, d = (int(x) for x in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return ""
    return f"{y:04d}-{mo:02d}-{d:02d}"


def build(raw, header, cols, members):
    body = raw[1:] if header else raw
    kind, cls_col = None, cols.get("clsany")
    for role in ("clsnum", "gradecls"):
        if cols.get(role) is not None and cols.get(role) != "":
            kind, cls_col = role, cols[role]
    out = []
    for i, r in enumerate(body):
        def get(role):
            idx = cols.get(role)
            if idx is None or idx == "" or int(idx) >= len(r):
                return ""
            return (r[int(idx)] or "").strip()

        def num(role):
            v = re.sub(r"[^\d]", "", get(role))
            return int(v) if v else None

        content = get("content")
        name = re.sub(r"\s", "", get("name"))
        if not content and not name:
            continue
        cls_val = (r[int(cls_col)].strip() if cls_col is not None and int(cls_col) < len(r) else "")
        ext = {"student_no": re.sub(r"\s", "", get("student_no")), "name": name, "grade": num("grade"),
               "class_no": num("class_no"), "number": num("number"), "class_opts": class_options(cls_val, kind)}
        sno, state, note = match_row(ext, members)
        out.append({"row": i + 1, "ext_no": ext["student_no"], "ext_name": name, "ext_cls": cls_val or "-".join(
            str(x) for x in (ext["grade"], ext["class_no"], ext["number"]) if x is not None),
            "change": get("change"), "title": get("title"), "date": norm_date(get("date")), "content": content, "student_no": sno, "state": state, "note": note})
    return out
