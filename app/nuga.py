"""나이스 '행동특성 누가기록' 내려받기 파일(v0.23).
인쇄용 쪽을 세로로 이어 붙인 모양이다: 쪽마다 머리글(번호·성명·일자·행동특성내용)과 쪽 번호(n / m)가 있고,
번호·성명은 그 쪽 안에서 학생 줄 수만큼 세로 병합, 내용은 E:R 가로 병합(값은 첫 칸).
학생이 다음 쪽으로 넘어가면 새 쪽 첫 줄에 번호가 다시 나오고, 쪽에서 잘린 글은 다음 쪽 첫 줄에 일자 없이 이어진다.
→ 학년·반·번호·성명·일자·누가기록 표로 바꾼다(한 줄 = 기록 한 건).

민감 정보(입력 받을 때부터): 분류 낱말로 상담·가정·건강·징계·출결·성적 점수 기록을 찾아 제외하고,
명렬 이름은 '○○'으로 가리며, 성을 뺀 이름·전화번호·주민번호처럼 보이는 글은 경고만 한다. AI는 쓰지 않는다."""
import re

HEAD = ("번호", "성명", "일자", "행동특성내용")
OUT_HEAD = ["학년", "반", "번호", "성명", "일자", "누가기록"]
ROLES = {"0": "grade", "1": "class_no", "2": "number", "3": "name", "4": "date", "5": "content"}
_DATE = re.compile(r"^\s*(\d{4})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})\s*\.?\s*$")
_CLS = re.compile(r"(\d+)\s*학년\s*(\d+)\s*반")


def read_xlsx(path, sheet=None):
    """칸 값을 다듬지 않고 읽는다(쪽에서 잘린 글을 이을 때 끝 공백이 필요)."""
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet else wb.worksheets[0]
        return [["" if v is None else (str(int(v)) if isinstance(v, float) and v.is_integer() else str(v)) for v in r] for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def _head_cols(row):
    cells = [str(c or "").strip() for c in row]
    if all(h in cells for h in HEAD):
        return {h: cells.index(h) for h in HEAD}
    return None


def is_nuga(rows) -> bool:
    return any(_head_cols(r) for r in rows or [])


def convert(rows, grade=None, class_no=None):
    """→ (표[머리글 포함], 안내). 학년·반은 '…1학년 4반' 칸에서 읽고, 없으면 grade·class_no(담당)를 쓴다."""
    cols = None
    for r in rows:
        cols = _head_cols(r)
        if cols:
            break
    if not cols:
        raise ValueError("행동특성 누가기록 모양이 아닙니다.")
    for r in rows:
        for c in r:
            m = _CLS.search(str(c or ""))
            if m:
                grade, class_no = int(m.group(1)), int(m.group(2))
                break
        else:
            continue
        break
    get = lambda r, h: (r[cols[h]] if cols[h] < len(r) and r[cols[h]] is not None else "")
    ents, cur_no, cur_name = [], "", ""
    joined = empty_rows = 0
    for r in rows:
        if _head_cols(r):
            continue
        no, name, date, text = str(get(r, "번호")).strip(), str(get(r, "성명")).strip(), str(get(r, "일자")).strip(), str(get(r, "행동특성내용"))
        if no:
            if not no.isdigit():  # 제목·조회 기간 같은 머리 줄
                continue
            if no != cur_no:
                cur_name = ""
            cur_no = no
        if name:
            cur_name = name
        if not cur_no:
            continue
        if _DATE.match(date):
            y, mo, d = _DATE.match(date).groups()
            ents.append({"no": cur_no, "name": cur_name, "date": f"{y}-{int(mo):02d}-{int(d):02d}", "text": text})
        elif text.strip() and ents and ents[-1]["no"] == cur_no:  # 쪽에서 잘린 글: 앞 기록에 그대로 잇는다
            ents[-1]["text"] += text
            joined += 1
    table = [list(OUT_HEAD)]
    for e in ents:
        t = re.sub(r"\s+", " ", e["text"]).strip()
        if not t:
            empty_rows += 1
            continue
        table.append([str(grade or ""), str(class_no or ""), e["no"], e["name"], e["date"], t])
    info = {"students": len({e["no"] for e in ents}), "entries": len(table) - 1, "joined": joined, "empty": empty_rows,
            "grade": grade, "class_no": class_no}
    return table, info


# ---------- 민감 정보 ----------
CATS = {
    "counsel": ("상담", r"상담"),
    "family": ("가정·건강", r"이혼|별거|재혼|한부모|조손|가정\s*폭력|학대|수급|차상위|생리|병원|입원|수술|진단|질환|깁스|골절|부상|우울|공황|불안\s*장애|ADHD|약을?\s*복용|망막|장애|정신과|심리\s*검사|자해|자살|극단적"),
    "discipline": ("징계·출결", r"지도\s*카드|생활\s*교육\s*위원회|생교위|선도\s*위원회|징계|학교\s*폭력|학폭|미인정|무단|결석|지각|조퇴|자퇴|벌점|흡연|음주|경찰(?!대)|출석\s*정지|처분"),
    "score": ("성적 점수", r"\d+\s*점(?!심)|\d\s*등급|등수|\d+\s*등(?![가-힣])|평균\s*\d"),
}
CAT_KEYS = tuple(CATS)
PHONE = re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}")
RRN = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")


def categories(text):
    """걸린 분류 키 목록."""
    return [k for k, (_, rx) in CATS.items() if re.search(rx, text or "")]


def mask_names(text, names):
    """명렬 이름(성 포함, 2글자 이상)을 '○○'으로. → (글, 가린 수)"""
    n = 0
    for nm in sorted({x for x in names if x and len(x) >= 2}, key=len, reverse=True):
        if nm in text:
            n += text.count(nm)
            text = text.replace(nm, "○○")
    return text, n


def warnings(text, names):
    """성을 뺀 두 글자 이름(3글자 이름의 끝 두 글자), 전화번호·주민번호처럼 보이는 글."""
    out = []
    given = sorted({x[1:] for x in names if x and len(x) == 3})
    hit = [g for g in given if re.search(rf"(?<![가-힣]){g}(?:[이가은는을를의와과도]|이가|이는|이를|이랑|랑|\s|$|[.,])", text)]
    if hit:
        out.append("이름처럼 보이는 글: " + ", ".join(hit[:3]))
    if PHONE.search(text):
        out.append("전화번호처럼 보이는 글")
    if RRN.search(text):
        out.append("주민등록번호처럼 보이는 글")
    return out
