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
from functools import wraps

import webview

from . import APP_NAME, MAKER, TAGLINE, VERSION, backup, config, db, openrouter, roster, updater
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
        except (db.DbError, updater.UpdateError, openrouter.LlmError) as e:
            return {"ok": False, "error": str(e)}
        except Exception as e:  # 알 수 없는 오류도 앱을 멈추지 않게
            return {"ok": False, "error": f"처리하지 못했습니다: {e.__class__.__name__}: {e}"}

    return inner


class Api:
    def __init__(self):
        self._window = None
        self._busy = threading.Lock()
        self._update_info = None

    def attach(self, window):
        self._window = window

    def _emit(self, payload: dict):
        if self._window:
            self._window.evaluate_js(f"window.onAppEvent({json.dumps(payload, ensure_ascii=False)})")

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
        d = db.open_year(year)
        d.set_role(role)
        config.save({"current_year": year})
        return {}

    @safe
    def switch_year(self, year):
        year = int(year)
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
        self._db().set_role(role)
        return {}

    @safe
    def finish_setup(self):
        config.save({"setup_done": True})
        return {}

    # ---------- 담당 ----------
    @safe
    def add_group(self, data):
        d = self._db()
        gid = d.add_group(
            data.get("kind"), data.get("name"), data.get("semester"), data.get("grade"), data.get("class_no"), data.get("level_scale", 5)
        )
        return {"id": gid, "groups": d.groups()}

    @safe
    def update_group(self, gid, data):
        d = self._db()
        d.update_group(gid, **(data or {}))
        return {"groups": d.groups()}

    @safe
    def delete_group(self, gid):
        d = self._db()
        d.delete_group(gid)
        return {"groups": d.groups()}

    # ---------- 명렬 ----------
    @safe
    def roster_from_text(self, text):
        rows = roster.parse_text(text)
        if not rows:
            raise db.DbError("붙여넣은 내용이 없습니다. 엑셀에서 학번·이름 칸을 복사해 주세요.")
        return {"raw": rows, **roster.detect(rows)}

    @safe
    def roster_from_xlsx(self):
        result = self._window.create_file_dialog(webview.OPEN_DIALOG, file_types=("Excel 파일 (*.xlsx)",))
        if not result:
            return {"ok": False, "cancelled": True}
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            rows = roster.parse_xlsx(path)
        except Exception:
            raise db.DbError("xlsx 파일을 열지 못했습니다. Excel에서 열려 있으면 닫고 다시 시도해 주세요.")
        if not rows:
            raise db.DbError("첫 번째 시트에 내용이 없습니다.")
        return {"raw": rows, "file": os.path.basename(path), **roster.detect(rows)}

    @safe
    def roster_build(self, gid, raw, header, columns):
        d = self._db()
        rows = roster.build_rows(raw, bool(header), columns or {})
        return {"rows": roster.validate(rows, d.group(gid), d.known_names([r["student_no"] for r in rows if r["student_no"]]))}

    @safe
    def roster_validate(self, gid, rows):
        d = self._db()
        for r in rows:
            r["student_no"] = str(r.get("student_no") or "").strip()
            r["name"] = str(r.get("name") or "").strip()
            for k in ("grade", "class_no", "number"):
                r[k] = roster._digits(r.get(k))
            r["level"] = str(r.get("level") or "").strip().upper()
            if r["student_no"] and not (r["grade"] and r["class_no"]):
                parts = roster.split_student_no(r["student_no"])
                if parts:
                    r["grade"], r["class_no"], r["number"] = (str(x) for x in parts)
        return {"rows": roster.validate(rows, d.group(gid), d.known_names([r["student_no"] for r in rows if r["student_no"]]))}

    @safe
    def roster_apply(self, gid, rows):
        d = self._db()
        checked = self.roster_validate(gid, rows)
        if not checked.get("ok"):
            return checked
        bad = [r for r in checked["rows"] if r["issues"]]
        if bad:
            raise db.DbError(f"확인이 필요한 행 {len(bad)}개를 먼저 고쳐 주세요.")
        result = d.apply_roster(gid, checked["rows"])
        return {**result, "groups": d.groups()}

    @safe
    def members(self, gid):
        return {"members": self._db().members(gid)}

    @safe
    def set_active(self, gid, student_nos, active, all_groups=False):
        d = self._db()
        n = d.set_active(gid, student_nos, bool(active), bool(all_groups))
        return {"changed": n, "groups": d.groups()}

    @safe
    def set_level(self, gid, student_no, level):
        self._db().set_level(gid, student_no, level)
        return {}

    # ---------- 일정·분량 ----------
    @safe
    def add_schedule(self, date, title):
        d = self._db()
        d.add_schedule(date, title)
        return {"schedules": d.schedules()}

    @safe
    def update_schedule(self, sid, date, title):
        d = self._db()
        d.update_schedule(sid, date, title)
        return {"schedules": d.schedules()}

    @safe
    def delete_schedule(self, sid):
        d = self._db()
        d.delete_schedule(sid)
        return {"schedules": d.schedules()}

    @safe
    def set_target(self, item, value):
        d = self._db()
        d.set_target(item, value)
        return {"targets": d.targets()}

    # ---------- 현황판 ----------
    @safe
    def dashboard(self):
        """0.1: 기록 기능 전이므로 모든 상태는 '기록 없음'. 화면 구조와 집계를 먼저 갖춘다."""
        d = self._db()
        role = d.role()
        groups = [g for g in d.groups() if role == "homeroom" or g["kind"] != "homeroom"]
        member_groups = d.student_groups()
        out = []
        for g in groups:
            members = d.members(g["id"])
            items = ["autonomy", "career", "behavior"] if g["kind"] == "homeroom" else [g["kind"]]
            rows = []
            for m in members:
                rows.append({
                    **m,
                    "status": {it: "none" for it in items},
                    "records": 0,
                    "final_bytes": None,
                    "others": [x for x in member_groups.get(m["student_no"], []) if x != g["id"]],
                    "senior_note": g["kind"] in ("homeroom", "club") and m["grade"] == 3,
                })
            active = [r for r in rows if r["active"]]
            out.append({
                **g,
                "items": items,
                "rows": rows,
                "summary": {
                    "students": len(active),
                    "item_total": len(active) * len(items),
                    "none": len(active) * len(items),
                    "progress": 0,
                    "final": 0,
                    "closed": 0,
                },
            })
        todo = []
        empty = [g for g in out if g["total"] == 0]
        if empty:
            todo.append({"kind": "roster", "label": f"명렬 등록 {len(empty)}곳", "group_id": empty[0]["id"]})
        return {"role": role, "groups": out, "todo": todo, "schedules": d.schedules()}

    # ---------- 백업·자료 ----------
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
        if not self._busy.acquire(blocking=False):
            raise db.DbError("다른 작업이 진행 중입니다.")
        try:
            return backup.restore(name)
        finally:
            self._busy.release()

    @safe
    def delete_year(self, year, typed):
        year = int(year)
        if (typed or "").strip() != f"{year}학년도":
            raise db.DbError(f"확인 칸에 '{year}학년도'를 정확히 입력해 주세요.")
        if year not in db.list_years():
            raise db.DbError("그 학년도 자료가 없습니다.")
        backup.make("삭제전")
        db.close_all()
        p = db.year_path(year)
        for f in (p, p.with_name(p.name + "-wal"), p.with_name(p.name + "-shm")):
            if f.exists():
                f.unlink()
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
        if not self._busy.acquire(blocking=False):
            raise updater.UpdateError("다른 작업이 진행 중입니다. 끝난 뒤 업데이트해 주세요.")

        def run():
            try:
                self._emit({"type": "update_progress", "stage": "backup"})
                backup.make("업데이트전")
                path = updater.download(info, lambda d, t: self._emit({"type": "update_progress", "stage": "download", "done": d, "total": t}))
                self._emit({"type": "update_progress", "stage": "restart"})
                db.close_all()
                updater.launch_swap(path)
                if self._window:
                    self._window.destroy()
            except Exception as e:
                self._emit({"type": "update_error", "message": str(e)})
            finally:
                self._busy.release()

        threading.Thread(target=run, daemon=True).start()
        return {}

    # ---------- 창 ----------
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
