"""행특 설계 사전: 성격유형(설명 목록)과 영역별 키워드(설명·추천 성격유형).
설정(config)의 trait_dict에 저장한다(없으면 기본 사전). 엑셀은 '역량요소' 시트와 같은 8열로 주고받는다."""
import copy

from . import config
from .db import DbError
from .trait_dict_default import DEFAULT

AREAS = ("academic", "attitude", "social")
AREA_NAMES = {"academic": "학업 역량", "attitude": "학업 태도", "social": "인성 및 학업 외 소양"}
HEAD = ["성격유형", "성격유형에 따른 설명", "학업역량 키워드", "학업역량 키워드 설명", "학업태도 키워드", "학업태도 키워드 설명",
        "인성 및 학업 외 소양", "인성 및 학업 외 소양 설명"]
MAX_TYPES, MAX_DESCS, MAX_KWS = 60, 60, 400


def _s(v, n=300):
    return " ".join(str(v).split())[:n] if v is not None else ""


def normalize(d):
    """사전 모양을 고르게: 빈 값·겹침을 빼고 길이를 자른다. 잘못된 모양이면 DbError."""
    if not isinstance(d, dict) or not isinstance(d.get("types"), list) or not isinstance(d.get("areas"), dict):
        raise DbError("사전 모양이 올바르지 않습니다.")
    types, seen = [], set()
    for t in d["types"][:MAX_TYPES]:
        name = _s((t or {}).get("name"), 30)
        if not name or name in seen:
            continue
        seen.add(name)
        descs = []
        for x in (t.get("descs") or [])[:MAX_DESCS]:
            x = _s(x, 120)
            if x and x not in descs:
                descs.append(x)
        types.append({"name": name, "descs": descs})
    areas = {}
    for a in AREAS:
        out, kws = [], set()
        for e in (d["areas"].get(a) or [])[:MAX_KWS]:
            kw = _s((e or {}).get("kw"), 30)
            if not kw or kw in kws:
                continue
            kws.add(kw)
            out.append({"kw": kw, "desc": _s(e.get("desc"), 200), "types": [x for x in (_s(y, 30) for y in (e.get("types") or [])) if x][:MAX_TYPES]})
        areas[a] = out
    return {"types": types, "areas": areas}


def load():
    d = config.load().get("trait_dict")
    try:
        return normalize(d) if d else copy.deepcopy(DEFAULT)
    except DbError:
        return copy.deepcopy(DEFAULT)


def is_default():
    return not config.load().get("trait_dict")


def save(d):
    """새 사전 저장. 바로 앞 사전은 trait_dict_prev로 남긴다(되돌리기 한 번)."""
    new = normalize(d)
    if not new["types"]:
        raise DbError("성격유형이 하나도 없습니다.")
    config.save({"trait_dict_prev": load(), "trait_dict": new})
    return new


def reset():
    config.save({"trait_dict_prev": load(), "trait_dict": None})
    return load()


def undo():
    prev = config.load().get("trait_dict_prev")
    if not prev:
        raise DbError("되돌릴 앞 사전이 없습니다.")
    cur = load()
    config.save({"trait_dict": normalize(prev), "trait_dict_prev": cur})
    return load()


def diff(old, new):
    """바뀌는 수: {types: {add, change, gone}, areas: {영역: {add, change, gone}}}"""
    def cmp(a, b, key, val):
        ka, kb = {key(x): val(x) for x in a}, {key(x): val(x) for x in b}
        return {"add": len([k for k in kb if k not in ka]), "change": len([k for k in kb if k in ka and ka[k] != kb[k]]), "gone": len([k for k in ka if k not in kb])}
    return {"types": cmp(old["types"], new["types"], lambda x: x["name"], lambda x: x["descs"]),
            "areas": {a: cmp(old["areas"][a], new["areas"][a], lambda x: x["kw"], lambda x: (x["desc"], x["types"])) for a in AREAS}}


# ---------- 엑셀(8열) ----------
def to_xlsx(d, path):
    """'역량요소' 시트와 같은 8열. 성격유형마다 설명 줄을 쓰고, 그 유형을 추천으로 단 키워드를 같은 줄들에 나란히 놓는다."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "역량요소"
    ws.append(HEAD)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="E8EEF8")
    placed = {a: set() for a in AREAS}
    rows = []
    for t in d["types"]:
        per = {a: [e for e in d["areas"][a] if t["name"] in e["types"]] for a in AREAS}  # 추천 유형이 여럿이면 유형마다 한 줄씩(올릴 때 합침)
        n = max([len(t["descs"])] + [len(v) for v in per.values()] + [1])
        for i in range(n):
            row = [t["name"], t["descs"][i] if i < len(t["descs"]) else ""]
            for a in AREAS:
                e = per[a][i] if i < len(per[a]) else None
                row += [e["kw"], e["desc"]] if e else ["", ""]
                if e:
                    placed[a].add(e["kw"])
            rows.append(row)
    rest = {a: [e for e in d["areas"][a] if e["kw"] not in placed[a]] for a in AREAS}  # 추천 유형 없는 키워드
    for i in range(max([len(v) for v in rest.values()] + [0])):
        row = ["", ""]
        for a in AREAS:
            e = rest[a][i] if i < len(rest[a]) else None
            row += [e["kw"], e["desc"]] if e else ["", ""]
        rows.append(row)
    for r in rows:
        ws.append([v if v else None for v in r])
    for col, w in zip("ABCDEFGH", (14, 40, 16, 48, 16, 48, 18, 48)):
        ws.column_dimensions[col].width = w
    for r in ws.iter_rows(min_row=2):
        for c in r:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    g = wb.create_sheet("안내")
    for line in ("행특 설계 사전 — 이 파일을 고쳐 [📤 엑셀 올리기]로 바꿉니다.",
                 "· 1열 성격유형 + 2열 설명이 있는 줄마다 그 유형의 설명이 하나씩 들어갑니다.",
                 "· 키워드는 영역마다 '키워드 + 설명' 두 열입니다. 같은 줄의 성격유형이 그 키워드의 '추천 유형'이 됩니다(비워도 됨).",
                 "· 같은 키워드를 여러 줄에 쓰면 하나로 합치고 추천 유형만 늘어납니다.",
                 "· 시트 이름·열 순서는 바꾸지 마세요. 학생 이름 등 인적사항은 넣지 마세요."):
        g.append([line])
    g.column_dimensions["A"].width = 100
    tmp = str(path) + ".작성중.xlsx"
    wb.save(tmp)
    import os
    os.replace(tmp, path)


def from_xlsx(path):
    """8열 엑셀 → 사전. 첫 시트(또는 '역량요소')의 1행은 머리글."""
    from openpyxl import load_workbook

    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        raise DbError("엑셀 파일을 열지 못했습니다(xlsx인지 확인하세요).")
    try:
        ws = wb["역량요소"] if "역량요소" in wb.sheetnames else wb.worksheets[0]
        it = ws.iter_rows(values_only=True)
        head = [_s(v, 40) for v in (next(it, None) or [])][:8]
        if len(head) < 8 or "성격유형" not in head[0] or "키워드" not in head[2]:
            raise DbError("사전 엑셀 모양이 아닙니다. 1행이 '성격유형 · 성격유형에 따른 설명 · 학업역량 키워드 · …' 8열이어야 합니다.")
        types, areas = {}, {a: {} for a in AREAS}
        for r in it:
            r = list(r or []) + [None] * 8
            t, td = _s(r[0], 30), _s(r[1], 120)
            if t and td:
                types.setdefault(t, [])
                if td not in types[t]:
                    types[t].append(td)
            for k, a in enumerate(AREAS):
                kw, desc = _s(r[2 + k * 2], 30), _s(r[3 + k * 2], 200)
                if not kw:
                    continue
                e = areas[a].setdefault(kw, {"kw": kw, "desc": desc, "types": []})
                if desc and not e["desc"]:
                    e["desc"] = desc
                if t and t not in e["types"]:
                    e["types"].append(t)
    finally:
        wb.close()
    d = normalize({"types": [{"name": k, "descs": v} for k, v in types.items()], "areas": {a: list(v.values()) for a, v in areas.items()}})
    if not d["types"]:
        raise DbError("성격유형과 설명이 있는 줄이 없습니다.")
    return d
