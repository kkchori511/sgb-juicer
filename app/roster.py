"""명렬 붙여넣기·xlsx 읽기, 열 자동 연결, 행 검사."""
import csv
import io
import re

HANGUL_NAME = re.compile(r"^[가-힣]{2,5}$")
LEVELS = {3: "ABC", 5: "ABCDE"}

# 머리글 이름 → 열 역할
HEADER_HINTS = {
    "student_no": ("학번",),
    "name": ("이름", "성명", "학생명", "성 명"),
    "grade": ("학년",),
    "class_no": ("반",),
    "number": ("번호", "번"),
    "level": ("성취수준", "성취도", "수준", "등급"),
}
ROLES = ("student_no", "name", "grade", "class_no", "number", "level")


def parse_text(text: str) -> list[list[str]]:
    """엑셀에서 복사한 글(탭 구분). 셀 안 줄바꿈은 따옴표로 감싸져 온다."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    if not text.strip():
        return []
    delim = "\t" if "\t" in text else ","
    if delim == "," and not re.search(r",", text):
        # 한 열짜리(또는 공백 구분) 붙여넣기
        rows = [re.split(r"\s+", line.strip()) for line in text.split("\n")]
    else:
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    return _clean(rows)


def parse_xlsx(path: str) -> list[list[str]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append([_cell(v) for v in r])
        return _clean(rows)
    finally:
        wb.close()


def _cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _clean(rows):
    rows = [[(c or "").strip() for c in r] for r in rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    # 모든 행이 비어 있는 열은 뺀다
    keep = [i for i in range(width) if any(r[i] for r in rows)]
    return [[r[i] for i in keep] for r in rows]


def _header_role(cell: str):
    c = cell.replace(" ", "")
    for role, hints in HEADER_HINTS.items():
        for h in hints:
            if c == h.replace(" ", ""):
                return role
    return None


def detect(rows: list[list[str]]) -> dict:
    """{'header': bool, 'columns': {role: index or None}}"""
    if not rows:
        return {"header": False, "columns": {r: None for r in ROLES}}
    cols = {r: None for r in ROLES}
    header = False
    for i, cell in enumerate(rows[0]):
        role = _header_role(cell)
        if role and cols[role] is None:
            cols[role] = i
            header = True
    body = rows[1:] if header else rows
    width = len(rows[0])

    def ratio(i, test):
        vals = [r[i] for r in body if i < len(r) and r[i]]
        return (sum(1 for v in vals if test(v)) / len(vals)) if vals else 0

    used = {v for v in cols.values() if v is not None}
    if cols["student_no"] is None:
        for i in range(width):
            if i not in used and ratio(i, lambda v: re.fullmatch(r"\d{4,6}", v) is not None) >= 0.8:
                cols["student_no"] = i
                used.add(i)
                break
    if cols["name"] is None:
        for i in range(width):
            if i not in used and ratio(i, lambda v: HANGUL_NAME.match(v) is not None) >= 0.8:
                cols["name"] = i
                used.add(i)
                break
    if cols["level"] is None:
        for i in range(width):
            if i not in used and ratio(i, lambda v: re.fullmatch(r"[A-Za-z]", v) is not None) >= 0.8:
                cols["level"] = i
                used.add(i)
                break
    return {"header": header, "columns": cols}


def split_student_no(no: str):
    """5자리 학번 → (학년, 반, 번호). 형식이 다르면 None."""
    m = re.fullmatch(r"(\d)(\d{2})(\d{2})", no or "")
    if not m:
        return None
    g, c, n = (int(x) for x in m.groups())
    if g == 0 or c == 0 or n == 0:
        return None
    return g, c, n


def build_rows(rows, header, columns) -> list[dict]:
    """열 연결대로 학생 행을 만든다. 학번이 없고 학년·반·번호가 있으면 학번을 만든다."""
    body = rows[1:] if header else rows
    out = []
    for i, r in enumerate(body):
        def get(role):
            idx = columns.get(role)
            if idx is None or idx == "" or int(idx) >= len(r):
                return ""
            return r[int(idx)].strip()

        no = re.sub(r"\s", "", get("student_no"))
        grade, class_no, number = get("grade"), get("class_no"), get("number")
        if not no and grade.isdigit() and class_no.isdigit() and number.isdigit():
            no = f"{int(grade)}{int(class_no):02d}{int(number):02d}"
        parts = split_student_no(no) if no else None
        if parts:
            grade = grade or str(parts[0])
            class_no = class_no or str(parts[1])
            number = number or str(parts[2])
        out.append({
            "row": i + 1,
            "student_no": no,
            "name": re.sub(r"\s", "", get("name")),
            "grade": _digits(grade),
            "class_no": _digits(class_no),
            "number": _digits(number),
            "level": get("level").upper(),
        })
    return out


def _digits(v):
    v = re.sub(r"[^\d]", "", str(v or ""))
    return str(int(v)) if v else ""


def validate(rows: list[dict], group: dict, known: dict) -> list[dict]:
    """행마다 issues(막는 문제)와 notes(알림)를 붙인다.
    known: {학번: 이미 저장된 이름}"""
    counts = {}
    for r in rows:
        if r["student_no"]:
            counts[r["student_no"]] = counts.get(r["student_no"], 0) + 1
    scale = group.get("level_scale") or 5
    for r in rows:
        issues, notes = [], []
        no, name = r["student_no"], r["name"]
        if not no:
            issues.append("학번 없음")
        elif not no.isdigit():
            issues.append("학번은 숫자만")
        elif counts.get(no, 0) > 1:
            issues.append("학번 중복")
        if not name:
            issues.append("이름 없음")
        if not r["grade"] or not r["class_no"]:
            issues.append("학년·반 입력 필요")
        if no and name and known.get(no) and known[no] != name:
            notes.append(f"기존 이름 {known[no]} → {name}")
        if group["kind"] == "homeroom" and r["grade"] and r["class_no"]:
            if (int(r["grade"]), int(r["class_no"])) != (group["grade"], group["class_no"]):
                issues.append(f"다른 반({r['grade']}-{r['class_no']})")
        if group["kind"] == "subject" and r["level"] and r["level"] not in LEVELS[scale]:
            notes.append(f"{scale}단계 범위 밖 수준")
        if group["kind"] in ("homeroom", "club") and r["grade"] == "3":
            notes.append("3학년: 1학기 마감 대상")
        r["issues"], r["notes"] = issues, notes
    # 과목: 학년이 섞이면 알림
    if group["kind"] == "subject":
        grades = {r["grade"] for r in rows if r["grade"]}
        if len(grades) > 1:
            for r in rows:
                r["notes"].append("과목 명렬에 여러 학년이 섞여 있음")
    return rows
