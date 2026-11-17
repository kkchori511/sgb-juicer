"""엑셀 전체 백업·복구(설정 › 백업, 버튼을 누를 때만). 만일을 위한 것 — 평소 백업은 backup.py(자료 파일 통째로).

저장(save): 한 학년도를 xlsx 하나로.
  - 보는 시트: 안내 · 명렬 · 항목별(자율활동/진로활동/행동특성 및 종합의견/세특_과목/동아리_이름) · AI 결과 · 태그 · 기준 자료 · 자료 인박스 · 일정 · 프롬프트
  - 숨김 복구용 시트: 자료 표마다 '_복구_표이름'(열 이름 + 값을 JSON으로), '_복구정보'(형식·버전·학년도·표별 행 수), '_복구_긴글'(엑셀 칸 한도를 넘는 글 조각)
  - only_final: 최종안·마감 결과만(항목별 시트에 학생별 최종안). 복구용 시트는 넣지 않는다(이 파일로는 복구 불가).
복구(build_db): 숨김 복구용 시트만 읽어 새 자료 파일(sqlite)을 만든다. 보는 시트를 고쳐도 복구에는 반영되지 않는다.
  실제 바꾸기는 api가 backup.restore로 한다(복원 전 자동 백업·실패 시 되돌리기 그대로).
"""
import datetime as dt
import json
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
            v = v[:CELL_MAX] + " …(잘림 — 전체는 숨김 복구용 시트에 있음)"
        c.value = v
        c.data_type = "s"
    else:
        c.value = value
    return c


def _table(ws, head, rows, widths=None, wrap=()):
    for j, h in enumerate(head, 1):
        c = _put(ws, 1, j, h)
        c.font = Font(bold=True)
        c.fill = HEAD_FILL
    for i, r in enumerate(rows, 2):
        for j, v in enumerate(r, 1):
            c = _put(ws, i, j, v)
            if j in wrap:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
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
            lines += [("복구", "설정 › 백업 › [📗 엑셀 파일로 복구]에서 이 파일로 이 학년도 자료를 되살릴 수 있습니다."),
                      ("주의", "복구는 숨김 시트(_복구_…)만 읽습니다. 보이는 시트를 엑셀에서 고쳐도 복구에는 반영되지 않습니다. 숨김 시트는 고치거나 지우지 마세요.")]
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
                listing.append((ws.title, f"{db.group_label(g)} · {prompts.ITEM_NAMES[item]}"))
                if only_final:
                    rows = []
                    for m in members:
                        f = finals.get((g["id"], item, m["student_no"]))
                        txt = f["text"] if f else ""
                        rows.append([m["student_no"], m["name"], txt, _bytes(txt), _status(f), (f or {}).get("closed_at") or "", "" if m["active"] else "비활성"])
                    _table(ws, ["학번", "이름", "최종안", "바이트", "상태", "마감 일시", "비고"], rows, [10, 10, 90, 8, 12, 18, 8], wrap=(3,))
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
                       [10, 10, 10, 6, 11, 18, 12, 12, 60, 60, 8], wrap=(9, 10))

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
            listing.append((ws.title, "기록별 변환 결과 묶음 · 분량 맞춤 후보"))
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
            listing.append((ws.title, "과목 성취기준 · 자율·진로·동아리 활동 개요"))
            rows = [[gl.get(x["group_id"], ""), "성취기준", x["text"], x["source"] or "", x["updated_at"]] for x in q("SELECT * FROM standards")]
            rows += [[gl.get(x["group_id"], ""), f"활동 개요 · {prompts.ITEM_NAMES.get(x['item'], x['item'])}", x["text"], x["source"] or "", x["updated_at"]] for x in q("SELECT * FROM outlines")]
            _table(ws, ["담당", "종류", "내용", "가져온 곳", "고친 때"], rows, [18, 22, 90, 18, 17], wrap=(3,))
            # 자료 인박스
            ws = wb.create_sheet(_sheet_name("자료 인박스", used))
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
        wb.save(path)
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
    """복구용: 자료 표를 그대로(열 이름 + 값 JSON). 너무 긴 값은 '_복구_긴글'에 조각으로."""
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    longs = []
    counts = {}
    for t in tables:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
        ws = wb.create_sheet((PREFIX + t)[:31])
        ws.sheet_state = "hidden"
        for j, c in enumerate(cols, 1):
            ws.cell(row=1, column=j, value=c).data_type = "s"
        n = 0
        for i, row in enumerate(con.execute(f"SELECT * FROM {t}"), 2):
            n += 1
            for j, v in enumerate(row, 1):
                s = json.dumps(v, ensure_ascii=False)  # 제어 문자는 \\uXXXX로, 문자열은 따옴표로 시작(수식 안 됨)
                if len(s) > CELL_MAX:
                    key = len(longs)
                    for k in range(0, len(s), CELL_MAX):
                        longs.append((key, k // CELL_MAX, s[k:k + CELL_MAX]))
                    s = json.dumps({"$long": key})
                cell = ws.cell(row=i, column=j, value=s)
                cell.data_type = "s"
        counts[t] = n
    if longs:
        ws = wb.create_sheet(LONG)
        ws.sheet_state = "hidden"
        for i, (key, part, chunk) in enumerate(longs, 1):
            ws.cell(row=i, column=1, value=key)
            ws.cell(row=i, column=2, value=part)
            ws.cell(row=i, column=3, value=chunk).data_type = "s"
    ws = wb.create_sheet(INFO)
    ws.sheet_state = "hidden"
    meta = {"format": FORMAT, "app_version": VERSION, "schema_version": db.SCHEMA_VERSION, "year": year, "created_at": made,
            "tables": {t: {"sheet": (PREFIX + t)[:31], "rows": n} for t, n in counts.items()}}
    ws.cell(row=1, column=1, value=json.dumps(meta, ensure_ascii=False)).data_type = "s"


# ---------- 복구 ----------
def read_info(path):
    """복구용 파일인지 확인하고 정보(학년도·버전·표별 행 수)를 돌려준다."""
    try:
        wb = load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        raise DbError("엑셀 파일을 열지 못했습니다. Excel에서 열려 있으면 닫고 다시 시도해 주세요.") from e
    try:
        if INFO not in wb.sheetnames:
            raise DbError("착즙기가 만든 '전체' 엑셀 백업이 아닙니다(복구 정보가 없음). '최종안·마감 결과만' 파일로는 복구할 수 없습니다.")
        v = next(wb[INFO].iter_rows(min_row=1, max_row=1, values_only=True))[0]
        info = _j(v, None)
        if not isinstance(info, dict) or info.get("format") != FORMAT:
            raise DbError("복구 정보를 읽지 못했습니다. 파일이 바뀌었을 수 있습니다.")
        if int(info.get("schema_version") or 0) > db.SCHEMA_VERSION:
            raise DbError(f"더 새 버전(v{info.get('app_version')})에서 만든 파일입니다. 앱을 업데이트한 뒤 복구하세요.")
        return info
    finally:
        wb.close()


def build_db(path, dest):
    """엑셀의 숨김 복구용 시트로 새 자료 파일을 만든다. 표별 행 수가 맞지 않으면 멈춘다."""
    info = read_info(path)
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        longs = {}
        if LONG in wb.sheetnames:
            for key, part, chunk in wb[LONG].iter_rows(values_only=True):
                longs.setdefault(int(key), {})[int(part)] = chunk or ""
        con = sqlite3.connect(dest)
        try:
            con.executescript(db.SCHEMA)
            con.execute("PRAGMA foreign_keys = OFF")
            con.execute("BEGIN")
            for t, ti in info["tables"].items():
                if not re.fullmatch(r"[a-z_]+", t):
                    raise DbError("복구 정보가 이상합니다(표 이름).")
                have = {r[1] for r in con.execute(f"PRAGMA table_info({t})")}
                if not have:
                    continue  # 앱이 모르는 표(있을 수 없지만): 건너뜀
                if ti["sheet"] not in wb.sheetnames:
                    raise DbError(f"복구용 시트가 없습니다: {ti['sheet']}")
                it = wb[ti["sheet"]].iter_rows(values_only=True)
                head = [h for h in next(it, ()) if h is not None]
                keep = [k for k, h in enumerate(head) if h in have]
                cols = [head[k] for k in keep]
                con.execute(f"DELETE FROM {t}")
                n = 0
                for row in it:
                    if row is None or all(v is None for v in row):
                        continue
                    vals = []
                    for k in keep:
                        raw = row[k] if k < len(row) else None
                        v = _j(raw, None) if isinstance(raw, str) else raw
                        if isinstance(v, dict) and "$long" in v:
                            parts = longs.get(int(v["$long"]), {})
                            v = json.loads("".join(parts[p] for p in sorted(parts)))
                        vals.append(v)
                    con.execute(f"INSERT INTO {t}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", vals)
                    n += 1
                if n != int(ti["rows"]):
                    raise DbError(f"'{t}' 자료 수가 맞지 않습니다(파일 {ti['rows']}건, 읽은 것 {n}건). 숨김 시트가 바뀌었을 수 있습니다.")
            con.execute("COMMIT")
            bad = con.execute("PRAGMA integrity_check").fetchone()[0]
            if bad != "ok":
                raise DbError(f"만든 자료 파일 점검에 실패했습니다: {bad}")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            con.close()
    finally:
        wb.close()
    return info
