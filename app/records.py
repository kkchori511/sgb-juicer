"""누가기록·태그·AI 결과 후보·최종안·마감(학년도 DB 위에서 동작).

'칸(slot)' = (담당 group_id, 항목 item, 학생 student_no).
담임반은 autonomy/career/behavior, 과목은 subject, 동아리는 club 항목을 가진다.
"""
import json

from .db import DbError, YearDb
from .textutil import count_bytes

HOMEROOM_ITEMS = ("autonomy", "career", "behavior")
ITEM_LABEL = {"autonomy": "자율활동", "career": "진로활동", "behavior": "행동특성 및 종합의견", "subject": "세특", "club": "동아리활동"}
MAX_RESULTS = 3
CLOSED_MSG = "마감된 항목입니다. [마감 해제]를 누른 뒤 고쳐 주세요."


def items_of(group: dict):
    return HOMEROOM_ITEMS if group["kind"] == "homeroom" else (group["kind"],)


class Records:
    def __init__(self, d: YearDb):
        self.d = d

    # ---------- 칸 ----------
    def slots(self, role: str):
        out = []
        targets = self.d.targets()
        for g in self.d.groups():
            if g["kind"] == "homeroom" and role != "homeroom":
                continue
            for it in items_of(g):
                target = targets[it] if g["kind"] == "homeroom" else (g["target_bytes"] or targets[it])
                label = f"{ITEM_LABEL[it]} · {g['name']}" if g["kind"] == "homeroom" else (
                    f"세특 · {g['name']}({g['semester']}학기)" if g["kind"] == "subject" else f"동아리 · {g['name']}")
                out.append({"group_id": g["id"], "item": it, "kind": g["kind"], "label": label, "target": target,
                            "semester": g["semester"], "level_scale": g["level_scale"], "total": g["total"], "active": g["active"]})
        return out

    def slot(self, gid, item):
        g = self.d.group(gid)
        if item not in items_of(g):
            raise DbError("이 담당에 없는 항목입니다.")
        targets = self.d.targets()
        target = targets[item] if g["kind"] == "homeroom" else (g["target_bytes"] or targets[item])
        return g, target

    def _member(self, gid, sno):
        rows = self.d.q("SELECT active FROM memberships WHERE group_id=? AND student_no=?", (int(gid), str(sno)))
        if not rows:
            raise DbError("이 담당의 학생이 아닙니다.")
        return rows[0]

    def final(self, gid, item, sno):
        rows = self.d.q("SELECT * FROM finals WHERE group_id=? AND item=? AND student_no=?", (int(gid), item, str(sno)))
        return rows[0] if rows else None

    def is_closed(self, gid, item, sno):
        f = self.final(gid, item, sno)
        return bool(f and f["closed"])

    def require_open(self, gid, item, sno):
        if self.is_closed(gid, item, sno):
            raise DbError(CLOSED_MSG)

    def _stale(self, c, gid, item, sno):
        c.execute("UPDATE finals SET stale=1 WHERE group_id=? AND item=? AND student_no=? AND text<>''", (int(gid), item, str(sno)))

    # ---------- 상태 ----------
    def status_map(self, gid, item):
        """{학번: {status, records, final_bytes, stale}}"""
        out = {}
        for r in self.d.q("SELECT student_no, COUNT(*) n FROM records WHERE group_id=? AND item=? GROUP BY student_no", (int(gid), item)):
            out.setdefault(r["student_no"], {})["records"] = r["n"]
        for r in self.d.q("SELECT student_no, COUNT(*) n FROM results WHERE group_id=? AND item=? GROUP BY student_no", (int(gid), item)):
            out.setdefault(r["student_no"], {})["results"] = r["n"]
        for f in self.d.q("SELECT * FROM finals WHERE group_id=? AND item=?", (int(gid), item)):
            o = out.setdefault(f["student_no"], {})
            o["closed"] = bool(f["closed"])
            o["final_bytes"] = count_bytes(f["text"]) if f["text"] else None
            o["has_final"] = bool(f["text"])
            o["stale"] = bool(f["stale"])
        for sno, o in out.items():
            o.setdefault("records", 0)
            o.setdefault("final_bytes", None)
            o.setdefault("stale", False)
            if o.get("closed"):
                o["status"] = "closed"
            elif o.get("has_final"):
                o["status"] = "final"
            elif o["records"] or o.get("results"):
                o["status"] = "progress"
            else:
                o["status"] = "none"
        return out

    # ---------- 태그 ----------
    def tags(self):
        return self.d.q(
            """SELECT t.id, t.name, (SELECT COUNT(*) FROM record_tags rt WHERE rt.tag_id=t.id) AS used
               FROM tags t ORDER BY t.sort_order, t.name"""
        )

    def add_tag(self, name):
        name = (name or "").strip()
        if not name:
            raise DbError("태그 이름을 입력해 주세요.")
        if self.d.q("SELECT 1 FROM tags WHERE name=?", (name,)):
            raise DbError(f"'{name}' 태그가 이미 있습니다.")
        with self.d.tx() as c:
            return c.execute("INSERT INTO tags(name) VALUES(?)", (name,)).lastrowid

    def rename_tag(self, tid, name):
        name = (name or "").strip()
        if not name:
            raise DbError("태그 이름을 입력해 주세요.")
        if self.d.q("SELECT 1 FROM tags WHERE name=? AND id<>?", (name, int(tid))):
            raise DbError(f"'{name}' 태그가 이미 있습니다.")
        with self.d.tx() as c:
            c.execute("UPDATE tags SET name=? WHERE id=?", (name, int(tid)))

    def delete_tag(self, tid):
        with self.d.tx() as c:
            c.execute("DELETE FROM record_tags WHERE tag_id=?", (int(tid),))
            c.execute("DELETE FROM tags WHERE id=?", (int(tid),))

    def tag_records(self, record_ids, tag_ids, mode="add"):
        """여러 기록에 태그를 한 번에. mode: add(추가) / remove(빼기)"""
        rids = [int(x) for x in record_ids or []]
        tids = [int(x) for x in tag_ids or []]
        if not rids:
            raise DbError("기록을 먼저 고르세요.")
        for rid in rids:
            r = self.record(rid)
            self.require_open(r["group_id"], r["item"], r["student_no"])
        with self.d.tx() as c:
            for rid in rids:
                for tid in tids:
                    if mode == "remove":
                        c.execute("DELETE FROM record_tags WHERE record_id=? AND tag_id=?", (rid, tid))
                    else:
                        c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?,?)", (rid, tid))
        return len(rids)

    # ---------- 기록 ----------
    def record(self, rid):
        rows = self.d.q("SELECT * FROM records WHERE id=?", (int(rid),))
        if not rows:
            raise DbError("기록을 찾지 못했습니다.")
        return rows[0]

    def records(self, gid, item, sno):
        recs = self.d.q(
            "SELECT * FROM records WHERE group_id=? AND item=? AND student_no=? ORDER BY kind='record', COALESCE(seq, 0), id",
            (int(gid), item, str(sno)),
        )
        if not recs:
            return []
        ids = [r["id"] for r in recs]
        marks = ",".join("?" * len(ids))
        tagmap = {}
        for t in self.d.q(f"SELECT rt.record_id, t.id, t.name FROM record_tags rt JOIN tags t ON t.id=rt.tag_id WHERE rt.record_id IN ({marks})", tuple(ids)):
            tagmap.setdefault(t["record_id"], []).append({"id": t["id"], "name": t["name"]})
        cands = {}
        for res in self.d.q(f"SELECT * FROM results WHERE record_id IN ({marks}) ORDER BY id", tuple(ids)):
            cands.setdefault(res["record_id"], []).append(_result_out(res))
        for r in recs:
            r["tags"] = tagmap.get(r["id"], [])
            r["candidates"] = cands.get(r["id"], [])
            r["bytes"] = count_bytes(r["content"])
        return recs

    def add_record(self, gid, item, sno, data):
        self.slot(gid, item)
        self._member(gid, sno)
        self.require_open(gid, item, sno)
        content = (data.get("content") or "").strip()
        if not content:
            raise DbError("내용을 입력해 주세요.")
        kind = "existing" if data.get("kind") == "existing" else "record"
        with self.d.tx() as c:
            seq = None
            if kind == "record":
                seq = (c.execute("SELECT COALESCE(MAX(seq),0) FROM records WHERE group_id=? AND item=? AND student_no=? AND kind='record'",
                                 (int(gid), item, str(sno))).fetchone()[0] or 0) + 1
            rid = c.execute(
                "INSERT INTO records(group_id,item,student_no,kind,seq,date,title,content,source) VALUES(?,?,?,?,?,?,?,?,?)",
                (int(gid), item, str(sno), kind, seq, (data.get("date") or "").strip(), (data.get("title") or "").strip(),
                 content, data.get("source") or ("existing" if kind == "existing" else "manual")),
            ).lastrowid
            for tid in data.get("tag_ids") or []:
                c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?,?)", (rid, int(tid)))
            self._stale(c, gid, item, sno)
        return rid

    def add_existing_bulk(self, gid, item, rows):
        """이미 쓴 생기부 여러 학생 한꺼번에 — 전부 넣거나 전부 취소."""
        self.slot(gid, item)
        for r in rows:
            self._member(gid, r["student_no"])
            self.require_open(gid, item, r["student_no"])
        with self.d.tx() as c:
            for r in rows:
                c.execute(
                    "INSERT INTO records(group_id,item,student_no,kind,seq,title,content,source) VALUES(?,?,?,'existing',NULL,?,?,?)",
                    (int(gid), item, str(r["student_no"]), "이미 쓴 생기부", r["content"].strip(), "existing-bulk"),
                )
                self._stale(c, gid, item, r["student_no"])
        return len(rows)

    def update_record(self, rid, data):
        r = self.record(rid)
        self.require_open(r["group_id"], r["item"], r["student_no"])
        fields = {}
        for k in ("date", "title", "content"):
            if k in data:
                fields[k] = (data[k] or "").strip()
        if "content" in fields and not fields["content"]:
            raise DbError("내용을 비울 수 없습니다. 지우려면 [삭제]를 누르세요.")
        if "weight" in data:
            w = data["weight"]
            if w in (None, ""):
                fields["weight"] = None
            else:
                try:
                    fields["weight"] = float(w)
                except (TypeError, ValueError):
                    raise DbError("비중은 숫자로 입력해 주세요.")
                if fields["weight"] < 0:
                    raise DbError("비중은 0 이상이어야 합니다.")
        with self.d.tx() as c:
            if fields:
                sets = ", ".join(f"{k}=?" for k in fields)
                c.execute(f"UPDATE records SET {sets}, updated_at=datetime('now','localtime') WHERE id=?", (*fields.values(), r["id"]))
            if "tag_ids" in data:
                c.execute("DELETE FROM record_tags WHERE record_id=?", (r["id"],))
                for tid in data["tag_ids"] or []:
                    c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?,?)", (r["id"], int(tid)))
            if "content" in fields and fields["content"] != r["content"]:
                self._stale(c, r["group_id"], r["item"], r["student_no"])

    def apply_candidate_to_record(self, result_id):
        """기록 한 건의 정제 후보로 기록 내용을 바꾼다(처음 원문은 original에 남긴다)."""
        res = self.result(result_id)
        if not res["record_id"]:
            raise DbError("기록 후보가 아닙니다.")
        r = self.record(res["record_id"])
        self.require_open(r["group_id"], r["item"], r["student_no"])
        with self.d.tx() as c:
            c.execute(
                "UPDATE records SET content=?, original=COALESCE(original, content), updated_at=datetime('now','localtime') WHERE id=?",
                (res["text"], r["id"]),
            )
            self._stale(c, r["group_id"], r["item"], r["student_no"])

    def delete_record(self, rid):
        r = self.record(rid)
        self.require_open(r["group_id"], r["item"], r["student_no"])
        with self.d.tx() as c:
            c.execute("DELETE FROM results WHERE record_id=?", (r["id"],))
            c.execute("DELETE FROM records WHERE id=?", (r["id"],))
            self._stale(c, r["group_id"], r["item"], r["student_no"])

    # ---------- 결과 후보(최근 3개, 잠금 포함) ----------
    def result(self, res_id):
        rows = self.d.q("SELECT * FROM results WHERE id=?", (int(res_id),))
        if not rows:
            raise DbError("결과를 찾지 못했습니다.")
        return rows[0]

    def slot_results(self, gid, item, sno):
        return [_result_out(r) for r in self.d.q(
            "SELECT * FROM results WHERE group_id=? AND item=? AND student_no=? AND record_id IS NULL ORDER BY id",
            (int(gid), item, str(sno)))]

    def _scope_rows(self, gid, item, sno, record_id):
        if record_id:
            return self.d.q("SELECT id, locked FROM results WHERE record_id=? ORDER BY id", (int(record_id),))
        return self.d.q("SELECT id, locked FROM results WHERE group_id=? AND item=? AND student_no=? AND record_id IS NULL ORDER BY id",
                        (int(gid), item, str(sno)))

    def check_room(self, gid, item, sno, record_id=None):
        """AI를 부르기 전에: 후보 3개가 모두 잠겨 있으면 막는다."""
        rows = self._scope_rows(gid, item, sno, record_id)
        if len(rows) >= MAX_RESULTS and all(r["locked"] for r in rows):
            raise DbError("결과 후보 3개가 모두 잠겨 있습니다. 잠금을 하나 풀어야 새로 만들 수 있습니다.")

    def add_result(self, gid, item, sno, op, text, meta=None, cost=0.0, record_id=None):
        """새 결과를 넣고, 3개를 넘으면 잠기지 않은 가장 오래된 후보를 지운다. 반환: (새 id, 지운 id 또는 None)"""
        self.check_room(gid, item, sno, record_id)
        with self.d.tx() as c:
            rows = [dict(r) for r in c.execute(
                ("SELECT id, locked FROM results WHERE record_id=? ORDER BY id" if record_id else
                 "SELECT id, locked FROM results WHERE group_id=? AND item=? AND student_no=? AND record_id IS NULL ORDER BY id"),
                (int(record_id),) if record_id else (int(gid), item, str(sno)))]
            dropped = None
            if len(rows) >= MAX_RESULTS:
                victim = next((r for r in rows if not r["locked"]), None)
                if victim is None:
                    raise DbError("결과 후보 3개가 모두 잠겨 있습니다.")
                c.execute("DELETE FROM results WHERE id=?", (victim["id"],))
                dropped = victim["id"]
            nid = c.execute(
                "INSERT INTO results(group_id,item,student_no,record_id,op,text,meta,cost) VALUES(?,?,?,?,?,?,?,?)",
                (int(gid), item, str(sno), int(record_id) if record_id else None, op, text,
                 json.dumps(meta or {}, ensure_ascii=False), float(cost or 0)),
            ).lastrowid
        return nid, dropped

    def lock_result(self, res_id, locked):
        r = self.result(res_id)
        with self.d.tx() as c:
            c.execute("UPDATE results SET locked=? WHERE id=?", (1 if locked else 0, r["id"]))

    def delete_result(self, res_id):
        r = self.result(res_id)
        self.require_open(r["group_id"], r["item"], r["student_no"])
        with self.d.tx() as c:
            c.execute("DELETE FROM results WHERE id=?", (r["id"],))

    # ---------- 최종안·마감 ----------
    def _upsert_final(self, c, gid, item, sno, text, source, meta):
        c.execute(
            """INSERT INTO finals(group_id,item,student_no,text,source,meta,stale,closed,updated_at)
               VALUES(?,?,?,?,?,?,0,0,datetime('now','localtime'))
               ON CONFLICT(group_id,item,student_no) DO UPDATE SET text=excluded.text, source=excluded.source,
                   meta=excluded.meta, stale=0, updated_at=excluded.updated_at""",
            (int(gid), item, str(sno), text, source, json.dumps(meta or {}, ensure_ascii=False)),
        )

    def adopt_result(self, res_id):
        r = self.result(res_id)
        self.require_open(r["group_id"], r["item"], r["student_no"])
        with self.d.tx() as c:
            self._upsert_final(c, r["group_id"], r["item"], r["student_no"], r["text"],
                               f"result:{r['id']}", {"op": r["op"], "created_at": r["created_at"], **json.loads(r["meta"] or "{}")})

    def adopt_record(self, rid):
        """기록(예: 이미 쓴 생기부)을 그대로 최종안으로."""
        r = self.record(rid)
        self.require_open(r["group_id"], r["item"], r["student_no"])
        with self.d.tx() as c:
            self._upsert_final(c, r["group_id"], r["item"], r["student_no"], r["content"], f"record:{r['id']}",
                               {"op": "record", "kind": r["kind"]})

    def edit_final(self, gid, item, sno, text):
        self.slot(gid, item)
        self.require_open(gid, item, sno)
        text = (text or "").strip()
        with self.d.tx() as c:
            if not text:
                c.execute("DELETE FROM finals WHERE group_id=? AND item=? AND student_no=?", (int(gid), item, str(sno)))
                return
            prev = self.final(gid, item, sno)
            meta = json.loads(prev["meta"]) if prev else {}
            meta["edited"] = True
            self._upsert_final(c, gid, item, sno, text, (prev or {}).get("source") or "manual", meta)

    def set_closed(self, gid, item, sno, closed):
        f = self.final(gid, item, sno)
        if closed and not (f and f["text"].strip()):
            raise DbError("최종안이 없어 마감할 수 없습니다. 먼저 최종안을 채택하거나 직접 써 주세요.")
        with self.d.tx() as c:
            c.execute(
                "UPDATE finals SET closed=?, closed_at=CASE WHEN ? THEN datetime('now','localtime') ELSE NULL END WHERE group_id=? AND item=? AND student_no=?",
                (1 if closed else 0, 1 if closed else 0, int(gid), item, str(sno)),
            )

    # ---------- 내보내기 ----------
    def export_rows(self, gid, item, only_closed=False, order="no"):
        self.slot(gid, item)
        members = [m for m in self.d.members(gid) if m["active"]]
        finals = {f["student_no"]: f for f in self.d.q("SELECT * FROM finals WHERE group_id=? AND item=?", (int(gid), item))}
        rows = []
        for m in members:
            f = finals.get(m["student_no"])
            closed = bool(f and f["closed"])
            if only_closed and not closed:
                continue
            text = f["text"] if f else ""
            rows.append({"student_no": m["student_no"], "name": m["name"], "grade": m["grade"], "class_no": m["class_no"],
                         "closed": closed, "text": text, "bytes": count_bytes(text) if text else 0})
        if order == "name":
            rows.sort(key=lambda r: (r["name"], r["student_no"]))
        else:
            rows.sort(key=lambda r: r["student_no"])
        return rows


def _result_out(r):
    out = dict(r)
    out["locked"] = bool(r["locked"])
    out["bytes"] = count_bytes(r["text"])
    try:
        out["meta"] = json.loads(r["meta"] or "{}")
    except ValueError:
        out["meta"] = {}
    return out
