"""화면(JS)에서 window.pywebview.api.* 로 부르는 함수들.

모든 함수는 {"ok": True, ...} 또는 {"ok": False, "error": "..."}를 돌려준다.
오래 걸리는 작업은 스레드로 돌리고 진행은 window.onAppEvent(...)로 보낸다.
"""
import datetime as dt
import json
import os
import platform
import subprocess
import threading
import webbrowser
from contextlib import contextmanager
from functools import wraps

import webview

from . import APP_NAME, MAKER, TAGLINE, VERSION, backup, config, db, existing, export, ocr, openrouter, prompts, roster, scan, stdformat, updater, weights
from .records import Records, items_of
from .inbox import Inbox
from .standards import Outlines, Standards, avoid_rule, new_words, outline_tidy_prompt, check_level, outline_rule, read_hwpx_text, read_pdf_text, similarity, standards_rule
from .paths import data_dir
from .textutil import count_bytes


def _read_clipboard() -> str:
    system = platform.system()
    if system == "Darwin":
        return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
    if system == "Windows":
        import ctypes
        from ctypes import wintypes

        CF_UNICODETEXT = 13
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        user32.GetClipboardData.restype = wintypes.HANDLE
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        if not user32.OpenClipboard(None):
            return ""
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return ""
            ptr = kernel32.GlobalLock(handle)
            try:
                return ctypes.wstring_at(ptr) if ptr else ""
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()
    return ""


def safe(fn):
    """예상한 오류는 화면에 보여 줄 문장으로 바꾼다."""

    @wraps(fn)
    def inner(*a, **kw):
        try:
            out = fn(*a, **kw)
            if isinstance(out, dict) and "ok" in out:
                return out
            return {"ok": True, **(out if isinstance(out, dict) else {"value": out})}
        except (db.DbError, updater.UpdateError, openrouter.LlmError, weights.WeightError) as e:
            out = {"ok": False, "error": str(e)}
            if getattr(e, "code", None):
                out["code"] = e.code
            return out
        except Exception as e:  # 알 수 없는 오류도 앱을 멈추지 않게
            return {"ok": False, "error": f"처리하지 못했습니다: {e.__class__.__name__}: {e}"}

    return inner


class Api:
    def __init__(self):
        self._window = None
        self._busy = threading.Lock()
        self._update_info = None
        self._xlsx_paths = {}  # 시트 고르기 대기: 표시값 → 고른 파일 경로(파일 창을 다시 띄우지 않으려고)
        self._run_cost = 0.0
        self._ai_keys = set()
        self._ai_extra = ""  # 이번 실행에만 쓰는 추가 요구 사항(ai_extra_set)
        self._ai_lock = threading.Lock()
        self._ocr_stop = threading.Event()
        self._jobs = 0  # 화면에서 진행 중인 일괄 작업(일괄 종합·인박스 정제 등)
        self._maint = ""  # 진행 중인 관리 작업(복원·학년도 전환·업데이트 등). 이때는 새 작업·쓰기를 막는다
        self._halted = ""  # 실행 잠금을 잃은 경우: 더 쓰지 않고 다시 켜 달라고 안내
        self._close_ok = False
        self._close_asked = 0.0
        self._last_undo = None

    def attach(self, window):
        self._window = window

    def _emit(self, payload: dict):
        if self._window:
            self._window.evaluate_js(f"window.onAppEvent({json.dumps(payload, ensure_ascii=False)})")

    def _check_running(self):
        """관리 작업 중이거나 실행 잠금을 잃었으면 새 작업·쓰기를 막는다(_ai_lock 안에서 부름)."""
        if self._halted:
            raise db.DbError(self._halted)
        if self._maint:
            raise db.DbError(f"{self._maint} 중입니다. 끝난 뒤 다시 해 주세요.")

    def _maint_begin(self, what, take_busy=False):
        """관리 작업 시작: AI·OCR·일괄 작업과 서로 막는다(한 잠금 안에서 확인하고 예약)."""
        with self._ai_lock:
            self._check_running()
            if self._ai_keys or self._jobs > 0 or self._busy.locked():
                raise db.DbError(f"AI·OCR 작업이 진행 중이라 {what}할 수 없습니다. 작업이 끝난 뒤 다시 해 주세요.")
            if take_busy and not self._busy.acquire(blocking=False):
                raise db.DbError("다른 작업이 진행 중입니다.")
            self._maint = what

    def _maint_end(self, take_busy=False):
        with self._ai_lock:
            self._maint = ""
            if take_busy:
                self._busy.release()

    @contextmanager
    def _maintenance(self, what, take_busy=False):
        self._maint_begin(what, take_busy)
        try:
            yield
        finally:
            self._maint_end(take_busy)

    def _require_idle(self, what):
        with self._ai_lock:
            self._check_running()
            if self._ai_keys or self._jobs > 0 or self._busy.locked():
                raise db.DbError(f"AI·OCR 작업이 진행 중이라 {what}할 수 없습니다. 작업이 끝난 뒤 다시 해 주세요.")

    def job_begin(self, name=""):
        with self._ai_lock:
            if self._halted or self._maint:
                return {"ok": False, "error": self._halted or f"{self._maint} 중입니다. 끝난 뒤 다시 해 주세요."}
            self._jobs += 1
        return {"ok": True}

    def job_end(self, name=""):
        with self._ai_lock:
            self._jobs = max(0, self._jobs - 1)
        return {"ok": True}

    def _db(self) -> db.YearDb:
        year = config.load()["current_year"]
        if not year:
            raise db.DbError("학년도를 먼저 정해 주세요.")
        return db.open_year(year)

    # ---------- 앱 ----------
    def app_info(self):
        return {
            "name": APP_NAME,
            "version": VERSION,
            "maker": MAKER,
            "tagline": TAGLINE,
            "data_dir": str(data_dir()),
            "config_path": str(config.config_path()),
            "today": dt.date.today().isoformat(),
        }

    @safe
    def startup(self):
        """화면이 뜬 직후 한 번: 하루 1회 자동 백업, 업데이트 확인(백그라운드)."""
        cfg = config.load()
        if cfg["current_year"] and db.year_path(cfg["current_year"]).exists():
            try:
                config.save({"last_backup": backup.daily(cfg.get("last_backup", ""))})
            except Exception:
                pass
        threading.Thread(target=self._check_update, daemon=True).start()
        threading.Thread(target=updater.cleanup_leftovers, daemon=True).start()
        try:
            def owner_of(n):
                return [y for y in db.list_years()
                        if db.open_year(y).q("SELECT 1 FROM inbox_batches WHERE id=? AND source='scan'", (n,))]
            moved = scan.migrate_flat(owner_of)
            if moved:
                updater.log("스캔 원본 정리: " + ", ".join(moved))
        except Exception:
            pass
        return {}

    def _check_update(self):
        info = updater.check()
        if info.get("ok") and info.get("available"):
            self._update_info = info
            self._emit({"type": "update_available", **{k: info[k] for k in ("version", "notes", "can_apply")}})

    def guide_html(self):
        from .paths import web_dir

        return (web_dir() / "guide.html").read_text(encoding="utf-8")

    @safe
    def load_config(self):
        return {"config": config.load()}

    @safe
    def save_config(self, patch):
        config.save(patch or {})
        return {}

    @safe
    def reset_keys(self):
        config.reset_keys()
        return {}

    def open_url(self, url):
        if isinstance(url, str) and url.startswith("https://"):
            webbrowser.open(url)
        return {"ok": True}

    @safe
    def read_clipboard(self):
        return {"text": _read_clipboard()}

    @safe
    def check_key(self, key=None):
        k = key if key is not None else config.load()["openrouter_key"]
        return openrouter.check_key(k)

    @safe
    def balance(self):
        return {"balance": openrouter.balance(config.load()["openrouter_key"])}

    @safe
    def model_info(self, model_id):
        return openrouter.model_info(model_id)

    def count_bytes(self, text):
        return count_bytes(text)

    # ---------- 학년도 ----------
    @safe
    def year_state(self):
        cfg = config.load()
        year = cfg["current_year"]
        years = db.list_years()
        if not year or year not in years:
            return {"year": 0, "years": years}
        d = db.open_year(year)
        latest = max(years)
        return {
            "year": year,
            "years": years,
            "archived": year < latest,
            "role": d.role(),
            "groups": d.groups(),
            "schedules": d.schedules(),
            "targets": d.targets(),
        }

    @safe
    def create_year(self, year, role):
        year = int(year)
        if not 2000 <= year <= 2100:
            raise db.DbError("학년도를 확인해 주세요.")
        years = db.list_years()
        if year in years and year < max(years):
            raise db.DbError("보관 학년도는 바꿀 수 없습니다.")
        if year in years:
            self._editable()
            db.open_year(year).set_role(role)
            config.save({"current_year": year})
            return {}
        with self._maintenance("새 학년도 만들기"):
            self._last_undo = None
            d = db.open_year(year)
            d.set_role(role)
            config.save({"current_year": year})
        return {}

    @safe
    def switch_year(self, year):
        year = int(year)
        with self._maintenance("학년도 전환"):
            self._last_undo = None
            if year not in db.list_years():
                raise db.DbError("그 학년도 자료가 없습니다.")
            config.save({"current_year": year})
        return {}

    @safe
    def role_change_preview(self, role):
        d = self._db()
        if role == d.role():
            return {"message": ""}
        if role == "subject":
            hr = [g for g in d.groups() if g["kind"] == "homeroom"]
            if hr:
                g = hr[0]
                return {"message": f"비담임으로 바꾸면 {g['name']} 담임반(학생 {g['total']}명)과 담임 항목이 화면에서 숨겨집니다. 자료는 지우지 않으며, 다시 담임으로 바꾸면 그대로 보입니다."}
            return {"message": "비담임으로 바꾸면 담임 항목(자율·진로·행특)이 숨겨집니다."}
        return {"message": "담임으로 바꾸면 담임 항목(자율·진로·행특)이 나타납니다. 담임반이 없으면 명렬·담당 관리에서 추가해 주세요."}

    @safe
    def set_role(self, role):
        self._editable()
        self._db().set_role(role)
        return {}

    @safe
    def finish_setup(self):
        config.save({"setup_done": True})
        return {}

    # ---------- 담당 ----------
    @safe
    def add_group(self, data):
        self._editable()
        d = self._db()
        gid = d.add_group(
            data.get("kind"), data.get("name"), data.get("semester"), data.get("grade"), data.get("class_no"), data.get("level_scale", 5)
        )
        return {"id": gid, "groups": d.groups()}

    @safe
    def update_group(self, gid, data):
        self._editable()
        d = self._db()
        unpaired = d.update_group(gid, **(data or {}))
        return {"groups": d.groups(), "unpaired": unpaired or 0}

    @safe
    def group_impact(self, gid):
        return self._db().group_impact(gid)

    @safe
    def delete_group(self, gid):
        self._editable()
        with self._maintenance("담당 삭제"):
            d = self._db()
            bids = [r["id"] for r in d.q("SELECT id FROM inbox_batches WHERE group_id=?", (int(gid),))]
            name = backup.make("담당삭제전")
            d.delete_group(gid)
            for b in bids:
                p = scan.pdf_path(d.year, b)
                if p.exists():
                    p.unlink()
            self._last_undo = None
        return {"groups": d.groups(), "backup": name}

    # ---------- 명렬 ----------
    @safe
    def roster_from_text(self, text):
        rows = roster.parse_text(text)
        if not rows:
            raise db.DbError("붙여넣은 내용이 없습니다. 엑셀에서 학번·이름 칸을 복사해 주세요.")
        return {"raw": rows, **roster.detect(rows)}

    # ---------- 엑셀 시트 고르기 ----------
    def _xlsx_token(self, path):
        import secrets

        t = secrets.token_hex(8)
        self._xlsx_paths[t] = path
        while len(self._xlsx_paths) > 20:
            self._xlsx_paths.pop(next(iter(self._xlsx_paths)))
        return t

    def _xlsx_pick(self, path):
        """시트가 하나(내용 있는 것)면 (rows, None). 여럿이면 (None, 고르기 정보)."""
        sheets = roster.xlsx_sheets(path)
        full = [x for x in sheets if x["rows"]]
        if len(full) <= 1:
            return roster.parse_xlsx(path, full[0]["name"] if full else None), None
        return None, {"token": self._xlsx_token(path), "file": os.path.basename(path), "sheets": sheets}

    def _xlsx_path(self, token):
        path = self._xlsx_paths.get(token or "")
        if not path or not os.path.exists(path):
            raise db.DbError("고른 파일을 다시 찾지 못했습니다. 파일을 다시 골라 주세요.")
        return path

    @safe
    def roster_from_xlsx(self, token=None, sheets=None):
        """명렬 파일을 여러 개 한꺼번에 고를 수 있다(xlsx·csv). 파일마다 읽은 결과와 오류를 돌려준다.
        시트가 여러 개인 xlsx는 ask로 돌려주고, 화면에서 고른 시트(여러 개 가능)를 token·sheets로 다시 부른다."""
        if token:
            path = self._xlsx_path(token)
            name = os.path.basename(path)
            files, errors = [], []
            for sh in sheets or []:
                try:
                    rows = roster.parse_xlsx(path, sh)
                except Exception:
                    errors.append(f"{name} › {sh}: 읽지 못했습니다")
                    continue
                if not rows:
                    errors.append(f"{name} › {sh}: 고른 시트에 내용이 없습니다")
                    continue
                files.append({"raw": rows, "file": f"{name} › {sh}", **roster.detect(rows)})
            if not files:
                raise db.DbError("읽은 명렬이 없습니다.\n" + "\n".join(errors or ["시트를 하나 이상 골라 주세요."]))
            return {"files": files, "errors": errors, "ask": []}
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True,
                                                 file_types=("명렬 파일 (*.xlsx;*.csv)", "Excel 파일 (*.xlsx)", "CSV 파일 (*.csv)"))
        if not result:
            return {"ok": False, "cancelled": True}
        paths = list(result) if isinstance(result, (list, tuple)) else [result]
        files, errors, ask = [], [], []
        for path in paths:
            name = os.path.basename(path)
            try:
                if path.lower().endswith(".csv"):
                    raw = open(path, "rb").read()
                    for enc in ("utf-8-sig", "cp949"):
                        try:
                            text = raw.decode(enc)
                            break
                        except UnicodeDecodeError:
                            text = None
                    if text is None:
                        raise ValueError
                    rows = roster.parse_text(text)
                else:
                    rows, pick = self._xlsx_pick(path)
                    if pick:
                        ask.append(pick)
                        continue
            except Exception:
                errors.append(f"{name}: 열지 못했습니다(Excel에서 열려 있으면 닫고 다시 시도)")
                continue
            if not rows:
                errors.append(f"{name}: 내용이 없습니다")
                continue
            files.append({"raw": rows, "file": name, **roster.detect(rows)})
        if not files and not ask:
            raise db.DbError("읽은 명렬이 없습니다.\n" + "\n".join(errors))
        return {"files": files, "errors": errors, "ask": ask}

    def _members_map(self, d, gid):
        return {m["student_no"]: bool(m["active"]) for m in d.members(gid)}

    @safe
    def roster_build(self, gid, raw, header, columns, add=False):
        d = self._db()
        rows = roster.build_rows(raw, bool(header), columns or {})
        return {"rows": roster.validate(rows, d.group(gid), d.known_names([r["student_no"] for r in rows if r["student_no"]]),
                                        self._members_map(d, gid) if add else None)}

    @safe
    def roster_direct(self, gid, text):
        """명렬 직접 입력: 줄마다 읽어 확인(검사)까지 한 결과. 화면에서 고친 뒤 roster_validate로 다시 확인한다."""
        rows = roster.parse_lines(text)
        lines = [(r.pop("line"), r.pop("raw")) for r in rows]
        out = self.roster_validate(gid, rows, True)
        if out.get("ok") is False:
            return out
        for r, (ln, raw) in zip(out["rows"], lines):
            r["line"], r["raw"] = ln, raw
        return {"rows": out["rows"]}

    @safe
    def roster_validate(self, gid, rows, add=False):
        d = self._db()
        for r in rows:
            r["student_no"] = str(r.get("student_no") or "").strip()
            r["name"] = str(r.get("name") or "").strip()
            for k in ("grade", "class_no", "number"):
                r[k] = roster._digits(r.get(k))
            r["level"] = str(r.get("level") or "").strip().upper()
            r["section"] = str(r.get("section") or "").strip()[:40]
            if not r["student_no"] and r["grade"] and r["class_no"] and r["number"]:  # 학년·반·번호로 학번 만들기
                r["student_no"] = f"{int(r['grade'])}{int(r['class_no']):02d}{int(r['number']):02d}"
            if r["student_no"] and not (r["grade"] and r["class_no"]):
                parts = roster.split_student_no(r["student_no"])
                if parts:
                    r["grade"], r["class_no"], r["number"] = (str(x) for x in parts)
        return {"rows": roster.validate(rows, d.group(gid), d.known_names([r["student_no"] for r in rows if r["student_no"]]),
                                        self._members_map(d, gid) if add else None)}

    @safe
    def roster_apply(self, gid, rows, mode="replace"):
        """mode: replace(이 명렬로 바꾸기) / add(지금 명렬에 더하기)"""
        self._editable()
        d = self._db()
        add = mode == "add"
        checked = self.roster_validate(gid, rows, add)
        if not checked.get("ok"):
            return checked
        bad = [r for r in checked["rows"] if r["issues"]]
        if bad:
            raise db.DbError(f"확인이 필요한 행 {len(bad)}개를 먼저 고쳐 주세요.")
        result = d.apply_roster(gid, checked["rows"], replace=not add)
        return {**result, "groups": d.groups()}

    @safe
    def set_section(self, gid, student_nos, section):
        """선택과목: 고른 학생의 수업 이름(비우면 학년-반으로 묶음)."""
        self._editable()
        d = self._db()
        return {"changed": d.set_section(gid, student_nos, section)}

    @safe
    def members(self, gid):
        return {"members": self._db().members(gid)}

    @safe
    def set_active(self, gid, student_nos, active, all_groups=False):
        self._editable()
        d = self._db()
        n = d.set_active(gid, student_nos, bool(active), bool(all_groups))
        return {"changed": n, "groups": d.groups()}

    @safe
    def roster_copy_source(self, src_gid):
        """다른 담당의 명렬(활성 학생만)을 명렬 입력에 넣을 행으로."""
        d = self._db()
        rows = [{"student_no": m["student_no"], "name": m["name"], "grade": str(m["grade"] or ""), "class_no": str(m["class_no"] or ""),
                 "number": str(m["number"] or ""), "level": "", "section": m["section"]} for m in d.members(src_gid) if m["active"]]
        return {"rows": rows, "label": d.group(src_gid)["name"]}

    @safe
    def member_impact(self, gid, student_nos, all_groups=False):
        return self._db().member_impact(gid, student_nos, bool(all_groups))

    @safe
    def remove_members(self, gid, student_nos, all_groups=False):
        """전출 학생 삭제: 먼저 백업하고 지운다."""
        self._editable()
        with self._maintenance("학생 삭제"):
            d = self._db()
            name = backup.make("학생삭제전")
            n = d.remove_members(gid, student_nos, bool(all_groups))
            self._last_undo = None
        return {"removed": n, "backup": name, "groups": d.groups()}

    @safe
    def set_level(self, gid, student_no, level):
        self._editable()
        self._db().set_level(gid, student_no, level)
        return {}

    # ---------- 일정·분량 ----------
    @safe
    def add_schedule(self, date, title):
        self._editable()
        d = self._db()
        d.add_schedule(date, title)
        return {"schedules": d.schedules()}

    @safe
    def update_schedule(self, sid, date, title):
        self._editable()
        d = self._db()
        d.update_schedule(sid, date, title)
        return {"schedules": d.schedules()}

    @safe
    def delete_schedule(self, sid):
        self._editable()
        d = self._db()
        d.delete_schedule(sid)
        return {"schedules": d.schedules()}

    @safe
    def set_target(self, item, value):
        self._editable()
        d = self._db()
        d.set_target(item, value)
        return {"targets": d.targets()}

    # ---------- 현황판 ----------
    @safe
    def dashboard(self):
        d = self._db()
        rec = Records(d)
        role = d.role()
        groups = [g for g in d.groups() if role == "homeroom" or g["kind"] != "homeroom"]
        member_groups = d.student_groups()
        out = []
        todo_final = todo_close = todo_stale = 0
        first = {}  # 할 일 종류 → 처음 만난 (담당, 항목)
        for g in groups:
            members = d.members(g["id"])
            items = list(items_of(g))
            smaps = {it: rec.status_map(g["id"], it) for it in items}
            rows = []
            counts = {"none": 0, "progress": 0, "final": 0, "closed": 0}
            for m in members:
                st = {it: smaps[it].get(m["student_no"], {}).get("status", "none") for it in items}
                one = smaps[items[0]].get(m["student_no"], {}) if len(items) == 1 else {}
                stale = any(smaps[it].get(m["student_no"], {}).get("stale") for it in items)
                rows.append({
                    **m,
                    "status": st,
                    "records": sum(smaps[it].get(m["student_no"], {}).get("records", 0) for it in items),
                    "final_bytes": one.get("final_bytes"),
                    "stale": stale,
                    "others": [x for x in member_groups.get(m["student_no"], []) if x != g["id"]],
                    "senior_note": g["kind"] in ("homeroom", "club") and m["grade"] == 3,
                })
                if m["active"]:
                    for v in st.values():
                        counts[v] += 1
                    todo_final += sum(1 for v in st.values() if v == "progress")
                    todo_close += sum(1 for v in st.values() if v == "final")
                    todo_stale += 1 if stale else 0
                    for it in items:
                        o = smaps[it].get(m["student_no"], {})
                        if o.get("status") == "progress":
                            first.setdefault("final", (g["id"], it))
                        if o.get("status") == "final":
                            first.setdefault("close", (g["id"], it))
                        if o.get("stale"):
                            first.setdefault("stale", (g["id"], it))
            active = [r for r in rows if r["active"]]
            out.append({
                **g,
                "items": items,
                "rows": rows,
                "summary": {"students": len(active), "item_total": len(active) * len(items), **counts},
            })
        # 순서: 명렬 → 인박스 매칭 → 인박스 보내기 → 채택 후 변경 → 최종안 만들기 → 마감 검토
        todo = []
        empty = [g for g in out if g["total"] == 0]
        if empty:
            todo.append({"kind": "roster", "label": f"명렬 등록 {len(empty)}곳", "group_id": empty[0]["id"]})
        ib = Inbox(d).batches()
        need = [b for b in ib if b["stage"] in ("import", "match") and (b["pending"] or b["stage"] == "import")]
        ready = [b for b in ib if b["stage"] in ("refine", "review") or (b["stage"] == "match" and not b["pending"] and b["n"])]
        if need:
            todo.append({"kind": "inbox", "label": f"인박스 확인 필요 {len(need)}묶음", "batch_id": need[0]["id"]})
        if ready:
            todo.append({"kind": "inbox", "label": f"인박스 보내기 대기 {len(ready)}묶음", "batch_id": ready[0]["id"]})
        for kind, n, label, flt in (("stale", todo_stale, "채택 후 기록 변경", "stale"), ("final", todo_final, "최종안 만들기", "progress"),
                                    ("close", todo_close, "마감 검토", "final")):
            if n:
                gid, it = first[kind]
                todo.append({"kind": kind, "label": f"{label} {n}건", "group_id": gid, "item": it, "filter": flt})
        return {"role": role, "groups": out, "todo": todo, "schedules": d.schedules()}

    # ---------- 항목별 기록 ----------
    def _rec(self) -> Records:
        return Records(self._db())

    def _editable(self, year=None):
        """쓰기 전에: 관리 작업 중·보관 학년도면 막는다. year를 주면 지금 학년도와 같은지도 본다."""
        with self._ai_lock:
            self._check_running()
        if year is not None and int(year) != config.load()["current_year"]:
            raise db.DbError("학년도가 바뀌어 저장하지 않았습니다. 화면을 다시 열어 확인해 주세요.")
        st = self.year_state()
        if st.get("ok") and st.get("archived"):
            raise db.DbError("보관 학년도는 조회만 할 수 있습니다. 상단에서 최신 학년도로 바꿔 주세요.")

    @safe
    def slots(self):
        d = self._db()
        return {"slots": Records(d).slots(d.role())}

    @safe
    def slot_view(self, gid, item):
        d = self._db()
        rec = Records(d)
        g, target = rec.slot(gid, item)
        smap = rec.status_map(gid, item)
        students = []
        for m in d.members(gid):
            o = smap.get(m["student_no"], {})
            students.append({**m, "status": o.get("status", "none"), "records": o.get("records", 0),
                             "final_bytes": o.get("final_bytes"), "stale": o.get("stale", False)})
        return {"group": g, "item": item, "target": target, "students": students}

    @safe
    def student_view(self, gid, item, sno):
        d = self._db()
        rec = Records(d)
        g, _ = rec.slot(gid, item)
        target, pair = rec.target_for(gid, item, sno)
        m = next((x for x in d.members(gid) if x["student_no"] == str(sno)), None)
        if not m:
            raise db.DbError("학생을 찾지 못했습니다.")
        f = rec.final(gid, item, sno)
        final = None
        if f:
            final = {**f, "closed": bool(f["closed"]), "stale": bool(f["stale"]), "bytes": count_bytes(f["text"])}
        std = None
        if g["kind"] == "subject":
            st = Standards(d).get(gid)
            std = {"text": st["text"], "level_scale": g["level_scale"] or 5}
        return {"student": m, "target": target, "pair": pair, "records": rec.records(gid, item, sno),
                "results": rec.slot_results(gid, item, sno), "final": final, "tags": rec.tags(),
                "weight_sum_check": config.load()["weight_sum_check"], "standards": std}

    @safe
    def add_record(self, gid, item, sno, data):
        self._editable()
        return {"id": self._rec().add_record(gid, item, sno, data or {})}

    @safe
    def update_record(self, rid, data):
        data = dict(data or {})
        self._editable(data.pop("year", None))
        rec = self._rec()
        rec.update_record(rid, data or {})
        return {"record": rec.record_state(rid)}

    # ---------- 태그별 기록 ----------
    @safe
    def tag_view(self, tag_id, flt=None):
        d = self._db()
        return Records(d).tag_view(d.role(), tag_id, flt or {})

    @safe
    def record_state(self, rid):
        return {"record": self._rec().record_state(rid)}

    @safe
    def revert_record(self, rid, before, after, year=None):
        self._editable(year)
        return {"record": self._rec().revert_record(rid, before or {}, after or {})}

    @safe
    def tag_records_undoable(self, record_ids, tag_ids, mode="add", year=None):
        self._editable(year)
        rec = self._rec()
        pairs = rec.tag_records_changed(record_ids, tag_ids, mode)
        return {"pairs": pairs, "states": {str(r): rec.record_state(r) for r in {p[0] for p in pairs}}}

    @safe
    def undo_tag_records(self, pairs, mode, year=None):
        self._editable(year)
        rec = self._rec()
        done, skipped, changed = rec.undo_tag_pairs(pairs, mode)
        ids = {int(p[0]) for p in pairs or []}
        states = {}
        for r in ids:
            try:
                states[str(r)] = rec.record_state(r)
            except db.DbError:
                pass
        return {"done": done, "skipped": skipped, "changed": changed, "states": states}

    @safe
    def copy_text(self, text):
        export.write_clipboard(text or "")
        return {}

    @safe
    def delete_records(self, record_ids, confirm=None, year=None):
        """태그별 기록에서 고른 기록 여러 건 삭제(되돌릴 수 없음 → '확인했어요' 입력)."""
        self._editable(year)
        if (confirm or "").strip() != updater.CONFIRM_WORD:
            raise db.DbError(f"'{updater.CONFIRM_WORD}'를 입력해야 지웁니다.")
        return self._rec().delete_records(record_ids)

    @safe
    def delete_record(self, rid):
        self._editable()
        self._rec().delete_record(rid)
        return {}

    @safe
    def apply_candidate(self, res_id):
        self._editable()
        self._rec().apply_candidate_to_record(res_id)
        return {}

    @safe
    def lock_result(self, res_id, locked):
        self._editable()
        self._rec().lock_result(res_id, locked)
        return {}

    @safe
    def delete_result(self, res_id):
        self._editable()
        self._rec().delete_result(res_id)
        return {}

    @safe
    def adopt_result(self, res_id):
        self._editable()
        self._rec().adopt_result(res_id)
        return {}

    @safe
    def adopt_record(self, rid):
        self._editable()
        self._rec().adopt_record(rid)
        return {}

    @safe
    def edit_final(self, gid, item, sno, text, year=None):
        self._editable(year)
        self._rec().edit_final(gid, item, sno, text)
        return {}

    @safe
    def reorder_records(self, gid, item, sno, ids):
        self._editable()
        self._rec().reorder(gid, item, sno, ids)
        return {}

    @safe
    def set_closed(self, gid, item, sno, closed):
        self._editable()
        self._rec().set_closed(gid, item, sno, bool(closed))
        return {}

    @safe
    def close_info(self, gid, item):
        return self._rec().close_info(gid, item)

    @safe
    def close_many(self, gid, item, snos, closed, year=None):
        """일괄 마감/해제. 반환 done(바꾼 학번)·skipped([학번, 이유]) — 화면에서 [되돌리기]는 done만 반대로."""
        self._editable(year)
        done, skipped = self._rec().close_many(gid, item, snos or [], bool(closed))
        return {"done": done, "skipped": skipped}

    # ---------- 문단 이동 ----------
    @safe
    def move_targets(self, gid, item, sno):
        return {"targets": self._rec().move_targets(gid, item, sno)}

    @safe
    def move_records(self, moves, dest_gid, dest_item):
        self._editable()
        self._last_undo = self._rec().move(moves or [], dest_gid, dest_item)
        return {"moved": len(moves or [])}

    @safe
    def undo_move(self):
        self._editable()
        u = getattr(self, "_last_undo", None)
        if not u:
            raise db.DbError("되돌릴 이동이 없습니다.")
        try:
            self._rec().undo_move(u)
        finally:
            self._last_undo = None
        return {}

    @safe
    def batch_info(self, gid, item):
        return self._rec().batch_info(gid, item)

    # ---------- 태그 ----------
    @safe
    def tags(self):
        return {"tags": self._rec().tags()}

    @safe
    def add_tag(self, name):
        self._editable()
        rec = self._rec()
        tid = rec.add_tag(name)
        return {"id": tid, "tags": rec.tags()}

    @safe
    def inbox_tag_names(self):
        return {"names": self._rec().inbox_tag_names()}

    @safe
    def tags_from_inbox(self, names):
        self._editable()
        rec = self._rec()
        made, attached = rec.tags_from_inbox(names)
        return {"made": made, "attached": attached, "tags": rec.tags()}

    @safe
    def rename_tag(self, tid, name):
        self._editable()
        rec = self._rec()
        rec.rename_tag(tid, name)
        return {"tags": rec.tags()}

    @safe
    def delete_tag(self, tid):
        self._editable()
        rec = self._rec()
        rec.delete_tag(tid)
        return {"tags": rec.tags()}

    @safe
    def tag_records(self, record_ids, tag_ids, mode="add"):
        self._editable()
        return {"count": self._rec().tag_records(record_ids, tag_ids, mode)}

    # ---------- AI ----------
    def _model(self, index):
        cfg = config.load()
        try:
            i = int(index)
        except (TypeError, ValueError):
            i = cfg["default_model"]
        if not 0 <= i < 4:
            i = cfg["default_model"]
        model = cfg["models"][i]
        if not model:
            raise db.DbError(f"{i + 1}번 모델 칸이 비어 있습니다. 설정 > 연결·모델에서 모델을 넣어 주세요.")
        if not cfg["openrouter_key"].strip():
            raise db.DbError("OpenRouter API 키가 없습니다. 설정에서 넣어 주세요.")
        return cfg, model

    # 이번 실행에만 쓰는 교사의 추가 요구 사항(AI 실행 확인 창에서 입력). 저장된 프롬프트는 바꾸지 않는다.
    @safe
    def ai_extra_set(self, text=None, prompt_id=None, kind=None):
        """이번 실행에만: 추가 요구 사항과 고른 프롬프트. 고른 프롬프트는 작업 종류마다 기억한다(다음 실행의 기본)."""
        self._ai_extra = (text or "").strip()[:1000]
        self._ai_prompt = str(prompt_id or "")
        if prompt_id and kind in prompts.KINDS:
            picks = dict(config.load().get("prompt_pick") or {})
            if picks.get(kind) != prompt_id:
                picks[kind] = str(prompt_id)
                config.save({"prompt_pick": picks})
        return {}

    def _library(self):
        cfg = config.load()
        lib, changed = prompts.build_library(cfg.get("prompt_lib"), cfg.get("prompts"))
        if changed:
            config.save({"prompt_lib": lib})
        return lib, cfg

    def _prompt(self, kind):
        """이번 실행에 쓸 프롬프트 {id, name, prompt, example}."""
        lib, cfg = self._library()
        return prompts.pick(lib, cfg.get("prompt_pick"), kind, getattr(self, "_ai_prompt", ""))

    def _xm(self, meta):
        """결과 기록(meta)에 이번 추가 요구 사항을 남긴다."""
        x = getattr(self, "_ai_extra", "")
        return {**(meta or {}), "extra": x} if x else meta

    def _call_ai(self, key, model, system, user, privacy):
        x = getattr(self, "_ai_extra", "")
        if x:
            system = (system + "\n\n[이번 추가 요구 사항 — 교사가 이번 실행에만 준 요청]\n<요청>\n" + x + "\n</요청>\n"
                      "- 위 요청을 반영하되, 앞의 규칙(학번·이름 쓰지 않기, 분량, 없는 사실 지어내지 않기, 원문 보존, 출력 형식)이 항상 우선한다.")
        if openrouter.cancelled():
            raise openrouter.Cancelled()
        text, cost = openrouter.chat(key, model, system, user, privacy)
        with self._ai_lock:
            self._run_cost += cost
        if openrouter.cancelled():  # [바로 중지] 뒤에 도착한 답은 저장하지 않는다
            raise openrouter.Cancelled()
        if not text.strip():
            raise openrouter.LlmError("AI가 빈 결과를 돌려주었습니다. 다시 시도하거나 다른 모델을 고르세요.")
        return text, cost

    @safe
    def ai_cancel(self):
        """[바로 중지]: 진행 중인 AI 요청 연결을 끊고, 늦게 도착한 답도 버린다."""
        openrouter.cancel()
        return {}

    @safe
    def ai_cancel_reset(self):
        """새 AI 실행을 시작할 때 중지 표시를 푼다."""
        openrouter.reset()
        return {}

    def _guard(self, key):
        with self._ai_lock:
            self._check_running()
            if key in self._ai_keys:
                raise db.DbError("이미 AI 작업이 진행 중입니다. 끝날 때까지 기다려 주세요.")
            self._ai_keys.add(key)

    def _release(self, key):
        with self._ai_lock:
            self._ai_keys.discard(key)

    def _ai_out(self, extra):
        return {**extra, "cost": extra.get("cost", 0), "run_cost": self._run_cost,
                "balance": openrouter.balance(config.load()["openrouter_key"])}

    @safe
    def ai_record(self, rid, model_index=None):
        """기록 한 건: 학생관찰기록은 정제(refine), 이미 쓴 생기부는 다듬기(polish). 내용만 보낸다."""
        self._editable()
        rec = self._rec()
        r = rec.record(rid)
        rec.require_open(r["group_id"], r["item"], r["student_no"])
        rec.check_room(r["group_id"], r["item"], r["student_no"], r["id"])
        cfg, model = self._model(model_index)
        op = "polish" if r["kind"] == "existing" else "refine"
        pr = self._prompt(op)
        target = rec.ai_target(r["group_id"], r["item"], r["student_no"]) if op == "polish" else 0
        system = prompts.build_system(pr["prompt"], pr["example"], target)
        key = ("record", r["id"])
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, system, r["content"], cfg["privacy_block"])
            meta = {"model": model, "op": op, "prompt_name": pr["name"], "prompt": pr["prompt"], "example": pr["example"], "record_ids": [r["id"]]}
            nid, dropped = rec.add_result(r["group_id"], r["item"], r["student_no"], op, text, self._xm(meta), cost, record_id=r["id"])
            return self._ai_out({"id": nid, "dropped": dropped, "cost": cost})
        finally:
            self._release(key)

    @safe
    def ai_synth(self, gid, item, sno, record_ids, weights_map=None, model_index=None, sum_check=None, std=None):
        """선택한 기록들을 비중대로 종합 → 학생×항목 후보. 학번·이름 없이 내용과 비율만 보낸다.
        std(세특만): {"text": 이번에 쓸 성취기준, "level": 성취수준} — 있으면 성취기준 관점·수준 반영."""
        self._editable()
        rec = self._rec()
        g, _ = rec.slot(gid, item)
        std_rule, std_meta = self._std_rule(g, item, std, only=False)
        rec.require_open(gid, item, sno)
        target = rec.ai_target(gid, item, sno)
        rec.check_room(gid, item, sno)
        ids = [int(x) for x in record_ids or []]
        idset = set(ids)
        chosen = [r for r in rec.records(gid, item, sno) if r["id"] in idset]  # 화면의 기록 순서대로
        if not chosen:
            raise weights.WeightError("종합할 기록을 고르세요.")
        wm = {int(k): v for k, v in (weights_map or {}).items()}
        for r in chosen:  # 화면에서 바꾼 비중은 기록에 저장해 둔다
            if r["id"] in wm and wm[r["id"]] != r["weight"]:
                rec.update_record(r["id"], {"weight": wm[r["id"]]})
                r["weight"] = None if wm[r["id"]] in (None, "") else float(wm[r["id"]])
        cfg, model = self._model(model_index)
        check = cfg["weight_sum_check"] if sum_check is None else bool(sum_check)
        ratios = weights.compute([{"bytes": r["bytes"], "weight": r["weight"]} for r in chosen], check)
        pr = self._prompt("synth")
        system = prompts.build_system(pr["prompt"] + std_rule + prompts.SYNTH_RULE, pr["example"], target)
        user = prompts.build_synth_user([{"text": r["content"], "ratio": q} for r, q in zip(chosen, ratios)], target)
        key = ("slot", int(gid), item, str(sno))
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, system, user, cfg["privacy_block"])
            meta = {"model": model, "op": "synth", "prompt_name": pr["name"], "prompt": pr["prompt"], "example": pr["example"], "target": target,
                    "record_ids": [r["id"] for r in chosen], "ratios": [round(q * 100, 1) for q in ratios], "sum_check": check, **std_meta}
            nid, dropped = rec.add_result(gid, item, sno, "synth", text, self._xm(meta), cost)
            return self._ai_out({"id": nid, "dropped": dropped, "cost": cost, "ratios": meta["ratios"]})
        finally:
            self._release(key)

    def _std_rule(self, g, item, std, only):
        if not std or not (std.get("text") or "").strip():
            if only:
                raise db.DbError("성취기준이 비어 있습니다. 메뉴의 [성취기준]에서 먼저 넣어 주세요.")
            return "", {}
        if item != "subject":
            raise db.DbError("성취기준은 과목 세특에서만 쓸 수 있습니다.")
        level = check_level(std.get("level"), g["level_scale"] or 5)
        if only and not level:
            raise db.DbError("성취기준만으로 만들 때는 성취수준을 골라 주세요.")
        return (standards_rule(std["text"], level, g["level_scale"] or 5, only),
                {"standards": True, "level": level, "basis": "standards_only" if only else "records+standards", "standards_text": std["text"][:20000]})

    def _basis_avoid(self, rec, gid, item, sno, n=3):
        """같은 담당에서 기준 자료만으로 만든 다른 학생의 최근 문장(겹치지 않게 AI에 함께 보냄). 학번·이름은 넣지 않는다.
        기준 자료로 만든 후보만 먼저 골라 최근 n개(일반 종합 후보가 많아도 가려지지 않게)."""
        rows = rec.d.q("SELECT text FROM results WHERE group_id=? AND item=? AND student_no<>? AND record_id IS NULL AND op='synth' "
                       "AND json_extract(meta, '$.basis') IN ('standards_only', 'outline_only') ORDER BY id DESC LIMIT ?",
                       (int(gid), item, str(sno), int(n)))
        return [r["text"] for r in rows]

    @safe
    def ai_standards_only(self, gid, item, sno, std, model_index=None):
        """기록이 없는 학생: 기준 자료만으로 후보를 만든다. 학번·이름은 보내지 않는다.
        세특 std={text, level}(성취기준·성취수준), 자율·진로·동아리 std={lines}(이 학생이 참여한 활동 개요 줄).
        같은 담당에서 이미 만든 다른 학생 문장 몇 개를 함께 보내 50% 이상 다르게 쓰게 한다."""
        self._editable()
        rec = self._rec()
        g, _ = rec.slot(gid, item)
        rec.require_open(gid, item, sno)
        rec.check_room(gid, item, sno)
        target = rec.ai_target(gid, item, sno)
        if item == "subject":
            rule, meta = self._std_rule(g, item, std, only=True)
        elif item in ("autonomy", "career", "club"):
            lines = [str(x).strip() for x in ((std or {}).get("lines") or []) if str(x).strip()]
            if not lines:
                raise db.DbError("이 학생이 참여한 활동을 하나 이상 골라 주세요.")
            rule = outline_rule(lines)
            meta = {"basis": "outline_only", "outline_lines": lines}
        else:
            raise db.DbError("기준 자료로 생성은 세특·자율·진로·동아리에서만 쓸 수 있습니다.")
        avoid = self._basis_avoid(rec, gid, item, sno)
        rule += avoid_rule(avoid)
        meta["avoid_count"] = len(avoid)
        cfg, model = self._model(model_index)
        pr = self._prompt("synth")
        key = ("slot", int(gid), item, str(sno))
        self._guard(key)
        try:
            what = "성취기준과 성취수준" if item == "subject" else "활동 개요"
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, prompts.build_system(pr["prompt"] + rule + prompts.SYNTH_RULE, pr["example"], target),
                                       f"(학생관찰기록 없음 — {what}으로만 작성)", cfg["privacy_block"])
            meta.update({"model": model, "op": "synth", "prompt_name": pr["name"], "prompt": pr["prompt"], "example": pr["example"], "target": target})
            nid, dropped = rec.add_result(gid, item, sno, "synth", text, self._xm(meta), cost)
            return self._ai_out({"id": nid, "dropped": dropped, "cost": cost})
        finally:
            self._release(key)

    @safe
    def basis_similarity(self, gid, item, snos=None):
        """기준 자료만으로 만든 학생별 최신 후보와, 다른 학생 후보와 표현이 얼마나 겹치는지(글자 3개 묶음 기준 참고값).
        반환: {학번: {sim, with, text, with_text}} — snos가 있으면 그 학생들만(비교 상대는 담당 전체)."""
        rec = self._rec()
        rows = rec.d.q("SELECT student_no, text FROM results WHERE group_id=? AND item=? AND record_id IS NULL AND op='synth' "
                       "AND json_extract(meta, '$.basis') IN ('standards_only', 'outline_only') ORDER BY id", (int(gid), item))
        latest = {r["student_no"]: r["text"] for r in rows}
        want = [str(x) for x in snos] if snos else list(latest)
        out = {}
        for a in want:
            if a not in latest:
                continue
            best, who = 0.0, ""
            for b, tb in latest.items():
                if b != a:
                    v = similarity(latest[a], tb)
                    if v > best:
                        best, who = v, b
            out[a] = {"sim": round(best, 3), "with": who, "text": latest[a], "with_text": latest.get(who, "")}
        return {"similar": out}

    # ---------- 활동 개요(자율·진로·동아리) ----------
    @safe
    def outline_get(self, gid, item):
        return Outlines(self._db()).get(gid, item)

    @safe
    def outline_tidy(self, gid, item, text, model_index=None):
        """활동 개요를 AI로 다듬기(저장하지 않음): 한 줄에 활동 하나, 맞춤법만. 없는 내용은 더하지 않게 하고,
        원문에 없던 낱말은 new_words로 알려 화면에서 확인하게 한다."""
        self._editable()
        Outlines(self._db())._check(gid, item)
        if not (text or "").strip():
            raise db.DbError("다듬을 내용이 없습니다.")
        cfg, model = self._model(model_index)
        key = ("outline", int(gid), item)
        self._guard(key)
        try:
            out, cost = self._call_ai(cfg["openrouter_key"].strip(), model, outline_tidy_prompt(), text[:20000], cfg["privacy_block"])
        finally:
            self._release(key)
        out = "\n".join(ln.rstrip() for ln in (out or "").replace("\r", "").split("\n") if ln.strip())
        return self._ai_out({"cost": cost, "text": out, "new_words": new_words(text, out)})

    @safe
    def outline_save(self, gid, item, text, source=None, year=None):
        self._editable(year)
        Outlines(self._db()).save(gid, item, text, source)
        return {}

    # ---------- 성취기준 ----------
    @safe
    def standards_overview(self):
        d = self._db()
        return {"subjects": Standards(d).overview(), "outlines": Outlines(d).overview()}

    @safe
    def standards_format(self, gid, text, use_ai=False, model_index=None):
        """성취기준 붙여넣기를 보기 좋게 정리(저장은 하지 않음). 원문 글자는 바꾸지 않고 줄 배치만 바꾼다.
        규칙으로 판단이 안 되는 줄이 있을 때만, use_ai=True면 AI에 줄 역할만 묻는다(글은 쓰지 않게)."""
        d = self._db()
        g = d.group(gid)
        if g["kind"] != "subject":
            raise db.DbError("성취기준은 과목에서만 씁니다.")
        lines = stdformat.split_lines(text)
        if not any(x.strip() for x in lines):
            raise db.DbError("정리할 내용이 없습니다. 성취기준을 먼저 붙여넣어 주세요.")
        roles = stdformat.classify(lines)
        unknown = roles.count("unknown")
        ai_used, cost, ai_headers, check = False, 0.0, [], []
        if unknown and use_ai:
            self._editable()
            cfg, model = self._model(model_index)
            key = ("stdformat", int(gid))
            self._guard(key)
            try:
                answer, cost = self._call_ai(cfg["openrouter_key"].strip(), model, stdformat.ai_prompt(), stdformat.ai_user(lines, roles), cfg["privacy_block"])
            finally:
                self._release(key)
            roles, ai_headers, check = stdformat.apply_ai(lines, roles, answer)
            ai_used = True
        out, three, headers, left = stdformat.build(lines, roles)
        missing = stdformat.verify(lines, roles, out)
        return {**(self._ai_out({"cost": cost}) if ai_used else {}), "text": out, "three_level": three,
                "headers": [lines[i].strip() for i in headers], "unknown": unknown, "unknown_left": left, "ai_used": ai_used,
                "ai_headers": [lines[i].strip() for i in ai_headers], "check": [lines[i].strip() for i in check],
                "missing": [lines[i].strip() for i in missing], "gaps": [ln for _, ln in stdformat.gaps(lines, roles)],
                "content_lines": sum(1 for r in roles if r not in (None, "header", "label"))}

    @safe
    def standards_fill_gaps(self, gid, text, model_index=None):
        """수식이 빠진 빈 곳만 AI로 채우거나 앞뒤를 잇는다(저장하지 않음). 원문 글자를 지우거나 바꾼 줄은 버린다."""
        self._editable()
        g = self._db().group(gid)
        if g["kind"] != "subject":
            raise db.DbError("성취기준은 과목에서만 씁니다.")
        gl = stdformat.gap_lines(text)
        if not gl:
            return {"text": text, "changed": [], "rejected": [], "gaps": 0}
        cfg, model = self._model(model_index)
        key = ("stdformat", int(gid))
        self._guard(key)
        try:
            answer, cost = self._call_ai(cfg["openrouter_key"].strip(), model, stdformat.fill_prompt(), stdformat.fill_user(gl[:200]), cfg["privacy_block"])
        finally:
            self._release(key)
        out, changed, rejected = stdformat.apply_fill(text, gl[:200], answer)
        return self._ai_out({"cost": cost, "text": out, "changed": changed, "rejected": rejected, "gaps": len(gl)})

    @safe
    def standards_get(self, gid):
        return Standards(self._db()).get(gid)

    @safe
    def standards_save(self, gid, text, source=None, year=None):
        self._editable(year)
        Standards(self._db()).save(gid, text, source)
        return {}

    @safe
    def standards_read_file(self, kind):
        """PDF(글자 있는 문서) 또는 hwpx에서 글자를 읽어 돌려준다. 저장은 화면에서 확인 뒤."""
        types = ("PDF 파일 (*.pdf)",) if kind == "pdf" else ("한글 문서 (*.hwpx)",)
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=types)
        if not res:
            return {"ok": False, "cancelled": True}
        path = res[0] if isinstance(res, (list, tuple)) else res
        text = read_pdf_text(path) if kind == "pdf" else read_hwpx_text(path)
        return {"text": text, "file": os.path.basename(path)}

    @safe
    def ai_polish_final(self, gid, item, sno, model_index=None):
        """최종안(또는 직접 쓴 글)을 다듬어 학생×항목 후보로."""
        self._editable()
        rec = self._rec()
        rec.slot(gid, item)
        rec.require_open(gid, item, sno)
        target = rec.ai_target(gid, item, sno)
        f = rec.final(gid, item, sno)
        if not (f and f["text"].strip()):
            raise db.DbError("다듬을 최종안이 없습니다.")
        rec.check_room(gid, item, sno)
        cfg, model = self._model(model_index)
        pr = self._prompt("polish")
        key = ("slot", int(gid), item, str(sno))
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, prompts.build_system(pr["prompt"], pr["example"], target), f["text"], cfg["privacy_block"])
            meta = {"model": model, "op": "polish", "prompt_name": pr["name"], "prompt": pr["prompt"], "example": pr["example"], "target": target, "from": "final"}
            nid, dropped = rec.add_result(gid, item, sno, "polish", text, self._xm(meta), cost)
            return self._ai_out({"id": nid, "dropped": dropped, "cost": cost})
        finally:
            self._release(key)

    @safe
    def run_cost(self):
        return {"run_cost": self._run_cost}

    # ---------- 프롬프트 목록 ----------
    @safe
    def prompt_list(self):
        lib, cfg = self._library()
        picks = {k: prompts.pick(lib, cfg.get("prompt_pick"), k)["id"] for k in prompts.KINDS}
        return {"prompts": lib, "picks": picks, "kinds": prompts.KIND_NAMES,
                "defaults": {k: prompts.BUILTIN[k]["prompt"] for k in prompts.BUILTIN}}

    @safe
    def prompt_wizard_spec(self):
        from . import prompt_wizard

        return {"spec": prompt_wizard.default_spec(), "items": list(prompts.ITEM_NAMES.values()), "note": prompt_wizard.STEPS_NOTE}

    @safe
    def prompt_wizard_build(self, spec):
        from . import prompt_wizard

        return {"text": prompt_wizard.build(spec or {})}

    @safe
    def prompt_save(self, entry):
        """새로 만들기(id 없음) 또는 고치기. 기본 프롬프트는 이름을 바꾸지 않는다."""
        import uuid

        e = dict(entry or {})
        name = (e.get("name") or "").strip()[:60]
        if not name:
            raise db.DbError("프롬프트 이름을 적어 주세요.")
        lib, _ = self._library()
        pid = str(e.get("id") or "")
        if pid:
            cur = next((x for x in lib if x["id"] == pid), None)
            if not cur:
                raise db.DbError("프롬프트를 찾지 못했습니다.")
            if not cur["builtin"]:
                cur["name"] = name
            cur["prompt"] = str(e.get("prompt") or "")
            cur["example"] = str(e.get("example") or "")
        else:
            pid = "p" + uuid.uuid4().hex[:10]
            lib.append({"id": pid, "name": name, "prompt": str(e.get("prompt") or ""), "example": str(e.get("example") or ""), "builtin": False})
        config.save({"prompt_lib": lib})
        return {"id": pid}

    @safe
    def prompt_delete(self, pid):
        lib, cfg = self._library()
        if pid in prompts.BUILTIN:
            raise db.DbError("기본 프롬프트는 지울 수 없습니다. [기본값으로 되돌리기]를 쓰세요.")
        if not any(x["id"] == pid for x in lib):
            raise db.DbError("프롬프트를 찾지 못했습니다.")
        picks = {k: v for k, v in (cfg.get("prompt_pick") or {}).items() if v != pid}
        config.save({"prompt_lib": [x for x in lib if x["id"] != pid], "prompt_pick": picks})
        return {}

    @safe
    def prompt_reset(self, pid):
        if pid not in prompts.BUILTIN:
            raise db.DbError("기본 프롬프트만 되돌릴 수 있습니다.")
        lib, _ = self._library()
        for x in lib:
            if x["id"] == pid:
                x.update(prompt=prompts.BUILTIN[pid]["prompt"], example=prompts.BUILTIN[pid]["example"])
        config.save({"prompt_lib": lib})
        return {}

    # ---------- 이미 쓴 생기부 일괄 넣기 ----------
    @safe
    def existing_parse(self, gid, item, text=None, from_xlsx=False, token=None, sheet=None):
        """이미 쓴 생기부: 붙여넣은 글 또는 xlsx를 읽고 열을 알아본다(NEIS 업로드 형식 포함).
        시트가 여러 개면 {sheets, token}을 돌려주고, 고른 시트를 token·sheet로 다시 부른다."""
        d = self._db()
        Records(d).slot(gid, item)
        if from_xlsx:
            raw, pick = self._read_xlsx(token, sheet)
            if pick or raw is None:
                return pick or {"ok": False, "cancelled": True}
        else:
            raw = roster.parse_text(text or "", delim="\t")
        if not raw:
            raise db.DbError("내용이 없습니다. 엑셀에서 이름과 생기부 내용 칸을 함께 복사해 주세요.")
        return {"raw": raw, **existing.detect(raw)}

    @safe
    def existing_build(self, gid, item, raw, header, columns):
        """이름을 기준으로 학생과 연결한다. 학번·반/번호는 확인용."""
        d = self._db()
        rec = Records(d)
        rec.slot(gid, item)
        members = d.members(gid)
        rows = existing.build(raw, bool(header), columns or {}, members, config.load()["current_year"])
        out_members = [{"student_no": m["student_no"], "name": m["name"], "grade": m["grade"], "class_no": m["class_no"],
                        "number": m["number"], "active": bool(m["active"]), "closed": rec.is_closed(gid, item, m["student_no"])} for m in members]
        return {"rows": rows, "members": out_members}

    @safe
    def existing_apply(self, gid, item, rows, kind="existing", req_id=None):
        """rows: [{student_no, content, title?, date?}] — 화면에서 확정한 줄만.
        kind='existing': 학생당 한 줄. kind='record': 학생관찰기록(한 학생 여러 줄 허용).
        req_id: 같은 요청이 두 번 와도(연속 클릭) 한 번만 넣는다."""
        self._editable()
        done = self._req_done(req_id)
        if done:
            return done
        kind = "record" if kind == "record" else "existing"
        d = self._db()
        rec = Records(d)
        rec.slot(gid, item)
        members = {m["student_no"]: m for m in d.members(gid)}
        seen, clean = set(), []
        for r in rows or []:
            sno, content = str(r.get("student_no") or ""), (r.get("content") or "").strip()
            m = members.get(sno)
            if not m:
                raise db.DbError(f"이 담당 명렬에 없는 학생이 있습니다({sno or '학생 없음'}).")
            if not m["active"]:
                raise db.DbError(f"{m['name']}: 비활성 학생에게는 넣을 수 없습니다.")
            if not content:
                raise db.DbError(f"{m['name']}: 내용이 비어 있습니다.")
            if kind == "existing" and sno in seen:
                raise db.DbError(f"{m['name']} 학생이 두 줄에 있습니다. 한 줄만 남겨 주세요.")
            seen.add(sno)
            clean.append({"student_no": sno, "content": content, "title": str(r.get("title") or ""),
                          "date": existing.norm_date(str(r.get("date") or ""))})
        if not clean:
            raise db.DbError("넣을 줄이 없습니다.")
        return self._req_save(req_id, {"count": self._rec().add_existing_bulk(gid, item, clean, kind), "students": len(seen)})

    def _req_done(self, req_id):
        """이미 끝낸 요청이면 그 결과(같은 버튼을 두 번 눌러도 한 번만)."""
        if not req_id:
            return None
        with self._ai_lock:
            return dict(getattr(self, "_reqs", {}).get(str(req_id)) or {}) or None

    def _req_save(self, req_id, result):
        if req_id:
            with self._ai_lock:
                reqs = getattr(self, "_reqs", None)
                if reqs is None:
                    reqs = self._reqs = {}
                reqs[str(req_id)] = {**result, "repeated": True}
                while len(reqs) > 50:
                    reqs.pop(next(iter(reqs)))
        return result

    @safe
    def finals_bulk_view(self, gid, item):
        """기존 완성문 → 최종안 일괄 보내기 확인 표."""
        return {"students": self._rec().finals_bulk_view(gid, item)}

    @safe
    def finals_from_existing(self, gid, item, picks, req_id=None):
        self._editable()
        done = self._req_done(req_id)
        if done:
            return done
        if not picks:
            raise db.DbError("보낼 학생이 없습니다.")
        n, undo = self._rec().finals_from_existing(gid, item, picks)
        self._finals_undo = {"year": config.load()["current_year"], "gid": gid, "item": item, "undo": undo}
        return self._req_save(req_id, {"count": n})

    @safe
    def finals_bulk_undo(self):
        """바로 앞의 '기존 완성문 → 최종안 일괄'을 되돌린다(그 뒤에 고치거나 마감한 학생은 그대로)."""
        self._editable()
        u = getattr(self, "_finals_undo", None)
        if not u or u["year"] != config.load()["current_year"]:
            raise db.DbError("되돌릴 일괄 보내기가 없습니다.")
        try:
            done, skipped = self._rec().undo_finals(u["gid"], u["item"], u["undo"])
        finally:
            self._finals_undo = None
        return {"count": done, "skipped": len(skipped)}

    # ---------- 자료 인박스 ----------
    def _ib(self) -> Inbox:
        return Inbox(self._db())

    @safe
    def inbox_list(self):
        return {"batches": self._ib().batches()}

    @safe
    def inbox_create(self, title, gid, item):
        self._editable()
        return {"id": self._ib().create(title, gid, item)}

    @safe
    def inbox_update(self, bid, data):
        self._editable()
        self._ib().update(bid, data or {})
        return {}

    @safe
    def inbox_delete(self, bid):
        self._editable()
        self._ib().delete(bid)
        return {}

    @safe
    def inbox_source_text(self, bid, text):
        self._editable()
        raw = roster.parse_text(text or "", delim="\t")
        if not raw:
            raise db.DbError("붙여넣은 내용이 없습니다. 엑셀에서 칸을 드래그해 복사한 뒤 붙여넣어 주세요.")
        return {"opts": self._ib().set_source(bid, raw, "paste"), "raw": raw}

    @safe
    def inbox_source_xlsx(self, bid, token=None, sheet=None):
        self._editable()
        raw, pick = self._read_xlsx(token, sheet)
        if pick or raw is None:
            return pick or {"ok": False, "cancelled": True}
        if not raw:
            raise db.DbError("고른 시트에 내용이 없습니다.")
        name = os.path.basename(self._last_xlsx)
        return {"opts": self._ib().set_source(bid, raw, "xlsx", name + (f" › {sheet}" if sheet else "")), "raw": raw}

    def _read_xlsx(self, token, sheet):
        """파일 하나 고르기 → (rows, None) / 시트가 여럿이면 (None, 고르기 정보) / 취소면 (None, None)."""
        if token:
            path = self._xlsx_path(token)
        else:
            res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Excel 파일 (*.xlsx)",))
            if not res:
                return None, None
            path = res[0] if isinstance(res, (list, tuple)) else res
        self._last_xlsx = path
        try:
            if token:
                return roster.parse_xlsx(path, sheet), None
            return self._xlsx_pick(path)
        except Exception:
            raise db.DbError("xlsx 파일을 열지 못했습니다. Excel에서 열려 있으면 닫고 다시 시도해 주세요.")

    # ----- 스캔 PDF -----
    @safe
    def clova_ready(self):
        cfg = config.load()
        missing = [label for k, label in (("clova_secret", "CLOVA Secret Key"), ("clova_url", "CLOVA Invoke URL")) if not cfg[k].strip()]
        return {"ready": not missing, "missing": missing}

    @safe
    def inbox_scan_pick(self, bid):
        self._editable()
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("PDF 파일 (*.pdf)",))
        if not res:
            return {"ok": False, "cancelled": True}
        path = res[0] if isinstance(res, (list, tuple)) else res
        if os.path.getsize(path) > ocr.MAX_FILE_BYTES:
            raise db.DbError("파일 크기가 50MB를 넘습니다. PDF를 나눠서 가져와 주세요.")
        return {"scan": self._ib().scan_set(bid, path, os.path.basename(path))}

    @safe
    def inbox_scan_ocr(self, bid, per):
        """백그라운드로 OCR. 진행은 ocr_progress / ocr_done / ocr_error / ocr_stopped 이벤트."""
        self._editable()
        cfg = config.load()
        if not (cfg["clova_url"].strip() and cfg["clova_secret"].strip()):
            raise db.DbError("CLOVA OCR 키가 없습니다. 설정 > 연결·모델에서 Secret Key와 Invoke URL을 넣어 주세요.")
        ib = self._ib()
        b = ib._editable_batch(bid)
        if not (b["meta"].get("scan") or {}).get("pages"):
            raise db.DbError("먼저 스캔 PDF를 고르세요.")
        with self._ai_lock:
            self._check_running()
            if not self._busy.acquire(blocking=False):
                raise db.DbError("다른 작업이 진행 중입니다.")
        self._ocr_stop.clear()
        year = config.load()["current_year"]

        def run():
            try:
                def prog(n, total_chunks, total_pages):
                    self._emit({"type": "ocr_progress", "bid": int(bid), "done": n, "total": total_chunks, "pages": total_pages})

                texts = ocr.ocr_pdf(str(scan.pdf_path(year, bid)), cfg["clova_url"].strip(), cfg["clova_secret"].strip(), cfg["ocr_lang"], prog, self._ocr_stop.is_set)
                Inbox(db.open_year(year)).scan_save_ocr(bid, texts, per)
                self._emit({"type": "ocr_done", "bid": int(bid), "pages": len(texts)})
            except ocr.Stopped:
                self._emit({"type": "ocr_stopped", "bid": int(bid)})
            except Exception as e:
                self._emit({"type": "ocr_error", "bid": int(bid), "message": str(e)})
            finally:
                self._busy.release()

        threading.Thread(target=run, daemon=True).start()
        return {}

    def inbox_ocr_stop(self):
        self._ocr_stop.set()
        return {"ok": True}

    @safe
    def inbox_scan_groups(self, bid, starts=None, skipped=None):
        return self._ib().scan_groups(bid, starts, skipped)

    @safe
    def inbox_scan_confirm(self, bid, starts, skipped):
        self._editable()
        return {"count": self._ib().scan_confirm(bid, starts, skipped)}

    @safe
    def inbox_page_image(self, bid, page):
        try:
            return {"src": scan.render_page(self._db().year, bid, page)}
        except FileNotFoundError:
            raise db.DbError("원본 PDF가 없습니다(묶음을 지웠거나 자료 폴더를 옮겼을 수 있습니다).")

    @safe
    def inbox_scan_text(self, bid, pages):
        return {"pages": self._ib().scan_raw_text(bid, pages or [])}

    @safe
    def inbox_preview(self, bid, opts):
        """opts.roles가 없으면(방향·머리글을 바꿈) 열 역할을 다시 짐작해 함께 돌려준다."""
        opts = dict(opts or {})
        out = {}
        if opts.get("structure", "multi") == "multi" and opts.get("roles") is None:
            out["roles"], out["neis"] = self._ib().guess(bid, opts)
            opts["roles"] = out["roles"]
        out["rows"] = self._ib().preview(bid, opts)
        return out

    @safe
    def inbox_import(self, bid, opts):
        self._editable()
        return {"count": self._ib().confirm_import(bid, opts or {})}

    @safe
    def inbox_view(self, bid):
        return self._ib().view(bid)

    @safe
    def inbox_set_student(self, row_id, sno):
        self._editable()
        self._ib().set_student(row_id, sno)
        return {}

    @safe
    def inbox_confirm_suggested(self, bid, row_ids=None):
        self._editable()
        return {"count": self._ib().confirm_suggested(bid, row_ids)}

    @safe
    def inbox_exclude(self, row_ids, reason="", on=True):
        self._editable()
        self._ib().exclude(row_ids, reason, bool(on))
        return {}

    @safe
    def inbox_edit_row(self, row_id, data):
        self._editable()
        self._ib().edit_row(row_id, data or {})
        return {}

    @safe
    def inbox_rematch(self, bid):
        self._editable()
        self._ib().rematch(bid)
        return {}

    @safe
    def inbox_stage(self, bid, stage, exclude_pending=False):
        self._editable()
        self._ib().to_stage(bid, stage, bool(exclude_pending))
        return {}

    @safe
    def ai_inbox_row(self, row_id, model_index=None):
        """인박스 행 한 건 정제. 학번·이름 없이 내용만 보낸다."""
        self._editable()
        ib = self._ib()
        r = ib._row(row_id)
        b = ib._editable_batch(r["batch_id"])
        cfg, model = self._model(model_index)
        pr = self._prompt("refine")
        key = ("inbox", r["id"])
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, prompts.build_system(pr["prompt"], pr["example"], 0), r["content"], cfg["privacy_block"])
            cid = ib.add_cand(r["id"], text, self._xm({"model": model, "op": "refine", "prompt_name": pr["name"], "prompt": pr["prompt"], "example": pr["example"]}), cost)
            ib.use_cand(r["id"], cid)  # 새 후보를 바로 '보낼 내용'으로(다른 후보·원문으로 바꿀 수 있음)
            return {"id": cid, "cost": cost, "run_cost": self._run_cost}
        finally:
            self._release(key)

    @safe
    def inbox_reorder(self, bid, row_ids):
        self._editable()
        self._ib().reorder(bid, row_ids)
        return {}

    @safe
    def inbox_use_cand(self, row_id, cand_id=None):
        self._editable()
        self._ib().use_cand(row_id, cand_id)
        return {}

    @safe
    def inbox_review(self, bid):
        return self._ib().review(bid)

    @safe
    def inbox_sent_info(self, bid):
        return self._ib().sent_info(bid)

    @safe
    def inbox_delete_sent(self, bid, confirm=None):
        """되돌릴 수 없는 삭제: 화면에서 '확인했어요'를 입력해야 한다(서버에서도 확인)."""
        self._editable()
        if (confirm or "").strip() != updater.CONFIRM_WORD:
            raise db.DbError(f"'{updater.CONFIRM_WORD}'를 입력해야 지웁니다.")
        return self._ib().delete_sent(bid)

    @safe
    def inbox_send(self, bid, closed_action="block"):
        self._editable()
        return self._ib().send(bid, closed_action)

    # ---------- 내보내기 ----------
    @safe
    def export_preview(self, gid, item, only_closed=False, order="no"):
        rec = self._rec()
        g, target = rec.slot(gid, item)
        return {"rows": rec.export_rows(gid, item, bool(only_closed), order), "target": target,
                "paired": bool(item == "subject" and rec.pair_groups(gid))}

    @safe
    def export_combined(self, gid, only_closed=False, order="no"):
        """1·2학기 합산 과목 합쳐 보기(보기 전용)."""
        return self._rec().export_combined(gid, bool(only_closed), order)

    @safe
    def export_copy(self, gid, item, only_closed, order, scope, header):
        rows = self._rec().export_rows(gid, item, bool(only_closed), order)
        export.write_clipboard(export.to_tsv(rows, scope, bool(header)))
        return {"count": len(rows)}

    @safe
    def export_xlsx(self, gid, item, only_closed, order, scope, default_name):
        rec = self._rec()
        rows = rec.export_rows(gid, item, bool(only_closed), order)
        result = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=default_name or "생기부.xlsx", file_types=("Excel 파일 (*.xlsx)",))
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export.write_xlsx(path, rows, scope, default_name.rsplit(".", 1)[0] if default_name else "생기부")
        except PermissionError:
            raise db.DbError("저장하지 못했습니다. 같은 파일이 Excel에서 열려 있으면 닫고 다시 시도해 주세요.")
        except ValueError as e:
            raise db.DbError(str(e))
        return {"path": path, "count": len(rows)}

    # ---------- 백업·자료 ----------
    @safe
    def save_now(self):
        """수동 저장: 화면의 남은 저장은 화면이 먼저 마치고, 여기서는 자료 파일에 확실히 기록한다."""
        year = config.load()["current_year"]
        if year and db.year_path(year).exists():
            db.open_year(year).checkpoint()
        return {}

    @safe
    def backup_now(self):
        name = backup.make("수동")
        if not name:
            raise db.DbError("백업할 자료가 아직 없습니다.")
        return {"name": name, "backups": backup.list_backups()}

    @safe
    def backups(self):
        return {"backups": backup.list_backups()}

    @safe
    def restore_backup(self, name):
        with self._maintenance("복원", take_busy=True):
            self._last_undo = None
            return backup.restore(name)

    @safe
    def delete_year(self, year, typed):
        year = int(year)
        if (typed or "").strip() != f"{year}학년도":
            raise db.DbError(f"확인 칸에 '{year}학년도'를 정확히 입력해 주세요.")
        with self._maintenance("학년도 자료 삭제", take_busy=True):
            self._last_undo = None
            if year not in db.list_years():
                raise db.DbError("그 학년도 자료가 없습니다.")
            backup.make("삭제전")
            db.close_all()
            backup.delete_year_files(year)
            cfg = config.load()
            if cfg["current_year"] == year:
                rest = db.list_years()
                config.save({"current_year": max(rest) if rest else 0, "setup_done": bool(rest)})
        return {}

    @safe
    def open_data_dir(self):
        path = str(data_dir())
        if platform.system() == "Windows":
            os.startfile(path)  # noqa: S606 - 사용자 데이터 폴더 열기
        elif platform.system() == "Darwin":
            subprocess.run(["open", path])
        return {}

    # ---------- 업데이트 ----------
    @safe
    def update_check(self):
        info = updater.check()
        if info.get("available"):
            self._update_info = info
        return info

    @safe
    def update_apply(self, confirm=None):
        info = self._update_info
        if not info:
            raise updater.UpdateError("새 버전 정보가 없습니다. 다시 확인해 주세요.")
        if info.get("warning") and (confirm or "").strip() != updater.CONFIRM_WORD:
            raise updater.UpdateError(f"이 업데이트는 안내를 읽고 '{updater.CONFIRM_WORD}'를 입력해야 진행합니다.")
        if not updater.can_apply():
            raise updater.UpdateError("Windows exe에서만 자동 업데이트할 수 있습니다.")
        if not info.get("sha256"):
            raise updater.UpdateError("이 릴리스에는 검증값(SHA-256)이 없어 자동 업데이트하지 않습니다. 릴리스 페이지에서 직접 내려받아 주세요.")
        if getattr(self, "_update_ready", ""):
            raise updater.UpdateError(f"이미 v{self._update_ready}로 바꿔 두었습니다. 앱을 종료한 뒤 다시 시작해 주세요.")
        self._maint_begin("업데이트", take_busy=True)

        def run():
            try:
                self._emit({"type": "update_progress", "stage": "backup"})
                try:
                    backup.make("업데이트전")
                except OSError as e:
                    updater.log(f"업데이트전 백업 실패: {e}")
                    raise updater.UpdateError("업데이트 전 백업을 만들지 못했습니다. 백신이나 다른 프로그램이 자료 파일을 쓰는 중일 수 있어요. 잠시 뒤 다시 시도해 주세요.") from e
                path = updater.download(info, lambda d, t: self._emit({"type": "update_progress", "stage": "download", "done": d, "total": t}))
                # 새 버전을 자동으로 켜지 않는다(학교 보안 프로그램이 막을 수 있음). exe만 바꿔 두고 다시 시작을 안내한다.
                # 이 앱은 실행 잠금을 그대로 쥐고 계속 쓸 수 있다.
                updater.swap_only(path)
                self._update_ready = info.get("version", "")
                self._emit({"type": "update_ready", "version": self._update_ready})
            except Exception as e:
                updater.log(f"업데이트 실패: {e}")
                self._emit({"type": "update_error", "message": str(e)})
            self._maint_end(take_busy=True)

        threading.Thread(target=run, daemon=True).start()
        return {}

    # ---------- 창 ----------
    def on_closing(self):
        """창 닫기: 화면에 남은 저장(최종안·성취기준·프롬프트·설정)을 먼저 마치게 하고 닫는다.
        화면이 응답하지 않을 때를 대비해, 몇 초 안에 다시 닫으면 바로 닫는다."""
        import time

        self.save_window()
        if self._close_ok or not self._window:
            return True
        now = time.time()
        if now - self._close_asked < 8:
            return True
        self._close_asked = now
        w = self._window
        threading.Thread(target=lambda: w.evaluate_js(
            "setTimeout(function(){ if (window.__beforeClose) window.__beforeClose(); else window.pywebview.api.close_app(); }, 0); 0"), daemon=True).start()
        return False

    def update_state(self):
        return {"ok": True, "ready": getattr(self, "_update_ready", "")}

    def close_app(self):
        self._close_ok = True
        if self._window:
            self._window.destroy()
        return {"ok": True}

    def save_window(self):
        w = self._window
        if not w:
            return
        try:
            geo = {"x": int(w.x), "y": int(w.y), "width": int(w.width), "height": int(w.height)}
            if geo["width"] > 400 and geo["height"] > 300:
                config.save({"window": geo})
        except Exception:
            pass
