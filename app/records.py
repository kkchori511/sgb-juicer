"""누가기록·태그·AI 결과 후보·최종안·마감(학년도 DB 위에서 동작).

'칸(slot)' = (담당 group_id, 항목 item, 학생 student_no).
담임반은 autonomy/career/behavior, 과목은 subject, 동아리는 club 항목을 가진다.
"""
import json
import re

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
        rows = self.d.q(
            """SELECT t.id, t.name, (SELECT COUNT(*) FROM record_tags rt WHERE rt.tag_id=t.id) AS used,
                      (SELECT COUNT(*) FROM record_tags rt JOIN records r ON r.id=rt.record_id
                         JOIN finals f ON f.group_id=r.group_id AND f.item=r.item AND f.student_no=r.student_no AND f.closed=1
                       WHERE rt.tag_id=t.id) AS used_closed
               FROM tags t ORDER BY t.sort_order, t.name"""
        )
        inbox = self.d.q("SELECT tag_ids FROM inbox_batches WHERE stage<>'sent'")
        for t in rows:
            t["used_inbox"] = sum(1 for b in inbox if t["id"] in json.loads(b["tag_ids"] or "[]"))
        return rows

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
        """태그 사전 정리는 마감과 관계없이 전체에 반영한다(결정 27). 인박스의 태그 지정도 함께 뺀다."""
        with self.d.tx() as c:
            c.execute("DELETE FROM record_tags WHERE tag_id=?", (int(tid),))
            for b in c.execute("SELECT id, tag_ids FROM inbox_batches").fetchall():
                ids = json.loads(b[1] or "[]")
                if int(tid) in ids:
                    c.execute("UPDATE inbox_batches SET tag_ids=? WHERE id=?", (json.dumps([x for x in ids if x != int(tid)]), b[0]))
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
            "SELECT * FROM records WHERE group_id=? AND item=? AND student_no=? ORDER BY pos IS NULL, pos, kind='record', COALESCE(seq, 0), id",
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

    def reorder(self, gid, item, sno, ids):
        """학생×항목의 기록 순서를 화면에서 끈 순서로(종합할 때 AI에 보내는 순서도 이 순서)."""
        self.slot(gid, item)
        ids = [int(x) for x in ids or []]
        with self.d.tx() as c:
            self.require_open(gid, item, sno)
            have = {r[0] for r in c.execute("SELECT id FROM records WHERE group_id=? AND item=? AND student_no=?", (int(gid), item, str(sno)))}
            if set(ids) != have or len(ids) != len(have):
                raise DbError("기록 목록이 바뀌었습니다. 화면을 다시 열어 주세요.")
            for i, rid in enumerate(ids):
                c.execute("UPDATE records SET pos=? WHERE id=?", (i + 1, rid))

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
                if fields["weight"] != fields["weight"] or fields["weight"] in (float("inf"), float("-inf")):
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

    # ---------- 문단 이동 ----------
    @staticmethod
    def paragraphs(text: str) -> list[str]:
        """빈 줄로 나눈 문단. 빈 줄이 없으면 줄 단위."""
        t = (text or "").strip()
        parts = [p.strip() for p in re.split(r"\n\s*\n", t) if p.strip()]
        if len(parts) <= 1:
            parts = [p.strip() for p in t.splitlines() if p.strip()]
        return parts or ([t] if t else [])

    def move_targets(self, gid, item, sno):
        """이 학생이 속한(활성) 다른 항목들."""
        out = []
        for g in self.d.groups():
            rows = self.d.q("SELECT active FROM memberships WHERE group_id=? AND student_no=?", (g["id"], str(sno)))
            if not rows or not rows[0]["active"]:
                continue
            for it in items_of(g):
                if g["id"] == int(gid) and it == item:
                    continue
                out.append({"group_id": g["id"], "item": it, "label": f"{ITEM_LABEL[it]} · {g['name']}" if g["kind"] == "homeroom" else (
                    f"세특 · {g['name']}({g['semester']}학기)" if g["kind"] == "subject" else f"동아리 · {g['name']}"),
                    "closed": self.is_closed(g["id"], it, sno)})
        return out

    @staticmethod
    def _snap(c, rid):
        """되돌리기 충돌 검사용: 기록의 내용·제목·날짜·비중·태그와 그 기록에 달린 후보(잠금 포함)."""
        row = c.execute("SELECT content, title, date, weight FROM records WHERE id=?", (int(rid),)).fetchone()
        if row is None:
            return None
        tags = sorted(t[0] for t in c.execute("SELECT tag_id FROM record_tags WHERE record_id=?", (int(rid),)))
        res = sorted([r[0], r[1], r[2]] for r in c.execute("SELECT id, locked, text FROM results WHERE record_id=?", (int(rid),)))
        return [row[0], row[1], row[2], row[3], tags, res]

    def move(self, moves, dest_gid, dest_item):
        """moves: [{record_id, paras: [번호] 또는 None(전체)}] → 도착 항목의 새 기록. 전부 성공 또는 전부 취소.
        반환: 되돌리기 정보."""
        dest_gid = int(dest_gid)
        self.slot(dest_gid, dest_item)
        undo = {"created": [], "sources": []}
        recs = [self.record(m["record_id"]) for m in moves]
        if not recs:
            raise DbError("옮길 기록을 고르세요.")
        sno = recs[0]["student_no"]
        if any(r["student_no"] != sno for r in recs):
            raise DbError("한 학생의 기록만 함께 옮길 수 있습니다.")
        if not any(t["group_id"] == dest_gid and t["item"] == dest_item for t in self.move_targets(recs[0]["group_id"], recs[0]["item"], sno)):
            raise DbError("이 학생이 속하지 않은 항목으로는 옮길 수 없습니다.")
        for r in recs:
            self.require_open(r["group_id"], r["item"], r["student_no"])
        self.require_open(dest_gid, dest_item, sno)
        tagmap = {}
        for r in recs:
            tagmap[r["id"]] = [t["tag_id"] for t in self.d.q("SELECT tag_id FROM record_tags WHERE record_id=?", (r["id"],))]
        with self.d.tx() as c:
            seq = c.execute("SELECT COALESCE(MAX(seq),0) FROM records WHERE group_id=? AND item=? AND student_no=? AND kind='record'",
                            (dest_gid, dest_item, sno)).fetchone()[0] or 0
            for m, r in zip(moves, recs):
                paras = self.paragraphs(r["content"])
                pick = sorted(set(int(i) for i in m.get("paras") or [] if 0 <= int(i) < len(paras))) if m.get("paras") is not None else list(range(len(paras)))
                if not pick:
                    raise DbError("옮길 문단을 고르세요.")
                moved = "\n\n".join(paras[i] for i in pick)
                rest = [p for i, p in enumerate(paras) if i not in pick]
                kind = r["kind"]
                if kind == "record":
                    seq += 1
                nid = c.execute(
                    "INSERT INTO records(group_id,item,student_no,kind,seq,date,title,content,source) VALUES(?,?,?,?,?,?,?,?,?)",
                    (dest_gid, dest_item, sno, kind, seq if kind == "record" else None, r["date"], r["title"], moved,
                     f"moved:{r['item']}:{r['group_id']}"),
                ).lastrowid
                for tid in tagmap[r["id"]]:
                    c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?,?)", (nid, tid))
                undo["created"].append(nid)
                cands = [dict(x) for x in c.execute("SELECT * FROM results WHERE record_id=?", (r["id"],))]
                undo["sources"].append({"row": {k: r[k] for k in ("id", "group_id", "item", "student_no", "kind", "seq", "date", "title", "content", "original", "source", "weight", "created_at")},
                                        "tags": tagmap[r["id"]], "deleted": not rest, "after": "\n\n".join(rest), "cands": cands})
                undo.setdefault("moved_text", {})[str(nid)] = moved
                if rest:
                    c.execute("UPDATE records SET content=?, updated_at=datetime('now','localtime') WHERE id=?", ("\n\n".join(rest), r["id"]))
                else:
                    c.execute("DELETE FROM results WHERE record_id=?", (r["id"],))
                    c.execute("DELETE FROM records WHERE id=?", (r["id"],))
                self._stale(c, r["group_id"], r["item"], sno)
            self._stale(c, dest_gid, dest_item, sno)
            undo["snap"] = {str(nid): self._snap(c, nid) for nid in undo["created"]}
            for src in undo["sources"]:
                src["snap"] = None if src["deleted"] else self._snap(c, src["row"]["id"])
        undo.update(year=self.d.year, dest=[dest_gid, dest_item], sno=sno)
        return undo

    def undo_move(self, undo):
        """이동 직후 상태 그대로일 때만 되돌린다(그 뒤 고쳤거나 마감했으면 막음)."""
        if undo.get("year") != self.d.year:
            raise DbError("학년도가 바뀌어 이 이동은 되돌릴 수 없습니다.")
        sno = undo["sno"]
        slots = {(undo["dest"][0], undo["dest"][1])} | {(x["row"]["group_id"], x["row"]["item"]) for x in undo["sources"]}
        with self.d.tx() as c:
            # 검사와 되돌리기를 한 트랜잭션에서: 검사 뒤에 다른 변경이 끼어들지 않게
            for gid, item in slots:
                if self.is_closed(gid, item, sno):
                    raise DbError("이동한 뒤 마감된 항목이 있어 되돌릴 수 없습니다. 마감을 해제한 뒤 직접 옮겨 주세요.")
            snaps = undo.get("snap") or {}
            for nid in undo["created"]:
                now = self._snap(c, nid)
                if now is None or now != snaps.get(str(nid)):
                    raise DbError("옮긴 기록을 그 뒤에 고치거나(제목·날짜·태그·비중·후보 포함) 지워서 되돌릴 수 없습니다.")
            for src in undo["sources"]:
                now = self._snap(c, src["row"]["id"])
                if src["deleted"]:
                    if now is not None:
                        raise DbError("원래 기록 자리가 이미 쓰여 되돌릴 수 없습니다.")
                elif now is None or now != src.get("snap"):
                    raise DbError("원래 기록을 그 뒤에 고쳐서 되돌릴 수 없습니다.")
            for nid in undo["created"]:
                c.execute("DELETE FROM results WHERE record_id=?", (int(nid),))
                c.execute("DELETE FROM records WHERE id=?", (int(nid),))
            for src in undo["sources"]:
                r = src["row"]
                if src["deleted"]:
                    c.execute("""INSERT INTO records(id,group_id,item,student_no,kind,seq,date,title,content,original,source,weight,created_at)
                                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""", tuple(r[k] for k in ("id", "group_id", "item", "student_no", "kind", "seq", "date", "title", "content", "original", "source", "weight", "created_at")))
                    for tid in src["tags"]:
                        c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) SELECT ?, id FROM tags WHERE id=?", (r["id"], tid))
                    for cd in src.get("cands", []):
                        cols = list(cd.keys())
                        c.execute(f"INSERT INTO results({','.join(cols)}) VALUES({','.join('?' * len(cols))})", tuple(cd[k] for k in cols))
                else:
                    c.execute("UPDATE records SET content=?, updated_at=datetime('now','localtime') WHERE id=?", (r["content"], r["id"]))
            for gid, item in slots:
                self._stale(c, gid, item, sno)

    # ---------- 일괄 종합 준비 ----------
    def batch_info(self, gid, item):
        """학생마다 일괄 종합 가능 여부."""
        g, target = self.slot(gid, item)
        out = []
        for m in self.d.members(gid):
            recs = self.d.q("SELECT id, kind, content, weight FROM records WHERE group_id=? AND item=? AND student_no=? ORDER BY kind='record', COALESCE(seq,0), id",
                            (int(gid), item, m["student_no"]))
            slot_res = self._scope_rows(gid, item, m["student_no"], None)
            f = self.final(gid, item, m["student_no"])
            out.append({
                "student_no": m["student_no"], "name": m["name"], "grade": m["grade"], "class_no": m["class_no"], "number": m["number"],
                "active": bool(m["active"]), "level": m["level"] or "",
                "record_ids": [r["id"] for r in recs], "records": len(recs),
                "bytes": sum(count_bytes(r["content"]) for r in recs),
                "closed": bool(f and f["closed"]), "has_final": bool(f and f["text"]),
                "all_locked": len(slot_res) >= MAX_RESULTS and all(r["locked"] for r in slot_res),
            })
        return {"group": g, "target": target, "students": out}

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
            if self.is_closed(gid, item, sno):  # AI를 기다리는 동안 마감됐을 수 있다
                raise DbError("AI 작업 중에 마감되어 결과를 저장하지 않았습니다.")
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
        text = (text or "").strip()
        with self.d.tx() as c:
            self.require_open(gid, item, sno)
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
            rows.append({"student_no": m["student_no"], "name": m["name"], "grade": m["grade"], "class_no": m["class_no"], "number": m["number"],
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
