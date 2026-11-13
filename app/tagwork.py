"""태그 AI 변환(태그별 기록 › [이 태그 AI 변환]). 설계: docs/plan/tag-flow.md

흐름: 시험(기록 한 건으로 프롬프트를 바꿔 가며 후보 3칸) → 확정(그 후보로 기록을 바꾸고, 후보를 만든 단계를 이 태그 설정으로)
→ 나머지 변환(확정 단계를 대상마다 그대로 재현, 결과는 기록을 바꾸지 않는 후보) → 검토 표에서 체크한 것만 반영 → 반영 묶음 되돌리기.

- 단계(chain): {"src": "original"|"current", "steps": [{"prompt", "example", "request"}]}
  첫 단계는 src 글(처음 원문=records.original 또는 지금 내용)에 prompt를 적용, 다음 단계는 앞 결과에 request(짧은 요청)를 적용한다.
- 기록 내용 버전(records.content_ver)으로 '만든 뒤 원문이 바뀌었는지'를 확인한다. AI를 기다리는 동안 DB를 잡고 있지 않는다.
- 기록·태그가 지워져도 이력은 남긴다(외래 키 없음).
"""
import json
import uuid

from . import prompts
from .db import DbError
from .records import Records

TRIAL_MAX = 3

CONTINUE_RULE = ("\n\n[이어서 고치기]\n- 주어진 글은 앞 단계에서 만든 결과다. 아래 요청대로만 고치고, 위 지침(문체·쓰지 않는 것·출력 형식)은 그대로 지킨다.\n"
                 "- 요청과 관계없는 문장은 되도록 그대로 둔다. 글에 없는 사실을 지어내지 않는다.\n<요청>\n{req}\n</요청>")
FIRST_REQ_RULE = ("\n\n[이번 추가 요구 사항]\n<요청>\n{req}\n</요청>\n- 위 요청을 반영하되, 앞의 규칙(쓰지 않는 것, 없는 사실 지어내지 않기, 출력 형식)이 항상 우선한다.")


def _j(s, default):
    try:
        v = json.loads(s) if s else default
    except (TypeError, ValueError):
        return default
    return v if v is not None else default


def norm_chain(chain):
    """화면에서 온 단계를 정리한다. 빈 단계·빈 프롬프트는 막는다."""
    chain = chain or {}
    src = "current" if chain.get("src") == "current" else "original"
    steps = []
    for i, s in enumerate(chain.get("steps") or []):
        s = s or {}
        step = {"prompt": str(s.get("prompt") or "").strip(), "example": str(s.get("example") or "").strip(),
                "request": str(s.get("request") or "").strip()[:1000]}
        if i == 0 and not step["prompt"]:
            raise DbError("프롬프트(지침)를 입력해 주세요.")
        if i > 0 and not (step["request"] or step["prompt"]):
            raise DbError("이어서 고칠 요청을 입력해 주세요.")
        steps.append(step)
    if not steps:
        raise DbError("프롬프트(지침)를 입력해 주세요.")
    if len(steps) > 6:
        raise DbError("단계가 너무 많습니다(6단계까지). 처음 원문에서 프롬프트를 고쳐 다시 시험해 주세요.")
    return {"src": src, "steps": steps}


def effective(chain, i):
    """i번째 단계에 쓰는 지침·예시: 그 단계까지 마지막으로 전체를 고친 단계의 것(이어 고칠 때 그대로 이어짐)."""
    steps = chain["steps"]
    for j in range(i, -1, -1):
        if steps[j]["prompt"]:
            return steps[j]["prompt"], steps[j]["example"]
    return steps[0]["prompt"], steps[0]["example"]


def step_system(chain, i):
    """i번째 단계에 보낼 시스템 글. 이어 고치는 단계는 전체 프롬프트를 새로 주지 않았으면 앞 단계 지침을 그대로 쓴다."""
    s = chain["steps"][i]
    base, example = effective(chain, i)
    system = prompts.build_system(base, example, 0)
    if i == 0:
        return system + (FIRST_REQ_RULE.format(req=s["request"]) if s["request"] else "")
    return system + (CONTINUE_RULE.format(req=s["request"]) if s["request"] else "")


def signature(chain):
    return json.dumps(chain, ensure_ascii=False, sort_keys=True)


class TagWork:
    def __init__(self, d):
        self.d = d
        self.rec = Records(d)

    # ---------- 작업 ----------
    def work_for_tag(self, tag_id, create=True):
        """태그의 작업(없으면 만든다). 한 태그에 작업 하나를 이어 쓴다. create=False면 없을 때 None(보관 학년도)."""
        tag_id = int(tag_id)
        t = self.d.q("SELECT id, name FROM tags WHERE id=?", (tag_id,))
        if not t:
            raise DbError("태그를 찾지 못했습니다.")
        rows = self.d.q("SELECT * FROM tag_works WHERE tag_id=? ORDER BY id DESC LIMIT 1", (tag_id,))
        if rows:
            w = rows[0]
            if w["tag_name"] != t[0]["name"]:
                with self.d.tx() as c:
                    c.execute("UPDATE tag_works SET tag_name=? WHERE id=?", (t[0]["name"], w["id"]))
                w["tag_name"] = t[0]["name"]
            return self._work_out(w)
        if not create:
            return None
        with self.d.tx() as c:
            wid = c.execute("INSERT INTO tag_works(tag_id, tag_name) VALUES(?,?)", (tag_id, t[0]["name"])).lastrowid
        return self.work(wid)

    def work(self, wid):
        rows = self.d.q("SELECT * FROM tag_works WHERE id=?", (int(wid),))
        if not rows:
            raise DbError("태그 작업을 찾지 못했습니다.")
        return self._work_out(rows[0])

    def _work_out(self, w):
        return {**w, "draft": _j(w["draft"], {}), "confirmed": _j(w["confirmed"], None) or None}

    def save_draft(self, wid, draft):
        d = draft or {}
        keep = {k: str(d.get(k) or "")[:20000] for k in ("prompt", "example", "lib_id", "lib_name")}
        with self.d.tx() as c:  # 번호표(_vers)는 같은 트랜잭션에서 읽어 그대로 둔다(후보 저장과 겹쳐도 잃지 않게)
            row = c.execute("SELECT draft FROM tag_works WHERE id=?", (int(wid),)).fetchone()
            if not row:
                raise DbError("태그 작업을 찾지 못했습니다.")
            old = _j(row[0], {})
            if old.get("_vers"):
                keep["_vers"] = old["_vers"]
            c.execute("UPDATE tag_works SET draft=?, updated_at=datetime('now','localtime') WHERE id=?",
                      (json.dumps(keep, ensure_ascii=False), int(wid)))
        return keep

    # ---------- 기록 ----------
    def record_info(self, rid):
        r = self.rec.record(rid)
        return r

    def check_target(self, r):
        """AI를 부르거나 반영하기 전에: 마감·비활성·담당에서 빠진 학생은 막는다."""
        self.rec.require_open(r["group_id"], r["item"], r["student_no"])
        m = self.d.q("SELECT active FROM memberships WHERE group_id=? AND student_no=?", (r["group_id"], r["student_no"]))
        if not m:
            raise DbError("담당 명렬에 없는 학생의 기록입니다.")
        if not m[0]["active"]:
            raise DbError("비활성 학생의 기록입니다.")

    def source_text(self, r, src):
        return (r["original"] if src == "original" and r.get("original") else r["content"]) or ""

    # ---------- 시험 후보 ----------
    def trials(self, wid, rid=None):
        args = [int(wid)]
        sql = "SELECT * FROM tag_cands WHERE work_id=? AND kind='trial'"
        if rid is not None:
            sql += " AND record_id=?"
            args.append(int(rid))
        rows = self.d.q(sql + " ORDER BY id", tuple(args))
        sigs = self._ver_map(wid)
        return [self._cand_out(x, sigs) for x in rows]

    def _ver_map(self, wid):
        """같은 단계(프롬프트·요청·원문 종류)면 같은 번호. 처음 나온 순서대로 1, 2, 3…을 작업에 저장해 두어 후보가 지워져도 번호가 바뀌지 않는다."""
        rows = self.d.q("SELECT draft FROM tag_works WHERE id=?", (int(wid),))
        vers = dict(_j(rows[0]["draft"], {}).get("_vers") or {}) if rows else {}
        for x in self.d.q("SELECT steps FROM tag_cands WHERE work_id=? ORDER BY id", (int(wid),)):  # 예전 자료(번호 저장 전)
            if x["steps"] not in vers:
                vers[x["steps"]] = max(vers.values() or [0]) + 1
        return vers

    def _ver_of(self, c, wid, sig):
        """트랜잭션 안에서: 이 단계의 번호(없으면 새로 매겨 저장)."""
        row = c.execute("SELECT draft FROM tag_works WHERE id=?", (int(wid),)).fetchone()
        draft = _j(row[0] if row else "{}", {})
        vers = dict(draft.get("_vers") or {})
        if sig not in vers:
            for x in c.execute("SELECT steps FROM tag_cands WHERE work_id=? ORDER BY id", (int(wid),)):
                if x[0] not in vers:
                    vers[x[0]] = max(vers.values() or [0]) + 1
            if sig not in vers:
                vers[sig] = max(vers.values() or [0]) + 1
            draft["_vers"] = vers
            c.execute("UPDATE tag_works SET draft=? WHERE id=?", (json.dumps(draft, ensure_ascii=False), int(wid)))
        return vers[sig]

    def _cand_out(self, x, sigs=None):
        chain = _j(x["steps"], {"src": "original", "steps": []})
        return {**{k: x[k] for k in ("id", "work_id", "record_id", "kind", "run_id", "parent_id", "input_src", "input_text",
                                      "record_ver", "record_text", "text", "edited", "checked", "locked", "status", "error",
                                      "model", "cost", "created_at")},
                "chain": chain, "meta": _j(x["meta"], {}), "ver_no": (sigs or {}).get(x["steps"])}

    def trial_room(self, wid, rid):
        rows = self.d.q("SELECT id, locked FROM tag_cands WHERE work_id=? AND record_id=? AND kind='trial' ORDER BY id", (int(wid), int(rid)))
        if len(rows) >= TRIAL_MAX and all(r["locked"] for r in rows):
            raise DbError("시험 후보 3개가 모두 잠겨 있습니다. 하나를 잠금 해제하거나 지운 뒤 다시 해 주세요.")

    def add_trial(self, wid, r, chain, parent_id, input_src, input_text, text, model, cost, meta, base=None, alive=None):
        """시험 후보를 넣고, 3개를 넘으면 잠기지 않은 가장 오래된 시험 후보를 지운다. 반환: (새 id, 지운 id)
        base: 원자료 기준(record_ver, record_text). 이어 고친 후보는 앞 후보의 기준을 그대로 물려받는다."""
        rv, rt = base if base else (r.get("content_ver") or 0, r["content"])
        with self.d.tx() as c:
            if alive:
                alive()  # [바로 중지]가 저장 직전에 들어왔으면 여기서 멈춘다
            now = c.execute("SELECT content_ver, content FROM records WHERE id=?", (r["id"],)).fetchone()
            if not now or ((now[0] or 0), now[1]) != ((rv or 0), rt):
                raise DbError("변환하는 동안 기록이 바뀌어 후보를 저장하지 않았습니다. 다시 시험해 주세요.")
            self._ver_of(c, wid, signature(chain))
            rows = [dict(x) for x in c.execute(
                "SELECT id, locked FROM tag_cands WHERE work_id=? AND record_id=? AND kind='trial' ORDER BY id", (int(wid), r["id"]))]
            dropped = None
            if len(rows) >= TRIAL_MAX:
                victim = next((x for x in rows if not x["locked"]), None)
                if victim is None:
                    raise DbError("시험 후보 3개가 모두 잠겨 있습니다.")
                c.execute("DELETE FROM tag_cands WHERE id=?", (victim["id"],))
                dropped = victim["id"]
            nid = c.execute(
                "INSERT INTO tag_cands(work_id, record_id, kind, parent_id, steps, input_src, input_text, record_ver, record_text, text, model, cost, meta) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(wid), r["id"], "trial", parent_id, signature(chain), input_src, input_text, rv, rt,
                 text, model, float(cost or 0), json.dumps(meta or {}, ensure_ascii=False))).lastrowid
        return nid, dropped

    def cand(self, cid):
        rows = self.d.q("SELECT * FROM tag_cands WHERE id=?", (int(cid),))
        if not rows:
            raise DbError("후보를 찾지 못했습니다.")
        return self._cand_out(rows[0], self._ver_map(rows[0]["work_id"]))

    def lock_cand(self, cid, locked):
        with self.d.tx() as c:
            c.execute("UPDATE tag_cands SET locked=? WHERE id=? AND kind='trial'", (1 if locked else 0, int(cid)))

    def delete_trial(self, cid):
        with self.d.tx() as c:
            c.execute("DELETE FROM tag_cands WHERE id=? AND kind='trial'", (int(cid),))

    # ---------- 확정 ----------
    def confirm(self, cid, apply=True):
        """시험 후보를 확정: 그 후보를 만든 단계가 이 태그 설정이 되고, apply면 그 기록에 반영한다."""
        x = self.cand(cid)
        if x["kind"] != "trial" or x["status"] != "ok":
            raise DbError("시험 후보만 확정할 수 있습니다.")
        conf = {"cand_id": x["id"], "record_id": x["record_id"], "chain": x["chain"], "ver_no": x["ver_no"]}
        out = {"applied": None}
        if apply:
            out["applied"] = self.apply(x["work_id"], [x["id"]])
        with self.d.tx() as c:
            c.execute("UPDATE tag_works SET confirmed=?, updated_at=datetime('now','localtime') WHERE id=?",
                      (json.dumps({**conf, "at": self.d.q("SELECT datetime('now','localtime') t")[0]["t"]}, ensure_ascii=False), x["work_id"]))
        return out

    # ---------- 나머지 변환 ----------
    def plan(self, wid, role, flt):
        """지금 화면 조건의 대상 목록. 체크 기본값: 학생관찰기록이고 이 작업에서 반영한 적 없으면 체크."""
        w = self.work(wid)
        view = self.rec.tag_view(role, w["tag_id"], flt or {})
        applied = self._applied_records(wid)
        done = self._latest_ok_bulk(wid)
        items = {}
        out = []
        for r in view["records"]:
            why = ""
            if r["closed"]:
                why = "마감"
            elif not r["active"] or r.get("gone"):
                why = "비활성"
            kind = r["kind"]
            items.setdefault(r["slot_label"], 0)
            items[r["slot_label"]] += 1
            out.append({"id": r["id"], "student_no": r["student_no"], "name": r["name"], "grade": r["grade"], "class_no": r["class_no"],
                        "number": r["number"], "slot_label": r["slot_label"], "group_id": r["group_id"], "item": r["item"],
                        "kind": kind, "title": r.get("title") or "", "seq": r.get("seq"), "content": r["content"][:200], "bytes": r["bytes"],
                        "blocked": why, "applied": r["id"] in applied, "has_bulk": r["id"] in done,
                        "default": not why and kind == "record" and r["id"] not in applied})
        costs = [x["cost"] / max(1, len(_j(x["steps"], {}).get("steps") or [1]))
                 for x in self.d.q("SELECT cost, steps FROM tag_cands WHERE work_id=? AND status='ok' AND cost>0", (int(wid),))]
        return {"work": w, "targets": out, "items": items, "cost_per_call": (sum(costs) / len(costs)) if costs else None}

    def _applied_records(self, wid):
        return {x["record_id"] for x in self.d.q("SELECT record_id FROM tag_applies WHERE work_id=? AND undone_at IS NULL", (int(wid),))}

    def _latest_ok_bulk(self, wid):
        return {x["record_id"] for x in self.d.q("SELECT record_id FROM tag_cands WHERE work_id=? AND kind='bulk' AND status='ok'", (int(wid),))}

    def create_run(self, wid, record_ids, flt, role):
        w = self.work(wid)
        if not w["confirmed"]:
            raise DbError("먼저 시험 후보 하나를 [확정]해 주세요.")
        ids = []
        for x in record_ids or []:
            if int(x) not in ids:
                ids.append(int(x))
        if not ids:
            raise DbError("변환할 기록을 고르세요.")
        # 지금 이 태그·조건의 대상인지 서버에서 다시 확인(화면이 오래됐거나 다른 태그 기록이 섞이지 않게)
        if w["tag_id"] is None or not self.d.q("SELECT 1 FROM tags WHERE id=?", (w["tag_id"],)):
            raise DbError("태그가 지워져 새로 변환할 수 없습니다.")
        view = {r["id"]: r for r in self.rec.tag_view(role, w["tag_id"], flt or {})["records"]}
        bad = [i for i in ids if i not in view]
        if bad:
            raise DbError(f"대상이 바뀌었습니다({len(bad)}건이 지금 조건에 없음). [대상 다시 불러오기]를 눌러 주세요.")
        blocked = [i for i in ids if view[i]["closed"] or not view[i]["active"] or view[i].get("gone")]
        if blocked:
            raise DbError(f"마감·비활성 기록 {len(blocked)}건이 들어 있습니다. [대상 다시 불러오기]를 눌러 주세요.")
        slots = {(view[i]["group_id"], view[i]["item"]) for i in ids}
        if len(slots) > 1:
            raise DbError("서로 다른 항목(담당)의 기록이 섞여 있습니다. 위 항목 필터로 하나만 골라 나눠 실행해 주세요.")
        with self.d.tx() as c:
            rid = c.execute("INSERT INTO tag_runs(work_id, steps, filter, targets) VALUES(?,?,?,?)",
                            (int(wid), signature(w["confirmed"]["chain"]), json.dumps(flt or {}, ensure_ascii=False), json.dumps(ids))).lastrowid
        return self.run(rid)

    def run(self, run_id):
        rows = self.d.q("SELECT * FROM tag_runs WHERE id=?", (int(run_id),))
        if not rows:
            raise DbError("변환 실행을 찾지 못했습니다.")
        x = rows[0]
        return {**x, "chain": _j(x["steps"], {}), "targets": _j(x["targets"], []), "filter": _j(x["filter"], {})}

    def runs(self, wid):
        out = []
        for x in self.d.q("SELECT * FROM tag_runs WHERE work_id=? ORDER BY id DESC", (int(wid),)):
            cnt = self.d.q("SELECT status, COUNT(*) n FROM tag_cands WHERE run_id=? GROUP BY status", (x["id"],))
            st = {c["status"]: c["n"] for c in cnt}
            out.append({"id": x["id"], "status": x["status"], "created_at": x["created_at"], "finished_at": x["finished_at"],
                        "total": len(_j(x["targets"], [])), "ok": st.get("ok", 0), "failed": st.get("failed", 0)})
        return out

    def run_has_ok(self, run_id, rid):
        return bool(self.d.q("SELECT 1 FROM tag_cands WHERE run_id=? AND record_id=? AND status='ok'", (int(run_id), int(rid))))

    def failed_partial(self, run_id, rid):
        """앞 실패에서 이미 끝낸 단계(같은 원자료일 때만 이어서): {ver, text, outs, cost}"""
        rows = self.d.q("SELECT record_ver, record_text, meta, cost FROM tag_cands WHERE run_id=? AND record_id=? AND status='failed' ORDER BY id DESC LIMIT 1",
                        (int(run_id), int(rid)))
        if not rows:
            return None
        m = _j(rows[0]["meta"], {})
        return {"ver": rows[0]["record_ver"] or 0, "text": rows[0]["record_text"], "outs": m.get("steps_out") or [], "input": m.get("input") or "",
                "cost": rows[0]["cost"] or 0}

    def save_bulk(self, run, r, input_text, text, model, cost, meta, error=None, alive=None):
        """일괄 결과 한 건. 같은 실행·기록의 실패 결과는 바꿔 쓴다(성공은 다시 만들지 않음)."""
        with self.d.tx() as c:
            if alive and not error:
                alive()
            self._ver_of(c, run["work_id"], signature(run["chain"]))
            if c.execute("SELECT 1 FROM tag_cands WHERE run_id=? AND record_id=? AND status='ok'", (run["id"], r["id"])).fetchone():
                return None
            c.execute("DELETE FROM tag_cands WHERE run_id=? AND record_id=? AND status='failed'", (run["id"], r["id"]))
            return c.execute(
                "INSERT INTO tag_cands(work_id, record_id, kind, run_id, steps, input_src, input_text, record_ver, record_text, text, status, error, model, cost, meta) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run["work_id"], r["id"], "bulk", run["id"], signature(run["chain"]), run["chain"].get("src", "original"), input_text,
                 r.get("content_ver") or 0, r["content"], text or "", "failed" if error else "ok", error or "", model, float(cost or 0),
                 json.dumps(meta or {}, ensure_ascii=False))).lastrowid

    def finish_run(self, run_id, status):
        with self.d.tx() as c:
            c.execute("UPDATE tag_runs SET status=?, finished_at=datetime('now','localtime') WHERE id=?",
                      ("stopped" if status == "stopped" else "done", int(run_id)))

    # ---------- 검토 ----------
    def review(self, wid, run_id=None):
        """일괄 결과 검토 표: 실행 하나(없으면 가장 최근)의 결과와 기록의 지금 상태."""
        rows = self.d.q("SELECT id FROM tag_runs WHERE work_id=? ORDER BY id DESC LIMIT 1", (int(wid),)) if run_id is None else [{"id": int(run_id)}]
        if not rows:
            return {"run": None, "rows": []}
        run = self.run(rows[0]["id"])
        cands = {x["record_id"]: x for x in self.d.q("SELECT * FROM tag_cands WHERE run_id=? ORDER BY id", (run["id"],))}
        applied = {x["cand_id"]: x for x in self.d.q("SELECT * FROM tag_applies WHERE work_id=? AND undone_at IS NULL", (int(wid),))}
        recs = {}
        ids = run["targets"]
        if ids:
            marks = ",".join("?" * len(ids))
            for r in self.d.q(f"SELECT * FROM records WHERE id IN ({marks})", tuple(ids)):
                recs[r["id"]] = r
        stu = {s["student_no"]: s for s in self.d.q("SELECT * FROM students")}
        sigs = self._ver_map(wid)
        out = []
        for rid in ids:
            r = recs.get(rid)
            x = cands.get(rid)
            s = stu.get(r["student_no"]) if r else None
            state = "missing" if not r else ("none" if not x else ("failed" if x["status"] == "failed" else "ok"))
            act = self.d.q("SELECT active FROM memberships WHERE group_id=? AND student_no=?", (r["group_id"], r["student_no"])) if r else []
            row = {"record_id": rid, "state": state, "name": (s or {}).get("name", ""), "student_no": r["student_no"] if r else "",
                   "active": bool(act and act[0]["active"]), "seq": (r or {}).get("seq"), "date": (r or {}).get("date") or "", "kind": (r or {}).get("kind") or "",
                   "grade": (s or {}).get("grade"), "class_no": (s or {}).get("class_no"), "number": (s or {}).get("number"),
                   "group_id": r["group_id"] if r else None, "item": r["item"] if r else "", "title": (r or {}).get("title") or "",
                   "content": (r or {}).get("content") or "", "closed": bool(r and self.rec.is_closed(r["group_id"], r["item"], r["student_no"])),
                   "cand": self._cand_out(x, sigs) if x else None}
            if x and r:
                row["changed"] = (r.get("content_ver") or 0) != (x["record_ver"] or 0)
                row["applied"] = x["id"] in applied
            out.append(row)
        return {"run": run, "rows": out}

    def edit_cand(self, cid, text):
        text = (text or "").strip()
        x = self.cand(cid)
        with self.d.tx() as c:
            c.execute("UPDATE tag_cands SET edited=? WHERE id=?", (None if text == x["text"] else text, int(cid)))

    def check_cands(self, cids, checked):
        ids = [int(x) for x in cids or []]
        if not ids:
            return
        marks = ",".join("?" * len(ids))
        with self.d.tx() as c:
            c.execute(f"UPDATE tag_cands SET checked=? WHERE id IN ({marks})", (1 if checked else 0, *ids))

    # ---------- 반영·되돌리기 ----------
    def apply(self, wid, cids):
        """후보로 기록 내용을 바꾼다. 그사이 원문이 바뀌었거나 마감·비활성이면 빼고 알린다. 반환: {batch, applied, skipped:[{record_id, why}]}"""
        batch = uuid.uuid4().hex[:12]
        applied, skipped = [], []
        seen = set()
        for cid in cids or []:
            x = self.d.q("SELECT * FROM tag_cands WHERE id=? AND work_id=?", (int(cid), int(wid)))
            if not x:
                skipped.append({"cand_id": int(cid), "record_id": None, "why": "후보 없음"})
                continue
            x = x[0]
            if x["record_id"] in seen:
                skipped.append({"cand_id": x["id"], "record_id": x["record_id"], "why": "같은 기록이 두 번 골라짐"})
                continue
            seen.add(x["record_id"])
            if x["status"] != "ok":
                skipped.append({"cand_id": x["id"], "record_id": x["record_id"], "why": "실패한 결과"})
                continue
            new = (x["edited"] if x["edited"] is not None else x["text"]).strip()
            if not new:
                skipped.append({"cand_id": x["id"], "record_id": x["record_id"], "why": "빈 결과"})
                continue
            with self.d.tx() as c:
                rows = [dict(r) for r in c.execute("SELECT * FROM records WHERE id=?", (x["record_id"],))]
                if not rows:
                    skipped.append({"cand_id": x["id"], "record_id": x["record_id"], "why": "기록이 지워짐"})
                    continue
                r = rows[0]
                why = ""
                if (r["content_ver"] or 0) != (x["record_ver"] or 0) or r["content"] != x["record_text"]:
                    why = "결과를 만든 뒤 기록이 바뀜"
                elif self.rec.is_closed(r["group_id"], r["item"], r["student_no"]):
                    why = "마감됨"
                else:
                    m = c.execute("SELECT active FROM memberships WHERE group_id=? AND student_no=?", (r["group_id"], r["student_no"])).fetchone()
                    if not m or not m[0]:
                        why = "비활성 학생"
                if why:
                    skipped.append({"cand_id": x["id"], "record_id": r["id"], "why": why})
                    continue
                if new == r["content"]:
                    skipped.append({"cand_id": x["id"], "record_id": r["id"], "why": "이미 같은 내용"})
                    continue
                c.execute("UPDATE records SET content=?, original=COALESCE(original, content), updated_at=datetime('now','localtime') WHERE id=?",
                          (new, r["id"]))
                after_ver = c.execute("SELECT content_ver FROM records WHERE id=?", (r["id"],)).fetchone()[0]
                c.execute("INSERT INTO tag_applies(work_id, batch, record_id, cand_id, before_text, before_ver, after_text, after_ver) VALUES(?,?,?,?,?,?,?,?)",
                          (int(wid), batch, r["id"], x["id"], r["content"], r["content_ver"] or 0, new, after_ver))
                self.rec._stale(c, r["group_id"], r["item"], r["student_no"])
                applied.append({"cand_id": x["id"], "record_id": r["id"], "group_id": r["group_id"], "item": r["item"], "student_no": r["student_no"]})
        return {"batch": batch if applied else None, "applied": applied, "skipped": skipped}

    def batches(self, wid):
        out = []
        for x in self.d.q("SELECT batch, MIN(created_at) at, COUNT(*) n, SUM(undone_at IS NOT NULL) undone FROM tag_applies WHERE work_id=? "
                          "GROUP BY batch ORDER BY MIN(id) DESC", (int(wid),)):
            out.append({"batch": x["batch"], "at": x["at"], "count": x["n"], "undone": x["undone"] or 0})
        return out

    def undo(self, wid, batch):
        """반영 묶음 되돌리기. 반영 뒤 다시 고친 기록·마감된 기록은 그대로 두고 이유를 알린다."""
        rows = self.d.q("SELECT * FROM tag_applies WHERE work_id=? AND batch=? AND undone_at IS NULL ORDER BY id DESC", (int(wid), str(batch)))
        if not rows:
            raise DbError("되돌릴 반영이 없습니다(이미 되돌렸을 수 있습니다).")
        done, skipped = [], []
        for a in rows:
            with self.d.tx() as c:
                r = c.execute("SELECT * FROM records WHERE id=?", (a["record_id"],)).fetchone()
                if not r:
                    skipped.append({"record_id": a["record_id"], "why": "기록이 지워짐"})
                    continue
                r = dict(r)
                if (r["content_ver"] or 0) != (a["after_ver"] or 0) or r["content"] != a["after_text"]:
                    skipped.append({"record_id": r["id"], "why": "반영 뒤 기록이 다시 바뀜"})
                    continue
                if self.rec.is_closed(r["group_id"], r["item"], r["student_no"]):
                    skipped.append({"record_id": r["id"], "why": "마감됨"})
                    continue
                m = c.execute("SELECT active FROM memberships WHERE group_id=? AND student_no=?", (r["group_id"], r["student_no"])).fetchone()
                if not m or not m[0]:
                    skipped.append({"record_id": r["id"], "why": "비활성 학생"})
                    continue
                c.execute("UPDATE records SET content=?, updated_at=datetime('now','localtime') WHERE id=?", (a["before_text"], r["id"]))
                c.execute("UPDATE tag_applies SET undone_at=datetime('now','localtime') WHERE id=?", (a["id"],))
                self.rec._stale(c, r["group_id"], r["item"], r["student_no"])
                done.append({"record_id": r["id"], "group_id": r["group_id"], "item": r["item"], "student_no": r["student_no"]})
        return {"undone": done, "skipped": skipped}

    # ---------- 현황판 ----------
    def progress(self, wid):
        """작업 전체(모든 일괄 실행)에서 기록마다 가장 최근 일괄 결과로 센다: 검토 전·실패·결과 없음(중지·종료로 못 한 것)."""
        applied = {x["cand_id"] for x in self.d.q("SELECT cand_id FROM tag_applies WHERE work_id=? AND undone_at IS NULL AND cand_id IS NOT NULL", (int(wid),))}
        applied_rec = self._applied_records(wid)
        latest = {}
        for x in self.d.q("SELECT id, record_id, status FROM tag_cands WHERE work_id=? AND kind='bulk' ORDER BY id", (int(wid),)):
            latest[x["record_id"]] = x
        targets = set()
        for x in self.d.q("SELECT targets FROM tag_runs WHERE work_id=?", (int(wid),)):
            targets.update(_j(x["targets"], []))
        pending = failed = notrun = 0
        for rid in targets:
            x = latest.get(rid)  # 그 기록의 가장 최근 일괄 결과로 판단(예전 반영 여부로 새 결과를 끝난 것으로 보지 않음)
            if not x:
                if rid not in applied_rec:
                    notrun += 1
            elif x["status"] == "failed":
                failed += 1
            elif x["id"] not in applied:
                pending += 1
        return {"pending": pending, "failed": failed, "notrun": notrun}

    def summary(self):
        """진행 중인 태그 작업(태그가 남아 있는 것): 검토 전·실패·결과 없음 건수, 시험 중."""
        out = []
        tags = {x["id"] for x in self.d.q("SELECT id FROM tags")}
        for w in self.d.q("SELECT * FROM tag_works ORDER BY updated_at DESC"):
            if w["tag_id"] not in tags:
                continue
            p = self.progress(w["id"])
            trials = self.d.q("SELECT COUNT(*) n FROM tag_cands WHERE work_id=? AND kind='trial'", (w["id"],))[0]["n"]
            trying = bool(trials and not _j(w["confirmed"], None))
            if p["pending"] or p["failed"] or p["notrun"] or trying:
                out.append({"work_id": w["id"], "tag_id": w["tag_id"], "tag_name": w["tag_name"], **p, "trying": trying})
        return out

    def orphans(self):
        """지운 태그의 작업(반영 기록이 있는 것): 태그별 기록에서 이력 보기·되돌리기용."""
        tags = {x["id"] for x in self.d.q("SELECT id FROM tags")}
        out = []
        for w in self.d.q("SELECT * FROM tag_works ORDER BY updated_at DESC"):
            if w["tag_id"] in tags:
                continue
            n = self.d.q("SELECT COUNT(*) n, SUM(undone_at IS NULL) live FROM tag_applies WHERE work_id=?", (w["id"],))[0]
            if n["n"]:
                out.append({"work_id": w["id"], "tag_name": w["tag_name"], "applies": n["n"], "live": n["live"] or 0})
        return out
