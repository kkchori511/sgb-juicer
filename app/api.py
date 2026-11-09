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

from . import APP_NAME, MAKER, TAGLINE, VERSION, backup, config, db, export, ocr, openrouter, prompts, roster, scan, updater, weights
from .records import Records, items_of
from .inbox import Inbox
from .standards import Standards, check_level, read_hwpx_text, read_pdf_text, standards_rule
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
            return {"ok": False, "error": str(e)}
        except Exception as e:  # 알 수 없는 오류도 앱을 멈추지 않게
            return {"ok": False, "error": f"처리하지 못했습니다: {e.__class__.__name__}: {e}"}

    return inner


class Api:
    def __init__(self):
        self._window = None
        self._busy = threading.Lock()
        self._update_info = None
        self._run_cost = 0.0
        self._ai_keys = set()
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
        d.update_group(gid, **(data or {}))
        return {"groups": d.groups()}

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

    @safe
    def roster_from_xlsx(self):
        """명렬 파일을 여러 개 한꺼번에 고를 수 있다(xlsx·csv). 파일마다 읽은 결과와 오류를 돌려준다."""
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=True,
                                                 file_types=("명렬 파일 (*.xlsx;*.csv)", "Excel 파일 (*.xlsx)", "CSV 파일 (*.csv)"))
        if not result:
            return {"ok": False, "cancelled": True}
        paths = list(result) if isinstance(result, (list, tuple)) else [result]
        files, errors = [], []
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
                    rows = roster.parse_xlsx(path)
            except Exception:
                errors.append(f"{name}: 열지 못했습니다(Excel에서 열려 있으면 닫고 다시 시도)")
                continue
            if not rows:
                errors.append(f"{name}: 첫 번째 시트에 내용이 없습니다")
                continue
            files.append({"raw": rows, "file": name, **roster.detect(rows)})
        if not files:
            raise db.DbError("읽은 명렬이 없습니다.\n" + "\n".join(errors))
        return {"files": files, "errors": errors}

    def _members_map(self, d, gid):
        return {m["student_no"]: bool(m["active"]) for m in d.members(gid)}

    @safe
    def roster_build(self, gid, raw, header, columns, add=False):
        d = self._db()
        rows = roster.build_rows(raw, bool(header), columns or {})
        return {"rows": roster.validate(rows, d.group(gid), d.known_names([r["student_no"] for r in rows if r["student_no"]]),
                                        self._members_map(d, gid) if add else None)}

    @safe
    def roster_validate(self, gid, rows, add=False):
        d = self._db()
        for r in rows:
            r["student_no"] = str(r.get("student_no") or "").strip()
            r["name"] = str(r.get("name") or "").strip()
            for k in ("grade", "class_no", "number"):
                r[k] = roster._digits(r.get(k))
            r["level"] = str(r.get("level") or "").strip().upper()
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
                 "number": str(m["number"] or ""), "level": ""} for m in d.members(src_gid) if m["active"]]
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
        g, target = rec.slot(gid, item)
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
        return {"student": m, "target": target, "records": rec.records(gid, item, sno),
                "results": rec.slot_results(gid, item, sno), "final": final, "tags": rec.tags(),
                "weight_sum_check": config.load()["weight_sum_check"], "standards": std}

    @safe
    def add_record(self, gid, item, sno, data):
        self._editable()
        return {"id": self._rec().add_record(gid, item, sno, data or {})}

    @safe
    def update_record(self, rid, data):
        self._editable()
        self._rec().update_record(rid, data or {})
        return {}

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
    def set_closed(self, gid, item, sno, closed):
        self._editable()
        self._rec().set_closed(gid, item, sno, bool(closed))
        return {}

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

    def _call_ai(self, key, model, system, user, privacy):
        text, cost = openrouter.chat(key, model, system, user, privacy)
        if not text.strip():
            raise openrouter.LlmError("AI가 빈 결과를 돌려주었습니다. 다시 시도하거나 다른 모델을 고르세요.")
        self._run_cost += cost
        return text, cost

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
        """기록 한 건: 누가기록은 정제(refine), 이미 쓴 생기부는 다듬기(polish). 내용만 보낸다."""
        self._editable()
        rec = self._rec()
        r = rec.record(rid)
        rec.require_open(r["group_id"], r["item"], r["student_no"])
        rec.check_room(r["group_id"], r["item"], r["student_no"], r["id"])
        cfg, model = self._model(model_index)
        op = "polish" if r["kind"] == "existing" else "refine"
        pr = prompts.merged(cfg["prompts"])[r["item"]][op]
        _, target = rec.slot(r["group_id"], r["item"])
        system = prompts.build_system(pr["prompt"], pr["example"], target if op == "polish" else 0)
        key = ("record", r["id"])
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, system, r["content"], cfg["privacy_block"])
            meta = {"model": model, "op": op, "prompt": pr["prompt"], "example": pr["example"], "record_ids": [r["id"]]}
            nid, dropped = rec.add_result(r["group_id"], r["item"], r["student_no"], op, text, meta, cost, record_id=r["id"])
            return self._ai_out({"id": nid, "dropped": dropped, "cost": cost})
        finally:
            self._release(key)

    @safe
    def ai_synth(self, gid, item, sno, record_ids, weights_map=None, model_index=None, sum_check=None, std=None):
        """선택한 기록들을 비중대로 종합 → 학생×항목 후보. 학번·이름 없이 내용과 비율만 보낸다.
        std(세특만): {"text": 이번에 쓸 성취기준, "level": 성취수준} — 있으면 성취기준 관점·수준 반영."""
        self._editable()
        rec = self._rec()
        g, target = rec.slot(gid, item)
        std_rule, std_meta = self._std_rule(g, item, std, only=False)
        rec.require_open(gid, item, sno)
        rec.check_room(gid, item, sno)
        ids = [int(x) for x in record_ids or []]
        recs = {r["id"]: r for r in rec.records(gid, item, sno)}
        chosen = [recs[i] for i in ids if i in recs]
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
        pr = prompts.merged(cfg["prompts"])[item]["synth"]
        system = prompts.build_system(pr["prompt"] + std_rule, pr["example"], target)
        user = prompts.build_synth_user([{"text": r["content"], "ratio": q} for r, q in zip(chosen, ratios)], target)
        key = ("slot", int(gid), item, str(sno))
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, system, user, cfg["privacy_block"])
            meta = {"model": model, "op": "synth", "prompt": pr["prompt"], "example": pr["example"], "target": target,
                    "record_ids": [r["id"] for r in chosen], "ratios": [round(q * 100, 1) for q in ratios], "sum_check": check, **std_meta}
            nid, dropped = rec.add_result(gid, item, sno, "synth", text, meta, cost)
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

    @safe
    def ai_standards_only(self, gid, item, sno, std, model_index=None):
        """기록이 없는 학생: 성취기준(과 성취수준)만으로 세특 후보를 만든다. 학번·이름은 보내지 않는다."""
        self._editable()
        rec = self._rec()
        g, target = rec.slot(gid, item)
        rec.require_open(gid, item, sno)
        rec.check_room(gid, item, sno)
        rule, meta = self._std_rule(g, item, std, only=True)
        cfg, model = self._model(model_index)
        pr = prompts.merged(cfg["prompts"])[item]["synth"]
        key = ("slot", int(gid), item, str(sno))
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, prompts.build_system(pr["prompt"] + rule, pr["example"], target),
                                       "(누가기록 없음 — 성취기준과 성취수준으로만 작성)", cfg["privacy_block"])
            meta.update({"model": model, "op": "synth", "prompt": pr["prompt"], "example": pr["example"], "target": target})
            nid, dropped = rec.add_result(gid, item, sno, "synth", text, meta, cost)
            return self._ai_out({"id": nid, "dropped": dropped, "cost": cost})
        finally:
            self._release(key)

    # ---------- 성취기준 ----------
    @safe
    def standards_overview(self):
        return {"subjects": Standards(self._db()).overview()}

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
        _, target = rec.slot(gid, item)
        rec.require_open(gid, item, sno)
        f = rec.final(gid, item, sno)
        if not (f and f["text"].strip()):
            raise db.DbError("다듬을 최종안이 없습니다.")
        rec.check_room(gid, item, sno)
        cfg, model = self._model(model_index)
        pr = prompts.merged(cfg["prompts"])[item]["polish"]
        key = ("slot", int(gid), item, str(sno))
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, prompts.build_system(pr["prompt"], pr["example"], target), f["text"], cfg["privacy_block"])
            meta = {"model": model, "op": "polish", "prompt": pr["prompt"], "example": pr["example"], "target": target, "from": "final"}
            nid, dropped = rec.add_result(gid, item, sno, "polish", text, meta, cost)
            return self._ai_out({"id": nid, "dropped": dropped, "cost": cost})
        finally:
            self._release(key)

    @safe
    def run_cost(self):
        return {"run_cost": self._run_cost}

    # ---------- 프롬프트 ----------
    @safe
    def prompts_get(self):
        return {"prompts": prompts.merged(config.load()["prompts"]), "defaults": prompts.DEFAULT_PROMPTS,
                "items": prompts.ITEM_NAMES, "ops": prompts.OP_NAMES}

    @safe
    def prompts_save(self, item, op, prompt, example):
        if item not in prompts.ITEMS or op not in prompts.OPS:
            raise db.DbError("항목이 올바르지 않습니다.")
        saved = config.load()["prompts"]
        saved.setdefault(item, {})[op] = {"prompt": prompt or "", "example": example or ""}
        config.save({"prompts": saved})
        return {}

    @safe
    def prompts_reset(self, item, op):
        saved = config.load()["prompts"]
        if item in saved and op in saved[item]:
            del saved[item][op]
        config.save({"prompts": saved})
        return {"prompt": prompts.DEFAULT_PROMPTS[item][op]}

    # ---------- 이미 쓴 생기부 일괄 넣기 ----------
    @safe
    def existing_parse(self, gid, item, text=None, from_xlsx=False):
        d = self._db()
        rec = Records(d)
        rec.slot(gid, item)
        if from_xlsx:
            res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Excel 파일 (*.xlsx)",))
            if not res:
                return {"ok": False, "cancelled": True}
            path = res[0] if isinstance(res, (list, tuple)) else res
            raw = roster.parse_xlsx(path)
        else:
            raw = roster.parse_text(text or "", delim="\t")
        if not raw:
            raise db.DbError("내용이 없습니다. 엑셀에서 학번과 생기부 내용 칸을 복사해 주세요.")
        det = roster.detect(raw)
        cols = det["columns"]
        # 내용 열: 학번·이름이 아닌 열 중 글이 가장 긴 열
        body = raw[1:] if det["header"] else raw
        cands = [i for i in range(len(raw[0])) if i not in (cols["student_no"], cols["name"])]
        content_col = max(cands, key=lambda i: sum(len(r[i]) for r in body if i < len(r)), default=None)
        return {"raw": raw, "header": det["header"], "no_col": cols["student_no"], "name_col": cols["name"], "content_col": content_col}

    @safe
    def existing_build(self, gid, item, raw, header, no_col, name_col, content_col):
        d = self._db()
        rec = Records(d)
        rec.slot(gid, item)
        members = {m["student_no"]: m for m in d.members(gid)}
        body = raw[1:] if header else raw
        rows = []
        seen = {}
        for i, r in enumerate(body):
            get = lambda c: (r[int(c)].strip() if c is not None and c != "" and int(c) < len(r) else "")
            no = get(no_col).replace(" ", "")
            rows.append({"row": i + 1, "student_no": no, "name": get(name_col), "content": get(content_col)})
            seen[no] = seen.get(no, 0) + 1
        for r in rows:
            issues = []
            m = members.get(r["student_no"])
            if not r["student_no"]:
                issues.append("학번 없음")
            elif not m:
                issues.append("이 담당 명렬에 없는 학번")
            elif not m["active"]:
                issues.append("비활성 학생")
            elif rec.is_closed(gid, item, r["student_no"]):
                issues.append("마감된 학생")
            if seen.get(r["student_no"], 0) > 1 and r["student_no"]:
                issues.append("학번 중복")
            if not r["content"]:
                issues.append("내용 없음")
            notes = []
            if m and r["name"] and r["name"] != m["name"]:
                issues.append(f"이름 불일치(명렬: {m['name']})")
            if m:
                r["matched_name"] = m["name"]
            r["issues"], r["notes"] = issues, notes
        return {"rows": rows}

    @safe
    def existing_apply(self, gid, item, rows):
        self._editable()
        built = self.existing_build(gid, item, [["", "", ""]] + [[x.get("student_no", ""), x.get("name", ""), x.get("content", "")] for x in rows], True, 0, 1, 2)
        if not built.get("ok"):
            return built
        bad = [r for r in built["rows"] if r["issues"]]
        if bad:
            raise db.DbError(f"확인이 필요한 행 {len(bad)}개를 고치거나 빼 주세요. 모든 행이 확실히 매칭되어야 넣을 수 있습니다.")
        return {"count": self._rec().add_existing_bulk(gid, item, built["rows"])}

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
    def inbox_source_xlsx(self, bid):
        self._editable()
        res = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Excel 파일 (*.xlsx)",))
        if not res:
            return {"ok": False, "cancelled": True}
        path = res[0] if isinstance(res, (list, tuple)) else res
        try:
            raw = roster.parse_xlsx(path)
        except Exception:
            raise db.DbError("xlsx 파일을 열지 못했습니다. Excel에서 열려 있으면 닫고 다시 시도해 주세요.")
        if not raw:
            raise db.DbError("첫 번째 시트에 내용이 없습니다.")
        return {"opts": self._ib().set_source(bid, raw, "xlsx", os.path.basename(path)), "raw": raw}

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
        rows = self._ib().preview(bid, opts or {})
        return {"rows": rows}

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
    def inbox_stage(self, bid, stage):
        self._editable()
        self._ib().to_stage(bid, stage)
        return {}

    @safe
    def ai_inbox_row(self, row_id, model_index=None):
        """인박스 행 한 건 정제. 학번·이름 없이 내용만 보낸다."""
        self._editable()
        ib = self._ib()
        r = ib._row(row_id)
        b = ib._editable_batch(r["batch_id"])
        cfg, model = self._model(model_index)
        pr = prompts.merged(cfg["prompts"])[b["item"]]["refine"]
        key = ("inbox", r["id"])
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, prompts.build_system(pr["prompt"], pr["example"], 0), r["content"], cfg["privacy_block"])
            cid = ib.add_cand(r["id"], text, {"model": model, "op": "refine", "prompt": pr["prompt"], "example": pr["example"]}, cost)
            ib.use_cand(r["id"], cid)  # 새 후보를 바로 '보낼 내용'으로(다른 후보·원문으로 바꿀 수 있음)
            return {"id": cid, "cost": cost, "run_cost": self._run_cost}
        finally:
            self._release(key)

    @safe
    def inbox_use_cand(self, row_id, cand_id=None):
        self._editable()
        self._ib().use_cand(row_id, cand_id)
        return {}

    @safe
    def inbox_review(self, bid):
        return self._ib().review(bid)

    @safe
    def inbox_send(self, bid, closed_action="block"):
        self._editable()
        return self._ib().send(bid, closed_action)

    # ---------- 내보내기 ----------
    @safe
    def export_preview(self, gid, item, only_closed=False, order="no"):
        rec = self._rec()
        g, target = rec.slot(gid, item)
        return {"rows": rec.export_rows(gid, item, bool(only_closed), order), "target": target}

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
    def update_apply(self):
        info = self._update_info
        if not info:
            raise updater.UpdateError("새 버전 정보가 없습니다. 다시 확인해 주세요.")
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
                backup.make("업데이트전")
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
