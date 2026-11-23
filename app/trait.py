"""행동특성 및 종합의견 설계 카드(v0.22).
설계 = 성격유형·성격 설명 + 영역(학업 역량·학업 태도·인성 및 학업 외 소양)마다 키워드(0~3개)·실제 사례(선택)·빼기.
기록 한 건(kind='trait', 학생마다 하나)으로 두고 records.design에 JSON, content에는 사람이 읽는 요약을 둔다."""
import json
import re

from .db import DbError
from .trait_dict import AREA_NAMES, AREAS

MAX_KW = 3
MAX_CASE = 3000


def _s(v, n):
    return str(v or "").strip()[:n]


def normalize(d):
    d = d if isinstance(d, dict) else {}
    out = {"type": _s(d.get("type"), 30), "desc": _s(d.get("desc"), 200), "areas": {}}
    src = d.get("areas") if isinstance(d.get("areas"), dict) else {}
    for a in AREAS:
        x = src.get(a) if isinstance(src.get(a), dict) else {}
        kws = []
        for k in (x.get("kws") or [])[:MAX_KW * 2]:
            k = " ".join(str(k or "").split())[:30]
            if k and k not in kws:
                kws.append(k)
        if len(kws) > MAX_KW:
            raise DbError(f"{AREA_NAMES[a]} 키워드는 3개까지 고를 수 있습니다.")
        out["areas"][a] = {"kws": kws, "case": _s(x.get("case"), MAX_CASE), "off": bool(x.get("off"))}
    return out


def parse(text):
    try:
        return normalize(json.loads(text)) if text else normalize({})
    except (ValueError, DbError):
        return normalize({})


def used_areas(d):
    """생성에 쓰는 영역: 빼지 않았고 키워드나 사례가 있는 것."""
    return [a for a in AREAS if not d["areas"][a]["off"] and (d["areas"][a]["kws"] or d["areas"][a]["case"])]


def is_empty(d):
    return not d["type"] and not d["desc"] and not used_areas(d)


def summary(d):
    """기록 content로 쓰는 읽기용 요약(태그별 기록·내보내기·대화 마법사 원문)."""
    lines = []
    if d["type"] or d["desc"]:
        lines.append(f"[성격] {d['type']}{' — ' if d['type'] and d['desc'] else ''}{d['desc']}")
    for a in used_areas(d):
        x = d["areas"][a]
        line = f"[{AREA_NAMES[a]}]"
        if x["kws"]:
            line += " 키워드: " + ", ".join(x["kws"])
        if x["case"]:
            line += ("\n" if x["kws"] else " ") + "사례: " + x["case"]
        lines.append(line)
    return "\n".join(lines)


def ai_user(d, dic, target=0):
    """AI에 보낼 글(학번·이름 없음): 성격 + 영역별 키워드·사례. 키워드 뜻은 학생 자료와 섞지 않고 맨 끝 '참고'로 따로 둔다."""
    if is_empty(d):
        raise DbError("성격유형이나 영역 키워드·사례를 하나 이상 넣어 주세요.")
    descs = {a: {e["kw"]: e["desc"] for e in dic["areas"][a]} for a in AREAS}
    out = ["<학생 자료 — 이 안에 적힌 것만 이 학생의 사실>"]
    if d["type"] or d["desc"]:
        out.append(f"[성격]\n- 성격유형: {d['type'] or '(없음)'}\n- 성격 설명(참고 — 그대로 옮기지 말고 키워드·사례에 맞게 바꿔 쓸 것): {d['desc'] or '(없음)'}")
    ref = []
    for a in used_areas(d):
        x = d["areas"][a]
        part = [f"[{AREA_NAMES[a]}]"]
        if x["kws"]:
            part.append("- 드러낼 키워드: " + ", ".join(x["kws"]))
            ref += [f"- {k}: {descs[a][k]}" for k in x["kws"] if descs[a].get(k)]
        part.append(f"- 실제 사례·기록: {x['case']}" if x["case"] else "- 실제 사례·기록: 없음 → 키워드가 뜻하는 성향·태도만 쓰고, 구체적 행동·활동·습관(언제·어디서·무엇을)은 쓰지 않음")
        out.append("\n".join(part))
    skipped = [AREA_NAMES[a] for a in AREAS if a not in used_areas(d)]
    if skipped:
        out.append("[쓰지 않는 영역] " + ", ".join(skipped))
    out.append("</학생 자료>")
    if ref:
        out.append("<키워드 뜻 참고 — 학생이 한 일이 아님>\n키워드가 무슨 뜻인지만 이해하는 데 쓰세요. 아래 문장 속 구체적 행동·장소·빈도(예: 청소, 봉사활동, 매일, 자투리 시간, 모둠 과제, 학급 임원)는 위 학생 자료의 사례에 없으면 결과에 쓰지 마세요.\n"
                   + "\n".join(ref) + "\n</키워드 뜻 참고>")
    if target:
        aim = round(target * 0.88)
        out.append(f"[분량] 약 {aim}바이트(공백 포함 한글 약 {round(aim / 3)}자)로 쓰고, {target}바이트는 절대 넘지 않게. 넘을 것 같으면 꾸밈 문구부터 줄이세요.")
    return "\n\n".join(out)


# ---------- 인적사항 점검(경고만, 저장은 막지 않음) ----------
PHONE = re.compile(r"01[016789][-\s.]?\d{3,4}[-\s.]?\d{4}")
STUNO = re.compile(r"(?<!\d)[1-3]\d{4}(?!\d)")
RRN = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")


def pii_warnings(d, names):
    """설계 글(성격 설명·사례)에서 인적사항처럼 보이는 것을 찾는다. names: 명렬의 이름들."""
    out = []
    texts = [("성격 설명", d["desc"])] + [(AREA_NAMES[a], d["areas"][a]["case"]) for a in AREAS]
    nm = sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True)
    for where, t in texts:
        if not t:
            continue
        hit = [n for n in nm if n in t][:3]
        if hit:
            out.append(f"{where}: 학생 이름처럼 보이는 글({', '.join(hit)})")
        if PHONE.search(t):
            out.append(f"{where}: 전화번호처럼 보이는 글")
        if RRN.search(t):
            out.append(f"{where}: 주민등록번호처럼 보이는 글")
        elif STUNO.search(t):
            out.append(f"{where}: 학번처럼 보이는 숫자")
    return out


# ---------- 설계 엑셀(여러 학생 한꺼번에) ----------
XHEAD = ["학번", "이름", "성격유형", "성격 설명",
         "학업 역량 사례", "학업 역량 키워드1", "학업 역량 키워드2", "학업 역량 키워드3",
         "학업 태도 사례", "학업 태도 키워드1", "학업 태도 키워드2", "학업 태도 키워드3",
         "인성 및 학업 외 소양 사례", "인성 키워드1", "인성 키워드2", "인성 키워드3"]


def template(path, members, designs, dic):
    """양식: 학번·이름이 채워진 표 + 드롭다운(성격유형·키워드) + 사전 시트. designs: {학번: 설계} 있으면 채워 둔다."""
    import os

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    wb = Workbook()
    ws = wb.active
    ws.title = "행특 설계"
    ws.append(XHEAD)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E8EEF8")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    for m in members:
        d = designs.get(m["student_no"])
        row = [m["student_no"], m["name"]]
        if d:
            row += [d["type"], d["desc"]]
            for a in AREAS:
                x = d["areas"][a]
                row += [x["case"]] + (x["kws"] + ["", "", ""])[:3]
        ws.append([v if v != "" else None for v in row])
    n = max(ws.max_row, 2)
    ref = wb.create_sheet("사전")
    ref.append(["성격유형", "성격 설명", "학업 역량 키워드", "학업 태도 키워드", "인성 키워드"])
    tnames = [t["name"] for t in dic["types"]]
    alld = [x for t in dic["types"] for x in t["descs"]]
    cols = [tnames, alld] + [[e["kw"] for e in dic["areas"][a]] for a in AREAS]
    for i in range(max(len(c) for c in cols)):
        ref.append([c[i] if i < len(c) else None for c in cols])
    for col, w in zip("ABCDE", (14, 44, 18, 18, 18)):
        ref.column_dimensions[col].width = w

    def dv(col_letter, length, cells):
        if not length:
            return
        v = DataValidation(type="list", formula1=f"=사전!${col_letter}$2:${col_letter}${length + 1}", allow_blank=True, showErrorMessage=False)
        v.add(cells)
        ws.add_data_validation(v)
    dv("A", len(tnames), f"C2:C{n}")
    dv("B", len(alld), f"D2:D{n}")
    dv("C", len(cols[2]), f"F2:H{n}")
    dv("D", len(cols[3]), f"J2:L{n}")
    dv("E", len(cols[4]), f"N2:P{n}")
    for col, w in zip("ABCDEFGHIJKLMNOP", (9, 9, 12, 32, 40, 13, 13, 13, 40, 13, 13, 13, 40, 13, 13, 13)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "C2"
    g = wb.create_sheet("안내", 0)
    for line in ("행특 설계 일괄 입력 — '행특 설계' 시트를 채워 [엑셀로 설계 입력]으로 올립니다.",
                 "· 학번(또는 이름)으로 학생을 찾습니다. 학번·이름 열은 고치지 마세요.",
                 "· 성격유형·키워드는 드롭다운(사전 시트)에서 고르거나 직접 씁니다. 영역마다 키워드는 3개까지.",
                 "· 사례는 선택입니다. 키워드도 사례도 없는 영역은 생성에서 빠집니다.",
                 "· ⚠ 사례에 학생 이름·학번·연락처 등 인적사항을 넣지 마세요(AI에 그대로 보내집니다).",
                 "· 비워 둔 줄(학번·이름만 있는 줄)은 건너뜁니다."):
        g.append([line])
    g.column_dimensions["A"].width = 100
    tmp = str(path) + ".작성중.xlsx"
    wb.save(tmp)
    os.replace(tmp, path)


def read_xlsx(path):
    """설계 엑셀 → [{row, sno, name, design}] (빈 줄 건너뜀)."""
    from . import roster

    try:
        it = iter(roster.table_rows(path, "행특 설계"))
    except Exception:
        raise DbError("파일을 열지 못했습니다(xlsx 또는 csv인지 확인하세요).")
    head = [str(v or "").strip() for v in (next(it, None) or [])]
    if head[:4] != XHEAD[:4]:
        raise DbError("행특 설계 엑셀 모양이 아닙니다. [설계 엑셀 양식 내려받기]로 받은 파일에 채워 주세요.")
    out = []
    for i, r in enumerate(it, 2):
        r = [("" if v is None else str(v).strip()) for v in list(r or []) + [None] * 16][:16]
        if not any(r[2:]):
            continue
        areas = {}
        for k, a in enumerate(AREAS):
            b = 4 + k * 4
            areas[a] = {"case": r[b], "kws": [x for x in r[b + 1:b + 4] if x]}
        try:
            d = normalize({"type": r[2], "desc": r[3], "areas": areas})
        except DbError as e:
            out.append({"row": i, "sno": r[0], "name": r[1], "error": str(e)})
            continue
        out.append({"row": i, "sno": r[0], "name": r[1], "design": d})
    return out
