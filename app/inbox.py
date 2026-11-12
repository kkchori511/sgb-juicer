"""자료 인박스: 묶음(batch) 단위로 가져오기 → 학생 매칭 → (선택) AI 정제 → 보내기.

- 학번·이름은 이 PC 안에서만 매칭에 쓰고, 행의 content에는 내용만 둔다.
- 매칭은 규칙으로만 한다(AI 쓰지 않음). 학번+이름 일치는 자동 확정, 그 밖은 '추천'으로 두고 선생님이 확정.
- 보내기는 모든 행이 확정 또는 제외일 때만, 한 번에(전부 성공 또는 전부 취소).
"""
import datetime as dt
import json
import re

from .db import DbError, YearDb
from .records import Records
from . import scan
from .roster import split_student_no
from .textutil import count_bytes

STAGES = ("import", "match", "refine", "review", "sent")
MAX_CANDS = 3
NO_RE = re.compile(r"^\d{4,6}$")
NAME_RE = re.compile(r"^[가-힣]{2,5}$")


def col_name(i: int) -> str:
    s, i = "", i + 1
    while i > 0:
        i, m = divmod(i - 1, 26)
        s = chr(65 + m) + s
    return s


def lev(a: str, b: str) -> int:
    if a == b:
        return 0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def label_date(label: str, school_year: int) -> str:
    """'3/15', '3.15', '3월 15일', '2026-03-15' → YYYY-MM-DD (1·2월은 다음 해)."""
    t = (label or "").strip()
    m = re.search(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", t)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        m = re.search(r"(\d{1,2})\s*(?:/|\.|월)\s*(\d{1,2})\s*일?", t)
        if not m:
            return ""
        mo, d = int(m.group(1)), int(m.group(2))
        y = school_year + 1 if mo <= 2 else school_year
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return ""


def _transpose(g):
    w = max(len(r) for r in g)
    return [[(g[i][j] if j < len(g[i]) else "") for i in range(len(g))] for j in range(w)]


def _ratio(vals, rx):
    vals = [v for v in vals if v]
    return (sum(1 for v in vals if rx.match(v.replace(" ", ""))) / len(vals)) if vals else 0


def detect(raw: list[list[str]]) -> dict:
    """표 모양 추정: 학생이 행인지 열인지, 학번·이름 줄, 첫 줄 제목 여부."""
    best = None
    for orient in ("rows", "cols"):
        g = raw if orient == "rows" else _transpose(raw)
        width = max(len(r) for r in g)
        for header in (False, True):  # 같은 점수면 머리글 없음(첫 줄 학생을 빼먹지 않게)
            body = g[1:] if header else g
            if not body:
                continue
            nos = [j for j in range(width) if _ratio([r[j] if j < len(r) else "" for r in body], NO_RE) >= 0.6]
            names = [j for j in range(width) if j not in nos and _ratio([r[j] if j < len(r) else "" for r in body], NAME_RE) >= 0.6]
            score = (2 if nos else 0) + (1 if names else 0) + (0.5 if header and _header_like(g[0]) else 0) + (0.1 if orient == "rows" else 0)
            if best is None or score > best[0]:
                best = (score, {"orient": orient, "header": header, "no_idx": nos[0] if nos else None, "name_idx": names[0] if names else None})
    out = best[1]
    out["found"] = best[0] >= 1
    g = raw if out["orient"] == "rows" else _transpose(raw)
    roles, neis, header = guess_roles(g, out["header"], out["no_idx"], out["name_idx"])
    out.update(roles=roles, neis=neis, header=header)
    pos = {r: int(j) for j, r in reversed(list(roles.items()))}
    out["no_idx"], out["name_idx"] = pos.get("student_no"), pos.get("name")
    out["found"] = out["found"] or any(r in ID_ROLES for r in roles.values())
    return out


# 인박스 열 역할(화면에서 고르는 것). 학번·학년·반·번호·반/번호·이름은 학생 찾기, 내용은 기록, 학적변동은 안내.
ROLES = ("student_no", "grade", "class_no", "number", "clsnum", "name", "change", "content")
ID_ROLES = ("student_no", "grade", "class_no", "number", "clsnum", "name")


def guess_roles(g, header, no_idx=None, name_idx=None):
    """머리글·칸 모양으로 열 역할을 짐작한다 → ({'열번호': 역할}, 나이스 파일인지, 첫 줄 머리글인지).
    나이스 파일(학생개인번호·반/번호·성명)은 학년·반/번호·성명·학적변동·특기사항 칸만 쓴다(학생개인번호는 학번이 아님)."""
    from . import existing

    if not g:
        return {}, False, bool(header)
    # 첫 줄이 머리글인지는 표 모양 추정(detect)을 따른다. 머리글이 없으면 빈 줄을 앞에 붙여 본문을 머리글로 오해하지 않게 한다.
    header = bool(header)
    ex = existing.detect(g if header else [[""] * max(len(r) for r in g)] + g)
    cols = ex["columns"]
    roles = {}
    for role in ("student_no", "name", "grade", "class_no", "number", "clsnum", "change"):
        if cols.get(role) is not None:
            roles[int(cols[role])] = role
    if cols.get("clsany") is not None and "clsnum" not in roles.values():
        roles[int(cols["clsany"])] = "clsnum"
    for idx, role in ((no_idx, "student_no"), (name_idx, "name")):  # 칸 모양으로 찾은 학번·이름(머리글이 다른 뜻이면 쓰지 않음)
        if idx is not None and role not in roles.values() and int(idx) not in roles and not (header and existing.header_role(g[0][int(idx)] if int(idx) < len(g[0]) else "")):
            roles[int(idx)] = role
    neis = header and existing.is_neis(g[0])
    width = max(len(r) for r in g)
    body = g[1:] if header else g
    if neis:
        content = [int(cols["content"])] if cols.get("content") is not None else []
    else:
        skip = {j for j, c in enumerate(g[0]) if header and existing.header_role(c) in ("ignore", "title", "date")}
        content = [j for j in range(width) if j not in roles and j not in skip and any(j < len(r) and r[j] for r in body)]
    for j in content:
        roles[j] = "content"
    return {str(j): r for j, r in sorted(roles.items())}, neis, header


def _role_cols(opts, g, header):
    """opts의 열 역할 → {역할: [열번호]}. 역할을 정하지 않은 예전 묶음은 짐작한다."""
    roles = opts.get("roles")
    if roles is None:
        roles = guess_roles(g, header, _int(opts.get("no_idx")), _int(opts.get("name_idx")))[0]
    out = {}
    for j, r in roles.items():
        if r in ROLES:
            out.setdefault(r, []).append(int(j))
    return {r: sorted(v) for r, v in out.items()}


def _int(v):
    return int(v) if v not in (None, "") else None


def cls_text(ext):
    """읽은 학년·반·번호를 보기 좋게: '1학년 1반 1번'."""
    from . import existing

    if not ext:
        return ""
    g, c, n = ext.get("grade"), ext.get("class_no"), ext.get("number")
    if ext.get("cls"):
        opts = existing.class_options(ext["cls"], "clsnum")
        if opts:
            _, c, n = opts[0]
        else:
            return ext["cls"]
    parts = [f"{g}학년" if g else "", f"{c}반" if c else "", f"{n}번" if n else ""]
    return " ".join(p for p in parts if p)


def _header_like(line):
    joined = " ".join(line)
    return any(k in joined for k in ("학번", "이름", "성명", "번호")) or any(label_date(c, 2000) for c in line)


def interpret(raw, opts, school_year):
    """원본 표 → 만들어질 기록 목록. opts:
    structure: multi / single, orient: rows / cols, header: bool, no_idx/name_idx: 학번·이름 줄,
    order(single): row / col"""
    structure = opts.get("structure", "multi")
    header = bool(opts.get("header"))
    if not raw:
        return []
    out = []
    if structure == "single":
        width = max(len(r) for r in raw)
        labels = raw[0] if header else [""] * width
        body_rows = list(range(1, len(raw))) if header else list(range(len(raw)))
        cells = []
        if opts.get("order") == "col":
            for j in range(width):
                for i in body_rows:
                    cells.append((i, j))
        else:
            for i in body_rows:
                for j in range(width):
                    cells.append((i, j))
        n = 0
        for i, j in cells:
            v = raw[i][j].strip() if j < len(raw[i]) else ""
            if not v:
                continue
            n += 1
            lab = (labels[j] if j < len(labels) else "").strip()
            out.append({"line": 0, "source_ref": f"{col_name(j)}{i + 1}", "ext_no": "", "ext_name": "",
                        "label": lab or f"{n}회", "date": label_date(lab, school_year), "content": v})
        return out
    orient = opts.get("orient", "rows")
    g = raw if orient == "rows" else _transpose(raw)
    width = max(len(r) for r in g)
    cols = _role_cols(opts, g, header)
    labels = g[0] if header else [""] * width
    start = 1 if header else 0
    first = lambda role: (cols.get(role) or [None])[0]
    content_cols = cols.get("content", [])

    def num(v):
        v = re.sub(r"[^\d]", "", v)
        return int(v) if v else None

    for li, i in enumerate(range(start, len(g))):
        line = g[i]
        get = lambda j: (line[j].strip() if j is not None and j < len(line) else "")
        ext_no = re.sub(r"\s", "", get(first("student_no")))
        ext_name = re.sub(r"\s", "", get(first("name")))
        ext = {k: v for k, v in (("grade", num(get(first("grade")))), ("class_no", num(get(first("class_no")))),
                                 ("number", num(get(first("number")))), ("cls", get(first("clsnum"))),
                                 ("change", get(first("change")))) if v}
        for k, j in enumerate(content_cols, 1):
            v = get(j)
            if not v:
                continue
            lab = (labels[j] if j < len(labels) else "").strip()
            ref = f"{col_name(j)}{i + 1}" if orient == "rows" else f"{col_name(i)}{j + 1}"
            out.append({"line": li + 1, "source_ref": ref, "ext_no": ext_no, "ext_name": ext_name, "ext": ext, "ext_cls": cls_text(ext),
                        "label": lab or f"{k}회", "date": label_date(lab, school_year), "content": v})
    return out


def match_ext(ext_no, ext_name, ext, members):
    """학번·이름에 학년·반·번호(반/번호 칸 포함)까지 써서 학생을 찾는다. 학적변동이 재학이 아니면 확인을 받는다."""
    from . import existing

    ext = ext or {}
    if not any(ext.get(k) for k in ("grade", "class_no", "number", "cls")):
        sno, state, note = match_one(ext_no, ext_name, members)
    else:
        grade = ext.get("grade")
        e = {"student_no": ext_no, "name": ext_name}
        if ext.get("cls"):
            e["class_opts"] = [(o[0] if o[0] is not None else grade, o[1], o[2]) for o in existing.class_options(ext["cls"], "clsnum")]
            if not e["class_opts"] and grade:
                e["grade"] = grade
        else:
            e.update(grade=grade, class_no=ext.get("class_no"), number=ext.get("number"))
        sno, state, note = existing.match_row(e, members)
        m = next((x for x in members if x["student_no"] == sno), None)
        if m and not m["active"]:
            sno, state, note = None, "none", f"{m['name']}: 비활성 학생(명렬에서 다시 활성화하거나 제외)"
    change = (ext.get("change") or "").strip()
    if change and change != "재학":
        note = (note + " · " if note else "") + f"학적변동: {change} — 가져올지 확인해 주세요"
        if state == "confirmed":
            state = "suggested"
    return sno, state, note


def _ext(row):
    try:
        return json.loads(row.get("ext") or "{}")
    except (TypeError, ValueError):
        return {}


def match_one(ext_no, ext_name, members):
    """(student_no, state, note). members: [{student_no, name, active}]"""
    active = [m for m in members if m["active"]]
    by_no = {m["student_no"]: m for m in members}
    if ext_no and ext_no in by_no:
        m = by_no[ext_no]
        if not m["active"]:
            return None, "none", f"{m['name']}: 비활성 학생(명렬에서 다시 활성화하거나 제외)"
        if ext_name == m["name"]:
            return m["student_no"], "confirmed", ""
        if not ext_name:
            return m["student_no"], "suggested", f"이름 없음 — 학번으로 추천({m['name']})"
        return m["student_no"], "suggested", f"이름 다름(원본 {ext_name} / 명렬 {m['name']})"
    if ext_name:
        same = [m for m in active if m["name"] == ext_name]
        if len(same) == 1:
            return same[0]["student_no"], "suggested", "학번 없음·다름 — 이름으로 추천" if ext_no else "학번 없음 — 이름으로 추천"
        if len(same) > 1:
            return None, "none", f"동명이인 {len(same)}명 — 학번으로 골라 주세요"
        near = [m for m in active if len(ext_name) >= 2 and lev(ext_name, m["name"]) == 1]
        if len(near) == 1:
            return near[0]["student_no"], "suggested", f"비슷한 이름({near[0]['name']}) 추천"
    if ext_no and not ext_name:
        parts = split_student_no(ext_no)
        return None, "none", "명렬에 없는 학번" if parts else "학번 형식이 다름"
    return None, "none", "명렬에서 찾지 못함"


class Inbox:
    def __init__(self, d: YearDb):
        self.d = d
        self.rec = Records(d)

    # ---------- 묶음 ----------
    def batches(self):
        rows = self.d.q(
            """SELECT b.*, (SELECT COUNT(*) FROM inbox_rows r WHERE r.batch_id=b.id) AS n,
                      (SELECT COUNT(*) FROM inbox_rows r WHERE r.batch_id=b.id AND r.state IN ('none','suggested')) AS pending
               FROM inbox_batches b ORDER BY (b.stage='sent'), b.updated_at DESC, b.id DESC"""
        )
        for b in rows:
            b.pop("meta", None)
        return rows

    def batch(self, bid):
        rows = self.d.q("SELECT * FROM inbox_batches WHERE id=?", (int(bid),))
        if not rows:
            raise DbError("자료 묶음을 찾지 못했습니다.")
        b = rows[0]
        b["meta"] = json.loads(b["meta"] or "{}")
        b["tag_ids"] = json.loads(b["tag_ids"] or "[]")
        return b

    def _touch(self, c, bid, **fields):
        fields["updated_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sets = ", ".join(f"{k}=?" for k in fields)
        c.execute(f"UPDATE inbox_batches SET {sets} WHERE id=?", (*fields.values(), int(bid)))

    def create(self, title, group_id, item):
        self.rec.slot(group_id, item)
        title = (title or "").strip() or f"자료 {dt.date.today().strftime('%m-%d')}"
        with self.d.tx() as c:
            return c.execute("INSERT INTO inbox_batches(title, group_id, item, date) VALUES(?,?,?,?)",
                             (title, int(group_id), item, dt.date.today().isoformat())).lastrowid

    def update(self, bid, data):
        b = self.batch(bid)
        if b["stage"] == "sent":
            raise DbError("이미 보낸 묶음은 고칠 수 없습니다.")
        fields = {}
        if "title" in data:
            fields["title"] = (data["title"] or "").strip() or b["title"]
        if "date" in data:
            fields["date"] = (data["date"] or "").strip()
        if "tag_ids" in data:
            fields["tag_ids"] = json.dumps([int(x) for x in data["tag_ids"] or []])
        regroup = False
        if "group_id" in data or "item" in data:
            gid = int(data.get("group_id", b["group_id"]))
            item = data.get("item", b["item"])
            self.rec.slot(gid, item)
            regroup = gid != b["group_id"]
            fields.update(group_id=gid, item=item)
        with self.d.tx() as c:
            self._touch(c, bid, **fields)
        if regroup and self._rows(bid):
            self.rematch(bid, keep_manual=False)

    def delete(self, bid):
        with self.d.tx() as c:
            c.execute("DELETE FROM inbox_batches WHERE id=?", (int(bid),))
        p = scan.pdf_path(self.d.year, bid)
        if p.exists():
            p.unlink()

    # ---------- ① 가져오기 ----------
    def set_source(self, bid, raw, source, filename=""):
        b = self.batch(bid)
        if b["stage"] == "sent":
            raise DbError("이미 보낸 묶음입니다.")
        meta = b["meta"]
        meta.update(raw=raw, filename=filename)
        meta["opts"] = {"structure": b["structure"], **detect(raw)}
        with self.d.tx() as c:
            self._touch(c, bid, meta=json.dumps(meta, ensure_ascii=False), source=source)
        return meta["opts"]

    def preview(self, bid, opts):
        b = self.batch(bid)
        raw = b["meta"].get("raw") or []
        return interpret(raw, opts, self.d.year)

    def guess(self, bid, opts):
        raw = self.batch(bid)["meta"].get("raw") or []
        if not raw:
            return {}, False
        g = raw if opts.get("orient", "rows") == "rows" else _transpose(raw)
        roles, neis, _ = guess_roles(g, bool(opts.get("header")))
        return roles, neis

    def confirm_import(self, bid, opts):
        b = self.batch(bid)
        if b["stage"] == "sent":
            raise DbError("이미 보낸 묶음입니다.")
        raw = b["meta"].get("raw") or []
        recs = interpret(raw, opts, self.d.year)
        if not recs:
            raise DbError("만들어질 기록이 없습니다. 표 해석 설정을 확인해 주세요.")
        structure = opts.get("structure", "multi")
        if structure == "single" and not opts.get("student_no"):
            raise DbError("기록을 넣을 학생을 골라 주세요.")
        if structure == "multi" and not any(r["ext_no"] or r["ext_name"] or r["ext_cls"] for r in recs):
            raise DbError("학번·이름(또는 학년·반·번호) 열을 골라 주세요. 학생을 알 수 없으면 '한 학생에게 여러 건'을 고르세요.")
        meta = b["meta"]
        meta["opts"] = opts
        members = self.d.members(b["group_id"])
        with self.d.tx() as c:
            c.execute("DELETE FROM inbox_rows WHERE batch_id=?", (int(bid),))
            for k, r in enumerate(recs):
                if structure == "single":
                    sno, state, note = str(opts["student_no"]), "confirmed", "고른 학생"
                else:
                    sno, state, note = match_ext(r["ext_no"], r["ext_name"], r.get("ext"), members)
                c.execute(
                    """INSERT INTO inbox_rows(batch_id, ord, source_ref, ext_no, ext_name, ext, student_no, state, note, line, label, date, content)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (int(bid), k, r["source_ref"], r["ext_no"], r["ext_name"], json.dumps(r.get("ext") or {}, ensure_ascii=False),
                     sno, state, note, r["line"], r["label"], r["date"], r["content"]),
                )
            self._touch(c, bid, meta=json.dumps(meta, ensure_ascii=False), structure=structure, stage="match")
        return len(recs)

    # ---------- ① 가져오기: 스캔 PDF ----------
    def scan_set(self, bid, src_path, filename):
        import shutil

        b = self._editable_batch(bid)
        dest = scan.pdf_path(self.d.year, bid)
        shutil.copyfile(src_path, dest)
        try:
            n = scan.page_count(dest)
        except Exception:
            dest.unlink()
            raise DbError("PDF를 열지 못했습니다.")
        if n == 0:
            raise DbError("PDF에 페이지가 없습니다.")
        meta = b["meta"]
        meta.pop("raw", None)
        meta["scan"] = {"pages": n, "filename": filename, "per": 1, "ocr": None, "starts": None, "skipped": []}
        with self.d.tx() as c:
            self._touch(c, bid, meta=json.dumps(meta, ensure_ascii=False), source="scan", structure="multi")
        return meta["scan"]

    def scan_save_ocr(self, bid, texts, per):
        b = self._editable_batch(bid)
        meta = b["meta"]
        sc = meta.get("scan") or {}
        sc["ocr"] = texts
        sc["per"] = max(1, int(per or 1))
        sc["starts"] = [g[0] for g in scan.default_groups(len(texts), sc["per"])]
        sc["skipped"] = []
        meta["scan"] = sc
        with self.d.tx() as c:
            self._touch(c, bid, meta=json.dumps(meta, ensure_ascii=False))

    def _scan(self, bid):
        b = self.batch(bid)
        sc = b["meta"].get("scan") or {}
        if not sc.get("ocr"):
            raise DbError("먼저 OCR을 실행해 주세요.")
        return b, sc

    def scan_groups(self, bid, starts=None, skipped=None):
        b, sc = self._scan(bid)
        texts = sc["ocr"]
        starts = sc["starts"] if starts is None else starts
        skipped = sc["skipped"] if skipped is None else skipped
        members = self.d.members(b["group_id"]) if b["group_id"] else []
        out = []
        for i, g in enumerate(scan.groups_from_starts(len(texts), starts, skipped)):
            raw = "\n\n".join(texts[p] for p in g).strip()
            no, name = scan.extract_ids(texts[g[0]], members)
            out.append({"index": i, "pages": g, "ext_no": no, "ext_name": name,
                        "content": scan.strip_pages([texts[p] for p in g], no, name, members), "empty": not raw.strip()})
        return {"groups": out, "page_texts": [t[:300] for t in texts], "starts": starts, "skipped": skipped}

    def scan_confirm(self, bid, starts, skipped):
        self._editable_batch(bid)
        b, sc = self._scan(bid)
        res = self.scan_groups(bid, starts, skipped)
        groups = [g for g in res["groups"] if not g["empty"]]
        if not groups:
            raise DbError("인식된 글자가 있는 페이지가 없습니다.")
        members = self.d.members(b["group_id"])
        meta = b["meta"]
        sc["starts"], sc["skipped"] = starts, skipped
        meta["scan"] = sc
        with self.d.tx() as c:
            if self.batch(bid)["stage"] == "sent":
                raise DbError("이미 보낸 묶음입니다.")
            c.execute("DELETE FROM inbox_rows WHERE batch_id=?", (int(bid),))
            for k, g in enumerate(groups):
                pg = g["pages"]
                ref = f"{pg[0] + 1}쪽" if len(pg) == 1 else f"{pg[0] + 1}~{pg[-1] + 1}쪽"
                sno, state, note = match_one(g["ext_no"], g["ext_name"], members)
                if not g["ext_no"] and not g["ext_name"]:
                    note = "학번·이름을 읽지 못함 — 원본을 보고 골라 주세요"
                c.execute(
                    """INSERT INTO inbox_rows(batch_id, ord, source_ref, ext_no, ext_name, student_no, state, note, line, label, date, content, pages)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (int(bid), k, ref, g["ext_no"], g["ext_name"], sno, state, note, k + 1, b["title"], "", g["content"] or "(내용 없음)",
                     ",".join(str(p) for p in pg)),
                )
            self._touch(c, bid, meta=json.dumps(meta, ensure_ascii=False), stage="match")
        return len(groups)

    def scan_raw_text(self, bid, pages):
        _, sc = self._scan(bid)
        return [{"page": int(p), "text": sc["ocr"][int(p)]} for p in pages if 0 <= int(p) < len(sc["ocr"])]

    # ---------- ② 매칭 ----------
    def _rows(self, bid):
        return self.d.q("SELECT * FROM inbox_rows WHERE batch_id=? ORDER BY ord", (int(bid),))

    def view(self, bid):
        b = self.batch(bid)
        rows = self._rows(bid)
        members = self.d.members(b["group_id"]) if b["group_id"] else []
        names = {m["student_no"]: m for m in members}
        cands = {}
        if rows:
            marks = ",".join("?" * len(rows))
            for cd in self.d.q(f"SELECT * FROM inbox_cands WHERE row_id IN ({marks}) ORDER BY id", tuple(r["id"] for r in rows)):
                cd["meta"] = json.loads(cd["meta"] or "{}")
                cd["bytes"] = count_bytes(cd["text"])
                cands.setdefault(cd["row_id"], []).append(cd)
        # 같은 학생이 원본의 서로 다른 줄에서 나오면 중복 의심
        lines = {}
        for r in rows:
            if r["student_no"] and r["state"] in ("confirmed", "suggested") and b["structure"] == "multi":
                lines.setdefault(r["student_no"], set()).add(r["line"])
        for r in rows:
            m = names.get(r["student_no"]) if r["student_no"] else None
            r["matched_name"] = m["name"] if m else ""
            r["ext_cls"] = cls_text(_ext(r))
            r["dup"] = bool(r["student_no"] and len(lines.get(r["student_no"], ())) > 1)
            r["cands"] = cands.get(r["id"], [])
            r["text"] = r["used_text"] if r["used_text"] is not None else r["content"]
            r["bytes"] = count_bytes(r["text"])
        counts = {s: sum(1 for r in rows if r["state"] == s) for s in ("confirmed", "suggested", "none", "excluded")}
        return {"batch": b, "rows": rows, "members": [m for m in members if m["active"]], "counts": counts}

    def set_student(self, row_id, sno):
        r = self._row(row_id)
        b = self._editable_batch(r["batch_id"])
        if sno:
            m = next((x for x in self.d.members(b["group_id"]) if x["student_no"] == str(sno)), None)
            if not m:
                raise DbError("이 담당 명렬의 학생이 아닙니다.")
            if not m["active"]:
                raise DbError("비활성 학생입니다. 명렬에서 다시 활성화하거나 이 행을 제외하세요.")
        with self.d.tx() as c:
            c.execute("UPDATE inbox_rows SET student_no=?, state=?, exclude_reason='' WHERE id=?",
                      (str(sno) if sno else None, "confirmed" if sno else "none", r["id"]))
            self._touch(c, r["batch_id"])

    def confirm_suggested(self, bid, row_ids=None):
        self._editable_batch(bid)
        with self.d.tx() as c:
            if row_ids:
                marks = ",".join("?" * len(row_ids))
                n = c.execute(f"UPDATE inbox_rows SET state='confirmed' WHERE batch_id=? AND state='suggested' AND id IN ({marks})",
                              (int(bid), *[int(x) for x in row_ids])).rowcount
            else:
                n = c.execute("UPDATE inbox_rows SET state='confirmed' WHERE batch_id=? AND state='suggested'", (int(bid),)).rowcount
            self._touch(c, bid)
        return n

    def exclude(self, row_ids, reason, on=True):
        ids = [int(x) for x in row_ids or []]
        if not ids:
            raise DbError("행을 고르세요.")
        first = self._row(ids[0])
        self._editable_batch(first["batch_id"])
        reason = (reason or "").strip() or "기타"
        with self.d.tx() as c:
            for rid in ids:
                r = self._row(rid)
                if on:
                    c.execute("UPDATE inbox_rows SET state='excluded', exclude_reason=? WHERE id=?", (reason, rid))
                else:
                    c.execute("UPDATE inbox_rows SET state=CASE WHEN student_no IS NULL THEN 'none' ELSE 'suggested' END, exclude_reason='' WHERE id=?", (rid,))
            self._touch(c, first["batch_id"])

    def edit_row(self, row_id, data):
        r = self._row(row_id)
        self._editable_batch(r["batch_id"])
        fields = {}
        for k in ("content", "label", "date"):
            if k in data:
                fields[k] = (data[k] or "").strip()
        if "content" in fields and not fields["content"]:
            raise DbError("내용을 비울 수 없습니다. 보내지 않으려면 [제외]를 누르세요.")
        if not fields:
            return
        with self.d.tx() as c:
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE inbox_rows SET {sets} WHERE id=?", (*fields.values(), r["id"]))
            if "content" in fields:
                c.execute("UPDATE inbox_rows SET used_text=NULL WHERE id=?", (r["id"],))

    def rematch(self, bid, keep_manual=True):
        b = self._editable_batch(bid)
        if b["structure"] == "single":
            return
        members = self.d.members(b["group_id"])
        with self.d.tx() as c:
            for r in self._rows(bid):
                if keep_manual and r["state"] in ("confirmed", "excluded"):
                    continue
                sno, state, note = match_ext(r["ext_no"], r["ext_name"], _ext(r), members)
                c.execute("UPDATE inbox_rows SET student_no=?, state=?, note=?, exclude_reason='' WHERE id=?", (sno, state, note, r["id"]))
            self._touch(c, bid)

    def to_stage(self, bid, stage, exclude_pending=False):
        """exclude_pending: 확인이 필요한 행(추천·찾지 못함)을 '제외(매칭 미확인)'로 바꾸고 넘어간다(화면에서 확인을 받은 뒤)."""
        b = self._editable_batch(bid)
        if stage not in STAGES or stage == "sent":
            raise DbError("단계가 올바르지 않습니다.")
        pend = []
        if stage in ("refine", "review"):
            rows = self._rows(bid)
            pend = [r for r in rows if r["state"] in ("none", "suggested")]
            if pend and not exclude_pending:
                raise DbError(f"확인이 필요한 행 {len(pend)}개가 남아 있습니다. 학생을 확정하거나 제외해 주세요.")
            if not any(r["state"] == "confirmed" for r in rows):
                raise DbError("보낼 행이 없습니다. 확정된 학생이 하나도 없습니다.")
        with self.d.tx() as c:
            for r in pend:
                c.execute("UPDATE inbox_rows SET state='excluded', exclude_reason='매칭 미확인' WHERE id=?", (r["id"],))
            self._touch(c, bid, stage=stage)
        return b

    # ---------- ⑤ 보낸 뒤: 묶음 단위 태그·삭제 ----------
    def sent_info(self, bid):
        """이 묶음으로 넣은 기록(source='inbox:묶음번호'). 지금도 같은 항목에 있는 것만 묶음 단위로 다룬다.
        다른 항목으로 옮긴 기록, 마감된 학생의 기록은 지우지 않는다."""
        b = self.batch(bid)
        if b["stage"] != "sent":
            raise DbError("아직 보내지 않은 묶음입니다.")
        recs = self.d.q(
            """SELECT r.id, r.group_id, r.item, r.student_no, r.created_at, r.updated_at,
                      (SELECT COUNT(*) FROM results x WHERE x.record_id=r.id) AS cands
               FROM records r WHERE r.source=? ORDER BY r.student_no, r.id""", (f"inbox:{int(bid)}",))
        here = [r for r in recs if r["group_id"] == b["group_id"] and r["item"] == b["item"]]
        rec = Records(self.d)
        closed_sno = {r["student_no"] for r in here if rec.is_closed(b["group_id"], b["item"], r["student_no"])}
        free = [r for r in here if r["student_no"] not in closed_sno]
        tag_counts = {}
        if here:
            marks = ",".join("?" * len(here))
            for t in self.d.q(f"SELECT tag_id, COUNT(*) n FROM record_tags WHERE record_id IN ({marks}) GROUP BY tag_id", tuple(r["id"] for r in here)):
                tag_counts[str(t["tag_id"])] = t["n"]
        return {"record_ids": [r["id"] for r in here], "deletable": [r["id"] for r in free],
                "students": len({r["student_no"] for r in here}), "closed": sum(1 for r in here if r["student_no"] in closed_sno),
                "closed_students": len(closed_sno), "moved": len(recs) - len(here),
                "edited": sum(1 for r in free if (r["updated_at"] or "") > (r["created_at"] or "")),
                "with_cands": sum(1 for r in free if r["cands"]), "tag_counts": tag_counts}

    def delete_sent(self, bid):
        """이 묶음으로 넣은 기록을 모든 학생에서 지운다(마감·옮긴 기록 빼고).
        남은 기록이 없으면 묶음을 '④ 보내기 검토'로 되돌려 다시 보낼 수 있게 한다."""
        b = self.batch(bid)
        info = self.sent_info(bid)
        ids = info["deletable"]
        if not ids:
            raise DbError("지울 수 있는 기록이 없습니다(마감된 학생이거나 다른 항목으로 옮긴 기록만 남음).")
        marks = ",".join("?" * len(ids))
        snos = {r["student_no"] for r in self.d.q(f"SELECT student_no FROM records WHERE id IN ({marks})", tuple(ids))}
        reopened = not info["closed"] and not info["moved"]
        with self.d.tx() as c:
            c.execute(f"DELETE FROM results WHERE record_id IN ({marks})", tuple(ids))
            c.execute(f"DELETE FROM records WHERE id IN ({marks})", tuple(ids))
            for sno in snos:
                c.execute("UPDATE finals SET stale=1 WHERE group_id=? AND item=? AND student_no=? AND text<>''", (b["group_id"], b["item"], sno))
            if reopened:
                self._touch(c, bid, stage="review", sent_at=None, sent_summary="")
            else:
                left = info["closed"] + info["moved"]
                self._touch(c, bid, sent_summary=f"{b['sent_summary']} · {len(ids)}건 삭제(남은 {left}건)")
        return {"deleted": len(ids), "students": len(snos), "reopened": reopened, "closed": info["closed"], "moved": info["moved"]}

    # ---------- ③ 정제 후보 ----------
    def _row(self, row_id):
        rows = self.d.q("SELECT * FROM inbox_rows WHERE id=?", (int(row_id),))
        if not rows:
            raise DbError("행을 찾지 못했습니다.")
        return rows[0]

    def _editable_batch(self, bid):
        b = self.batch(bid)
        if b["stage"] == "sent":
            raise DbError("이미 보낸 묶음은 고칠 수 없습니다. 보낸 기록은 항목별 기록에서 고치세요.")
        return b

    def reorder(self, bid, row_ids):
        """인박스 행 순서를 화면에서 끈 순서로."""
        ids = [int(x) for x in row_ids or []]
        with self.d.tx() as c:
            b = self.batch(bid)
            if b["stage"] == "sent":
                raise DbError("이미 보낸 묶음은 고칠 수 없습니다.")
            have = {r[0] for r in c.execute("SELECT id FROM inbox_rows WHERE batch_id=?", (int(bid),))}
            if set(ids) != have or len(ids) != len(have):
                raise DbError("행 목록이 바뀌었습니다. 화면을 다시 열어 주세요.")
            for i, rid in enumerate(ids):
                c.execute("UPDATE inbox_rows SET ord=? WHERE id=?", (i + 1, rid))

    def add_cand(self, row_id, text, meta, cost):
        r = self._row(row_id)
        self._editable_batch(r["batch_id"])
        with self.d.tx() as c:
            ids = [x[0] for x in c.execute("SELECT id FROM inbox_cands WHERE row_id=? ORDER BY id", (r["id"],))]
            for old in ids[: max(0, len(ids) - MAX_CANDS + 1)]:
                c.execute("DELETE FROM inbox_cands WHERE id=?", (old,))
            return c.execute("INSERT INTO inbox_cands(row_id, text, meta, cost) VALUES(?,?,?,?)",
                             (r["id"], text, json.dumps(meta or {}, ensure_ascii=False), float(cost or 0))).lastrowid

    def use_cand(self, row_id, cand_id):
        r = self._row(row_id)
        self._editable_batch(r["batch_id"])
        with self.d.tx() as c:
            if cand_id:
                cd = c.execute("SELECT text FROM inbox_cands WHERE id=? AND row_id=?", (int(cand_id), r["id"])).fetchone()
                if not cd:
                    raise DbError("후보를 찾지 못했습니다.")
                c.execute("UPDATE inbox_rows SET used_text=? WHERE id=?", (cd[0], r["id"]))
            else:
                c.execute("UPDATE inbox_rows SET used_text=NULL WHERE id=?", (r["id"],))

    # ---------- ④ 보내기 ----------
    def review(self, bid):
        v = self.view(bid)
        b = v["batch"]
        rows = [r for r in v["rows"] if r["state"] == "confirmed"]
        per = {}
        for r in rows:
            per.setdefault(r["student_no"], {"student_no": r["student_no"], "name": r["matched_name"], "count": 0})["count"] += 1
        closed = [p for p in per.values() if self.rec.is_closed(b["group_id"], b["item"], p["student_no"])]
        return {**v, "students": sorted(per.values(), key=lambda p: p["student_no"]), "closed": closed,
                "send_rows": len(rows), "excluded": v["counts"]["excluded"]}

    def send(self, bid, closed_action="block"):
        """closed_action: block(마감 학생 있으면 막음) / reopen(마감 해제하고 보냄) / exclude(마감 학생 행 제외)
        모든 검사를 쓰기 트랜잭션 안에서 다시 해 두 번 눌러도 한 번만 들어간다."""
        with self.d.tx() as c:
            b = self.batch(bid)
            if b["stage"] == "sent":
                raise DbError(f"이미 보낸 묶음입니다({b['sent_at']}). 같은 자료를 다시 보내면 기록이 중복됩니다.")
            all_rows = self._rows(bid)
            pend = [r for r in all_rows if r["state"] in ("none", "suggested")]
            if pend:
                raise DbError(f"확인이 필요한 행 {len(pend)}개가 남아 있습니다.")
            self.rec.slot(b["group_id"], b["item"])
            members = {m["student_no"]: m for m in self.d.members(b["group_id"])}
            rows = [r for r in all_rows if r["state"] == "confirmed"]
            for r in rows:
                m = members.get(r["student_no"])
                if not m or not m["active"]:
                    raise DbError(f"{r['student_no']} 학생이 명렬에 없거나 비활성입니다. 매칭을 다시 확인해 주세요.")
            closed = sorted({r["student_no"] for r in rows if self.rec.is_closed(b["group_id"], b["item"], r["student_no"])})
            if closed and closed_action == "block":
                raise DbError(f"마감된 학생 {len(closed)}명이 있습니다: " + ", ".join(f"{n} {members[n]['name']}" for n in closed))
            valid_tags = {t[0] for t in c.execute("SELECT id FROM tags")}
            tag_ids = [t for t in b["tag_ids"] if t in valid_tags]  # 지워진 태그는 빼고
            if closed and closed_action == "exclude":
                for r in rows:
                    if r["student_no"] in closed:
                        c.execute("UPDATE inbox_rows SET state='excluded', exclude_reason='마감된 학생' WHERE id=?", (r["id"],))
                rows = [r for r in rows if r["student_no"] not in closed]
            if closed and closed_action == "reopen":
                for n in closed:
                    c.execute("UPDATE finals SET closed=0, closed_at=NULL WHERE group_id=? AND item=? AND student_no=?", (b["group_id"], b["item"], n))
            if not rows:
                raise DbError("보낼 행이 없습니다.")
            seqs = {}
            for r in rows:
                sno = r["student_no"]
                if sno not in seqs:
                    seqs[sno] = c.execute("SELECT COALESCE(MAX(seq),0) FROM records WHERE group_id=? AND item=? AND student_no=? AND kind='record'",
                                          (b["group_id"], b["item"], sno)).fetchone()[0] or 0
                seqs[sno] += 1
                text = r["used_text"] if r["used_text"] is not None else r["content"]
                # 제목: 날짜·회차뿐인 머리글이면 묶음 이름, 활동명 머리글이면 그 이름
                lab = r["label"] or ""
                if not lab or r["date"] or re.fullmatch(r"\d+회", lab):
                    title = b["title"]
                else:
                    title = lab
                rid = c.execute(
                    "INSERT INTO records(group_id,item,student_no,kind,seq,date,title,content,source) VALUES(?,?,?,'record',?,?,?,?,?)",
                    (b["group_id"], b["item"], sno, seqs[sno], r["date"] or b["date"], title, text, f"inbox:{b['id']}"),
                ).lastrowid
                for tid in tag_ids:
                    c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?,?)", (rid, int(tid)))
                c.execute("UPDATE finals SET stale=1 WHERE group_id=? AND item=? AND student_no=? AND text<>''", (b["group_id"], b["item"], sno))
            n_students = len({r["student_no"] for r in rows})
            summary = f"{n_students}명 · {len(rows)}건"
            self._touch(c, bid, stage="sent", sent_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), sent_summary=summary)
        return {"students": n_students, "records": len(rows), "reopened": closed if closed_action == "reopen" else [],
                "excluded_closed": closed if closed_action == "exclude" else []}
