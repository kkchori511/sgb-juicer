"""엑셀 전체 백업·복구(설정 › 백업, 버튼을 누를 때만). 만일을 위한 것 — 평소 백업은 backup.py(자료 파일 통째로).

저장(save): 한 학년도를 xlsx 하나로.
  - 보는 시트: 안내 · 명렬 · 항목별(자율활동/진로활동/행동특성 및 종합의견/세특_과목/동아리_이름) · AI 결과 · 태그 · 기준 자료 · 자료 Inbox · 일정 · 프롬프트
  - 숨김 복구용 시트: 자료 표마다 '_복구_표이름'(열 이름 + 값을 JSON으로), '_복구정보'(형식·버전·학년도·표별 행 수), '_복구_긴글'(엑셀 칸 한도를 넘는 글 조각)
  - only_final: 최종안·마감 결과만(항목별 시트에 학생별 최종안). 복구용 시트는 넣지 않는다(이 파일로는 복구 불가).
복구(build_db): 숨김 복구용 시트만 읽어 새 자료 파일(sqlite)을 만든다. 보는 시트를 고쳐도 복구에는 반영되지 않는다.
  실제 바꾸기는 api가 backup.restore로 한다(복원 전 자동 백업·실패 시 되돌리기 그대로).
"""
import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import VERSION, config, db, prompts
from .db import DbError
from .textutil import count_bytes

FORMAT = "SGB-XLSX-BACKUP-1"
INFO = "_복구정보"
LONG = "_복구_긴글"
PREFIX = "_복구_"
CELL_MAX = 32000            # 엑셀 칸 한도(32,767자)보다 조금 작게
ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
HEAD_FILL = PatternFill("solid", fgColor="DDE7F5")
ITEMS_OF = {"homeroom": ("autonomy", "career", "behavior"), "subject": ("subject",), "club": ("club",)}


# ---------- 공통 ----------
def _put(ws, row, col, value):
    """보는 시트 칸 쓰기: 엑셀이 못 받는 글자는 빼고, '='로 시작해도 수식이 되지 않게, 너무 길면 자른다."""
    c = ws.cell(row=row, column=col)
    if isinstance(value, str):
        v = ILLEGAL.sub("", value)
        if len(v) > CELL_MAX:
            v = v[:CELL_MAX] + " …(잘림 — 전체는 숨김 복구용 시트에 있음)"  # 전체 저장의 보는 시트에만 씀(최종안만은 줄을 나눠 자르지 않음)
        c.value = v
        c.data_type = "s"
    else:
        c.value = value
    return c


def _table(ws, head, rows, widths=None, wrap=(), freeze="A2"):
    for j, h in enumerate(head, 1):
        c = _put(ws, 1, j, h)
        c.font = Font(bold=True)
        c.fill = HEAD_FILL
    for i, r in enumerate(rows, 2):
        for j, v in enumerate(r, 1):
            c = _put(ws, i, j, v)
            if j in wrap:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = freeze  # 항목 시트는 C2(학번·이름 열과 첫 줄 고정)
    for j, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(j)].width = w


def _sheet_name(name, used):
    """엑셀 시트 이름: 31자, \\ / ? * [ ] : 빼기, 겹치면 (2)."""
    base = re.sub(r"[\\/?*\[\]:]", "", name).strip() or "시트"
    base = base[:31]
    n, out = 2, base
    while out.lower() in used:
        tail = f"({n})"
        out = base[: 31 - len(tail)] + tail
        n += 1
    used.add(out.lower())
    return out


def _snapshot(year):
    """열린 연결과 같은 시점의 사본(읽는 동안 앱이 써도 섞이지 않게)."""
    tmp = Path(tempfile.mkdtemp(prefix="sgb-xlsx-")) / "snap.sqlite"
    db.open_year(year).backup_to(tmp)
    con = sqlite3.connect(tmp)
    con.row_factory = sqlite3.Row
    return con, tmp


def _j(text, default):
    try:
        return json.loads(text) if text else default
    except ValueError:
        return default


def _status(f):
    if not f:
        return "최종안 없음"
    return "마감" if f["closed"] else "최종안 있음"


# ---------- 저장 ----------
def save(year, path, only_final=False):
    year = int(year)
    if year not in db.list_years():
        raise DbError("그 학년도 자료가 없습니다.")
    con, tmp = _snapshot(year)
    try:
        wb = Workbook()
        wb.remove(wb.active)
        used = set()
        q = lambda sql, a=(): [dict(r) for r in con.execute(sql, a).fetchall()]  # noqa: E731
        groups = q("SELECT * FROM groups ORDER BY sort_order, id")
        students = {s["student_no"]: s for s in q("SELECT * FROM students")}
        tags = {t["id"]: t for t in q("SELECT * FROM tags ORDER BY sort_order, name")}
        rtag = {}
        for x in q("SELECT record_id, tag_id FROM record_tags"):
            rtag.setdefault(x["record_id"], []).append(tags.get(x["tag_id"], {}).get("name", ""))
        finals = {(f["group_id"], f["item"], f["student_no"]): f for f in q("SELECT * FROM finals")}
        made = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

        # 안내
        ws = wb.create_sheet(_sheet_name("안내", used))
        lines = [("생기부 착즙기 엑셀 백업", ""), ("학년도", f"{year}학년도"), ("만든 때", made), ("앱 버전", f"v{VERSION}"),
                 ("종류", "최종안·마감 결과만" if only_final else "전체(모든 항목의 모든 내용)"), ("", "")]
        if only_final:
            lines += [("복구", "이 파일은 최종안·마감 결과만 담아 엑셀로 복구할 수 없습니다. 복구하려면 '전체'로 저장하세요.")]
        else:
            lines += [("복구", "설정 › 백업 › [엑셀 파일로 복구]에서 이 파일로 이 학년도 자료를 되살릴 수 있습니다."),
                      ("주의", "복구는 숨김 시트(_복구_…)만 읽습니다. 보이는 시트를 엑셀에서 고쳐도 복구에는 반영되지 않습니다. 숨김 시트가 조금이라도 바뀌면(지문 확인) 복구를 멈춥니다."),
                      ("보기 시트 밖", "태그 AI 변환 작업·시험 후보·반영 이력, Inbox 정제 후보, 기록 순서·내부 번호 등은 보이는 시트에는 없고 숨김 시트에만 있습니다(복구하면 모두 돌아옴)."),
                      ("들어 있지 않은 것", "스캔 PDF 원본과 설정(API 키·모델·프롬프트 목록 저장본)은 들어 있지 않습니다. 프롬프트 시트는 보기용입니다.")]
        lines += [("", ""), ("시트", "내용")]
        info_row = len(lines) + 1
        for i, (a, b) in enumerate(lines, 1):
            _put(ws, i, 1, a).font = Font(bold=bool(a) and i in (1, len(lines)))
            _put(ws, i, 2, b)
        ws.column_dimensions["A"].width = 16
        ws.column_dimensions["B"].width = 110
        listing = []

        # 항목별 시트
        homerooms = [g for g in groups if g["kind"] == "homeroom"]
        for g in groups:
            members = q("SELECT m.*, s.name, s.grade, s.class_no, s.number FROM memberships m JOIN students s USING(student_no) "
                        "WHERE m.group_id=? ORDER BY s.grade, s.class_no, s.number, m.student_no", (g["id"],))
            for item in ITEMS_OF[g["kind"]]:
                if g["kind"] == "homeroom":
                    nm = prompts.ITEM_NAMES[item] + (f"_{g['grade']}-{g['class_no']}" if len(homerooms) > 1 else "")
                elif g["kind"] == "subject":
                    nm = f"세특_{g['name']}({g['semester']}학기)"
                else:
                    nm = f"동아리_{g['name']}"
                ws = wb.create_sheet(_sheet_name(nm, used))
                listing.append((ws.title, f"{db.group_label(g)} / {prompts.ITEM_NAMES[item]}"))
                if only_final:
                    rows = []
                    for m in members:
                        f = finals.get((g["id"], item, m["student_no"]))
                        txt = f["text"] if f else ""
                        parts = [txt[k:k + CELL_MAX] for k in range(0, len(txt), CELL_MAX)] or [""]  # 칸 한도를 넘으면 다음 줄에 이어서(자르지 않음)
                        rows.append([m["student_no"], m["name"], parts[0], _bytes(txt), _status(f), (f or {}).get("closed_at") or "", "" if m["active"] else "비활성"])
                        rows += [[m["student_no"], m["name"], p, "", f"(앞 줄에 이어서 {k + 2})", "", ""] for k, p in enumerate(parts[1:])]
                    _table(ws, ["학번", "이름", "최종안", "바이트", "상태", "마감 일시", "비고"], rows, [10, 10, 90, 8, 12, 18, 8], wrap=(3,), freeze="C2")
                    continue
                recs = q("SELECT * FROM records WHERE group_id=? AND item=? ORDER BY student_no, pos IS NULL, pos, kind='record', COALESCE(seq,0), id", (g["id"], item))
                by = {}
                for r in recs:
                    by.setdefault(r["student_no"], []).append(r)
                rows = []
                for m in members:
                    f = finals.get((g["id"], item, m["student_no"]))
                    rows.append([m["student_no"], m["name"], "최종안", "", "", "", "", _status(f), "", f["text"] if f else "", _bytes(f["text"]) if f else 0])
                    for r in by.get(m["student_no"], []):
                        orig = r["original"] if r["original"] is not None else r["content"]
                        rows.append([m["student_no"], m["name"], "기존 완성문" if r["kind"] == "existing" else "기록", r["seq"] or "", r["date"] or "",
                                     r["title"] or "", "·".join(rtag.get(r["id"], [])), "확정" if r["confirmed"] else "미확정",
                                     orig, r["content"] if r["confirmed"] else "", _bytes(r["content"])])
                _table(ws, ["학번", "이름", "구분", "회차", "날짜", "활동명", "태그", "상태", "원문", "확정본·최종안", "바이트"], rows,
                       [10, 10, 10, 6, 11, 18, 12, 12, 60, 60, 8], wrap=(9, 10), freeze="C2")

        if not only_final:
            # 명렬
            ws = wb.create_sheet(_sheet_name("명렬", used))
            listing.append((ws.title, "담당별 학생"))
            rows = []
            for g in groups:
                for m in q("SELECT m.*, s.name, s.grade, s.class_no, s.number FROM memberships m JOIN students s USING(student_no) "
                           "WHERE m.group_id=? ORDER BY s.grade, s.class_no, s.number", (g["id"],)):
                    rows.append([db.group_label(g), m["grade"], m["class_no"], m["number"], m["student_no"], m["name"],
                                 "활성" if m["active"] else "비활성", m["section"] or "", m["level"] or ""])
            _table(ws, ["담당", "학년", "반", "번호", "학번", "이름", "상태", "수업", "성취수준"], rows, [20, 6, 6, 6, 10, 10, 8, 12, 8])
            # AI 결과
            ws = wb.create_sheet(_sheet_name("AI 결과", used))
            listing.append((ws.title, "기록별 변환 결과 묶음 / 분량 맞춤 후보"))
            gl = {g["id"]: db.group_label(g) for g in groups}
            rows = [[gl.get(x["group_id"], ""), prompts.ITEM_NAMES.get(x["item"], x["item"]), x["student_no"], students.get(x["student_no"], {}).get("name", ""),
                     "기록 결과" if x["record_id"] else "분량 맞춤 후보", x["record_id"] or "", prompts.OP_NAMES.get(x["op"], x["op"]), x["text"],
                     "잠금" if x["locked"] else "", x["created_at"]] for x in q("SELECT * FROM results ORDER BY group_id, item, student_no, id")]
            _table(ws, ["담당", "항목", "학번", "이름", "종류", "기록 번호", "작업", "글", "잠금", "만든 때"], rows, [18, 14, 10, 10, 14, 8, 10, 80, 6, 17], wrap=(8,))
            # 태그
            ws = wb.create_sheet(_sheet_name("태그", used))
            listing.append((ws.title, "태그 이름·기록 수"))
            cnt = {}
            for x in q("SELECT tag_id, COUNT(*) n FROM record_tags GROUP BY tag_id"):
                cnt[x["tag_id"]] = x["n"]
            _table(ws, ["순서", "태그", "기록 수"], [[t["sort_order"], t["name"], cnt.get(t["id"], 0)] for t in tags.values()], [6, 24, 8])
            # 기준 자료
            ws = wb.create_sheet(_sheet_name("성취기준·활동 개요", used))
            listing.append((ws.title, "과목 성취기준 / 자율·진로·동아리 활동 개요"))
            rows = [[gl.get(x["group_id"], ""), "성취기준", x["text"], x["source"] or "", x["updated_at"]] for x in q("SELECT * FROM standards")]
            rows += [[gl.get(x["group_id"], ""), f"활동 개요 / {prompts.ITEM_NAMES.get(x['item'], x['item'])}", x["text"], x["source"] or "", x["updated_at"]] for x in q("SELECT * FROM outlines")]
            _table(ws, ["담당", "종류", "내용", "가져온 곳", "고친 때"], rows, [18, 22, 90, 18, 17], wrap=(3,))
            # 자료 Inbox
            ws = wb.create_sheet(_sheet_name("자료 Inbox", used))
            listing.append((ws.title, "묶음과 행(보낸 것·안 보낸 것)"))
            bt = {b["id"]: b for b in q("SELECT * FROM inbox_batches")}
            rows = [[bt.get(x["batch_id"], {}).get("title", ""), x["ord"], x["source_ref"] or "", x["ext_no"] or "", x["ext_name"] or "", x["student_no"] or "",
                     x["state"], x["label"] or "", x["date"] or "", x["content"], x["used_text"] if x["used_text"] is not None else ""]
                    for x in q("SELECT * FROM inbox_rows ORDER BY batch_id, ord")]
            _table(ws, ["묶음", "순서", "원본 위치", "원본 학번", "원본 이름", "연결 학번", "상태", "활동명", "날짜", "원문", "보낼 내용"], rows,
                   [20, 6, 10, 10, 10, 10, 10, 16, 11, 60, 60], wrap=(10, 11))
            # 일정
            ws = wb.create_sheet(_sheet_name("일정", used))
            listing.append((ws.title, "일정"))
            _table(ws, ["날짜", "일정"], [[x["date"], x["title"]] for x in q("SELECT * FROM schedules ORDER BY date")], [12, 50])
            # 프롬프트(설정 파일 — 복구 대상 아님, 보기용)
            ws = wb.create_sheet(_sheet_name("프롬프트", used))
            listing.append((ws.title, "프롬프트 목록(보기용 — 엑셀 복구는 학년도 자료만 되살림)"))
            lib, _ = prompts.build_library(config.load().get("prompt_lib"), config.load().get("prompts"))
            _table(ws, ["이름", "기본", "만든 방식", "프롬프트", "예시"], [[p["name"], "기본" if p["builtin"] else "", p.get("made") or "", p["prompt"], p["example"]] for p in lib],
                   [24, 6, 10, 90, 40], wrap=(4, 5))
            _write_hidden(wb, con, year, made)
        # 안내 시트에 시트 목록
        for i, (a, b) in enumerate(listing, info_row):
            _put(ws_info(wb), i, 1, a)
            _put(ws_info(wb), i, 2, b)
        # 같은 폴더의 임시 파일에 다 쓴 뒤 바꿔 넣는다(실패해도 원래 있던 파일은 그대로)
        dest = Path(path)
        part = dest.with_name(f".{dest.stem}.작성중{os.getpid()}.xlsx")
        try:
            wb.save(part)
            wb.close()
            load_workbook(part, read_only=True).close()  # 다 쓴 파일이 열리는지 확인
            os.replace(part, dest)
        except BaseException:
            try:
                part.unlink()
            except OSError:
                pass
            raise
    finally:
        con.close()
        try:
            tmp.unlink()
            tmp.parent.rmdir()
        except OSError:
            pass
    return {"path": str(path)}


def ws_info(wb):
    return wb.worksheets[0]


def _bytes(t):
    return count_bytes(t or "")


def _write_hidden(wb, con, year, made):
    """복구용: 자료 표를 그대로(열 이름 + 값 JSON). 너무 긴 값은 '_복구_긴글'에 조각으로.
    표마다 행 수·지문(SHA-256), 긴 글마다 조각 수·길이·지문, 번호 자동 표의 '지금까지 쓴 가장 큰 번호'(sqlite_sequence)를 함께 남긴다."""
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    longs, long_info = [], {}
    tinfo = {}
    for t in tables:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        ws = wb.create_sheet((PREFIX + t)[:31])
        ws.sheet_state = "hidden"
        for j, c in enumerate(cols, 1):
            ws.cell(row=1, column=j, value=c).data_type = "s"
        h = hashlib.sha256("\x1f".join(cols).encode())
        n = 0
        for i, row in enumerate(con.execute(f"SELECT * FROM {t}"), 2):
            n += 1
            for j, v in enumerate(row, 1):
                s = json.dumps(v, ensure_ascii=False)  # 제어 문자는 \\uXXXX로, 문자열은 따옴표로 시작(수식 안 됨)
                if len(s) > CELL_MAX:
                    key = len(long_info)
                    parts = [s[k:k + CELL_MAX] for k in range(0, len(s), CELL_MAX)]
                    longs += [(key, k, p) for k, p in enumerate(parts)]
                    long_info[str(key)] = {"parts": len(parts), "len": len(s), "sha": hashlib.sha256(s.encode()).hexdigest()}
                    s = json.dumps({"$long": key})
                h.update(b"\x1e" + s.encode())  # 칸에 실제로 쓴 글로 지문(긴 글은 조각 지문을 따로)
                cell = ws.cell(row=i, column=j, value=s)
                cell.data_type = "s"
        tinfo[t] = {"sheet": (PREFIX + t)[:31], "rows": n, "cols": cols, "sha": h.hexdigest()}
    if longs:
        ws = wb.create_sheet(LONG)
        ws.sheet_state = "hidden"
        for i, (key, part, chunk) in enumerate(longs, 1):
            ws.cell(row=i, column=1, value=key)
            ws.cell(row=i, column=2, value=part)
            ws.cell(row=i, column=3, value=chunk).data_type = "s"
    seqs = {r[0]: r[1] for r in con.execute("SELECT name, seq FROM sqlite_sequence")} if con.execute(
        "SELECT 1 FROM sqlite_master WHERE name='sqlite_sequence'").fetchone() else {}
    ws = wb.create_sheet(INFO)
    ws.sheet_state = "hidden"
    meta = {"format": FORMAT, "app_version": VERSION, "schema_version": db.SCHEMA_VERSION, "year": year, "created_at": made,
            "tables": tinfo, "longs": long_info, "sequences": seqs}
    text = json.dumps(meta, ensure_ascii=False)
    for k in range(0, len(text), CELL_MAX):  # 정보가 길면 여러 줄에
        ws.cell(row=k // CELL_MAX + 1, column=1, value=text[k:k + CELL_MAX]).data_type = "s"


# ---------- 복구 ----------
class _Bad(DbError):
    pass


def _fresh_schema():
    """지금 앱의 표·열(복구할 때 모르는 표·열이 있으면 멈추고, 빠진 필수 표·열도 멈춘다)."""
    con = sqlite3.connect(":memory:")
    try:
        con.executescript(db.SCHEMA)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        cols = {t: [r[1] for r in con.execute(f"PRAGMA table_info({t})")] for t in tables}
        auto = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql LIKE '%AUTOINCREMENT%'")}
        return cols, auto
    finally:
        con.close()


def read_info(path):
    """복구용 파일인지 확인하고 정보(학년도·버전·표별 행 수·지문)를 돌려준다."""
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        raise DbError("엑셀 파일을 열지 못했습니다. Excel에서 열려 있으면 닫고 다시 시도해 주세요.") from e
    try:
        if INFO not in wb.sheetnames:
            raise DbError("착즙기가 만든 '전체' 엑셀 백업이 아닙니다(복구 정보가 없음). '최종안·마감 결과만' 파일로는 복구할 수 없습니다.")
        text = "".join(str(r[0] or "") for r in wb[INFO].iter_rows(values_only=True))
        try:
            info = json.loads(text)
        except ValueError:
            info = None
        if not isinstance(info, dict) or info.get("format") != FORMAT or not isinstance(info.get("tables"), dict):
            raise DbError("복구 정보를 읽지 못했습니다. 파일이 바뀌었을 수 있습니다.")
        ver = int(info.get("schema_version") or 0)
        if ver > db.SCHEMA_VERSION:
            raise DbError(f"더 새 버전(v{info.get('app_version')})에서 만든 파일입니다. 앱을 업데이트한 뒤 복구하세요.")
        if ver < 14:
            raise DbError("이 앱이 만든 엑셀 백업 형식이 아닙니다(자료 형식 번호가 맞지 않음).")
        return info
    finally:
        wb.close()


def _decode(raw, where):
    """복구용 칸 값: 반드시 JSON 글이어야 한다(빈 칸·깨진 값은 거절 — 조용히 빈 값으로 바꾸지 않음)."""
    if not isinstance(raw, str):
        raise _Bad(f"{where}: 값이 비었거나 형식이 다릅니다.")
    try:
        return json.loads(raw)
    except ValueError:
        raise _Bad(f"{where}: 값을 읽지 못했습니다.")


def build_db(path, dest):
    """엑셀의 숨김 복구용 시트로 새 자료 파일을 만든다. 표·열·행 수·지문·긴 글 조각·참조를 모두 확인하고, 하나라도 다르면 멈춘다."""
    info = read_info(path)
    known, auto = _fresh_schema()
    tables = info["tables"]
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        unknown = [t for t in tables if t not in known]
        if unknown:
            raise _Bad(f"이 앱이 모르는 자료 표가 있습니다: {', '.join(unknown[:3])}")
        missing = [t for t in known if t not in tables]
        if missing:  # 엑셀 백업은 v14부터 있어 그때의 표는 모두 있어야 한다(뒤 버전에서 새로 생긴 표만 없을 수 있음)
            raise _Bad(f"복구용 자료 표가 빠졌습니다: {', '.join(missing[:3])}")
        longs = {}
        if LONG in wb.sheetnames:
            for key, part, chunk in wb[LONG].iter_rows(values_only=True):
                if key is None:
                    continue
                d = longs.setdefault(int(key), {})
                if int(part) in d:
                    raise _Bad("긴 글 조각이 겹칩니다.")
                d[int(part)] = chunk if isinstance(chunk, str) else ""
        linfo = info.get("longs") or {}
        if set(map(int, linfo)) != set(longs):
            raise _Bad("긴 글 조각 목록이 맞지 않습니다.")
        joined = {}
        for k, li in linfo.items():
            parts = longs[int(k)]
            if sorted(parts) != list(range(int(li["parts"]))):
                raise _Bad("긴 글 조각이 빠졌거나 순서가 맞지 않습니다.")
            s = "".join(parts[p] for p in range(int(li["parts"])))
            if len(s) != int(li["len"]) or hashlib.sha256(s.encode()).hexdigest() != li["sha"]:
                raise _Bad("긴 글 조각 내용이 바뀌었습니다.")
            joined[int(k)] = s
        con = sqlite3.connect(dest)
        try:
            con.executescript(db.SCHEMA)
            con.execute("PRAGMA foreign_keys = OFF")
            con.execute("BEGIN")
            for t, ti in tables.items():
                if ti.get("sheet") not in wb.sheetnames:
                    raise _Bad(f"복구용 시트가 없습니다: {ti.get('sheet')}")
                it = wb[ti["sheet"]].iter_rows(values_only=True)
                head = list(next(it, ()))
                while head and head[-1] is None:
                    head.pop()
                if head != ti.get("cols") or len(set(head)) != len(head) or any(not isinstance(h, str) or not h for h in head):
                    raise _Bad(f"'{t}' 열 이름이 저장 때와 다릅니다.")
                bad = [h for h in head if h not in known[t]]
                if bad:
                    raise _Bad(f"'{t}'에 이 앱이 모르는 열이 있습니다: {bad[0]}")
                h = hashlib.sha256("\x1f".join(head).encode())
                n = 0
                sql = f"INSERT INTO {t}({','.join(head)}) VALUES({','.join('?' * len(head))})"
                for ri, row in enumerate(it, 2):
                    if row is None or all(v is None for v in row):
                        continue
                    vals = []
                    for k in range(len(head)):
                        raw = row[k] if k < len(row) else None
                        h.update(b"\x1e" + (raw.encode() if isinstance(raw, str) else b"\x00"))
                        v = _decode(raw, f"'{t}' {ri}행 {head[k]}")
                        if isinstance(v, dict):
                            if set(v) != {"$long"} or int(v["$long"]) not in joined:
                                raise _Bad(f"'{t}' {ri}행 {head[k]}: 긴 글 참조가 이상합니다.")
                            v = _decode(joined[int(v["$long"])], f"'{t}' {ri}행 {head[k]}")
                        vals.append(v)
                    con.execute(sql, vals)
                    n += 1
                if n != int(ti["rows"]):
                    raise _Bad(f"'{t}' 자료 수가 맞지 않습니다(파일 {ti['rows']}건, 읽은 것 {n}건).")
                if h.hexdigest() != ti.get("sha"):
                    raise _Bad(f"'{t}' 자료 내용이 저장 때와 다릅니다.")
            # 번호 자동 표: 지금까지 쓴 가장 큰 번호를 되살린다(지운 번호를 새 기록이 다시 쓰지 않게)
            for name, seq in (info.get("sequences") or {}).items():
                if name in auto and isinstance(seq, int):
                    cur = con.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (name,)).fetchone()
                    if cur is None:
                        con.execute("INSERT INTO sqlite_sequence(name, seq) VALUES(?, ?)", (name, seq))
                    elif cur[0] < seq:
                        con.execute("UPDATE sqlite_sequence SET seq=? WHERE name=?", (seq, name))
            con.execute("COMMIT")
            fk = con.execute("PRAGMA foreign_key_check").fetchall()
            if fk:
                raise _Bad(f"자료끼리 이어지는 번호가 맞지 않습니다({fk[0][0]} 표 등 {len(fk)}건).")
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            if ok != "ok":
                raise DbError(f"만든 자료 파일 점검에 실패했습니다: {ok}")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()
    except _Bad as e:
        raise DbError(f"복구를 멈췄습니다 — 숨김 복구용 시트가 저장 때와 다릅니다. 지금 자료는 그대로입니다. ({e})") from None
    finally:
        wb.close()
    return info
