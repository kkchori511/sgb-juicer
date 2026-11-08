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

from . import APP_NAME, MAKER, TAGLINE, VERSION, backup, config, db, export, openrouter, prompts, roster, updater, weights
from .records import Records, items_of
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
        d = self._db()
        rec = Records(d)
        role = d.role()
        groups = [g for g in d.groups() if role == "homeroom" or g["kind"] != "homeroom"]
        member_groups = d.student_groups()
        out = []
        todo_final = todo_close = todo_stale = 0
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
            active = [r for r in rows if r["active"]]
            out.append({
                **g,
                "items": items,
                "rows": rows,
                "summary": {"students": len(active), "item_total": len(active) * len(items), **counts},
            })
        todo = []
        empty = [g for g in out if g["total"] == 0]
        if empty:
            todo.append({"kind": "roster", "label": f"명렬 등록 {len(empty)}곳", "group_id": empty[0]["id"]})
        if todo_stale:
            todo.append({"kind": "stale", "label": f"채택 후 기록 변경 {todo_stale}건"})
        if todo_final:
            todo.append({"kind": "final", "label": f"최종안 만들기 {todo_final}건"})
        if todo_close:
            todo.append({"kind": "close", "label": f"마감 검토 {todo_close}건"})
        return {"role": role, "groups": out, "todo": todo, "schedules": d.schedules()}

    # ---------- 항목별 기록 ----------
    def _rec(self) -> Records:
        return Records(self._db())

    def _editable(self):
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
        return {"student": m, "target": target, "records": rec.records(gid, item, sno),
                "results": rec.slot_results(gid, item, sno), "final": final, "tags": rec.tags(),
                "weight_sum_check": config.load()["weight_sum_check"]}

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
    def edit_final(self, gid, item, sno, text):
        self._editable()
        self._rec().edit_final(gid, item, sno, text)
        return {}

    @safe
    def set_closed(self, gid, item, sno, closed):
        self._editable()
        self._rec().set_closed(gid, item, sno, bool(closed))
        return {}

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
        finally:
            self._release(key)
        meta = {"model": model, "op": op, "prompt": pr["prompt"], "example": pr["example"], "record_ids": [r["id"]]}
        nid, dropped = rec.add_result(r["group_id"], r["item"], r["student_no"], op, text, meta, cost, record_id=r["id"])
        return self._ai_out({"id": nid, "dropped": dropped, "cost": cost})

    @safe
    def ai_synth(self, gid, item, sno, record_ids, weights_map=None, model_index=None, sum_check=None):
        """선택한 기록들을 비중대로 종합 → 학생×항목 후보. 학번·이름 없이 내용과 비율만 보낸다."""
        self._editable()
        rec = self._rec()
        g, target = rec.slot(gid, item)
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
        system = prompts.build_system(pr["prompt"], pr["example"], target)
        user = prompts.build_synth_user([{"text": r["content"], "ratio": q} for r, q in zip(chosen, ratios)], target)
        key = ("slot", int(gid), item, str(sno))
        self._guard(key)
        try:
            text, cost = self._call_ai(cfg["openrouter_key"].strip(), model, system, user, cfg["privacy_block"])
        finally:
            self._release(key)
        meta = {"model": model, "op": "synth", "prompt": pr["prompt"], "example": pr["example"], "target": target,
                "record_ids": [r["id"] for r in chosen], "ratios": [round(q * 100, 1) for q in ratios], "sum_check": check}
        nid, dropped = rec.add_result(gid, item, sno, "synth", text, meta, cost)
        return self._ai_out({"id": nid, "dropped": dropped, "cost": cost, "ratios": meta["ratios"]})

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
        finally:
            self._release(key)
        meta = {"model": model, "op": "polish", "prompt": pr["prompt"], "example": pr["example"], "target": target, "from": "final"}
        nid, dropped = rec.add_result(gid, item, sno, "polish", text, meta, cost)
        return self._ai_out({"id": nid, "dropped": dropped, "cost": cost})

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
        return {"path": path, "count": len(rows)}

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
