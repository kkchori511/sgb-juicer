"""학생관찰기록·태그·AI 결과 후보·최종안·마감(학년도 DB 위에서 동작).

'칸(slot)' = (담당 group_id, 항목 item, 학생 student_no).
담임반은 autonomy/career/behavior, 과목은 subject, 동아리는 club 항목을 가진다.
"""
import json
import re

from .db import ClosedError, ConflictError, DbError, YearDb
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

    # ---------- 1·2학기 합산 과목 ----------
    def pair_info(self, gid, item, sno):
        """세특 바이트를 1·2학기가 함께 쓰는 과목이면 그 정보.
        2학기: 1학기 최종안 바이트와 남은 바이트(= 이 학생의 목표). 1학기 최종안이 아직 없으면 합산의 절반.
        1학기: 짝인 2학기 과목과 합산 목표."""
        g = self.d.group(gid)
        if g["kind"] != "subject":
            return None
        if g.get("pair_id") and g.get("pair_total"):
            try:
                p = self.d.group(g["pair_id"])
            except DbError:
                return None
            if g["semester"] != 2 or p["semester"] != 1 or p["kind"] != "subject":  # 맞지 않는 연결은 쓰지 않는다
                return None
            f = self.final(p["id"], "subject", sno)
            member = bool(self.d.q("SELECT 1 FROM memberships WHERE group_id=? AND student_no=?", (p["id"], str(sno))))
            first = count_bytes(f["text"]) if f and f["text"] else None
            total = int(g["pair_total"])
            remain = (total - first) if first is not None else None
            mine = self.final(gid, item, sno)
            mine_b = count_bytes(mine["text"]) if mine and mine["text"] else 0
            return {"role": "second", "other_id": p["id"], "other": p["label"], "total": total, "member": member,
                    "first_bytes": first, "first_text": (f["text"] if f else "") or "", "first_closed": bool(f and f["closed"]),
                    "remain": remain, "target": max(remain, 0) if remain is not None else total // 2,
                    # 합산 초과(1학기를 나중에 늘린 경우 등): 마감했더라도 다시 확인하도록
                    "second_bytes": mine_b, "over": bool(mine_b and (first or 0) + mine_b > total),
                    "second_closed": bool(mine and mine["closed"])}
        if g["semester"] != 1:
            return None
        seconds = [s2 for s2 in self.d.groups() if s2.get("pair_id") == g["id"] and s2.get("pair_total") and s2["semester"] == 2]
        if not seconds:
            return None
        mine = self.final(gid, item, sno)
        mine_b = count_bytes(mine["text"]) if mine and mine["text"] else 0
        others = []
        for s2 in seconds:
            f2 = self.final(s2["id"], "subject", sno)
            b2 = count_bytes(f2["text"]) if f2 and f2["text"] else None
            others.append({"id": s2["id"], "label": s2["label"], "total": int(s2["pair_total"]), "second_bytes": b2,
                           "over": bool(b2 and mine_b + b2 > int(s2["pair_total"])), "second_closed": bool(f2 and f2["closed"])})
        o = others[0]
        return {"role": "first", "other_id": o["id"], "other": ", ".join(x["label"] for x in others), "total": o["total"],
                "second_bytes": o["second_bytes"], "others": others, "first_bytes": mine_b, "over": any(x["over"] for x in others)}

    def target_for(self, gid, item, sno):
        """학생별 목표 바이트: 2학기 합산 과목이면 '합산 − 1학기 최종안', 아니면 담당 목표."""
        g, target = self.slot(gid, item)
        pi = self.pair_info(gid, item, sno)
        if pi and pi["role"] == "second":
            return pi["target"], pi
        return target, pi

    def ai_target(self, gid, item, sno):
        """AI에 줄 목표. 1학기가 합산을 이미 다 쓰면 막는다."""
        t, pi = self.target_for(gid, item, sno)
        if pi and pi["role"] == "second" and t <= 0:
            raise DbError(f"1학기({pi['other']}) 최종안이 {pi['first_bytes']}B로 합산 {pi['total']}B를 이미 채웠습니다. 1학기 최종안을 줄이거나 합산 목표를 바꿔 주세요.")
        return t

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
            raise ClosedError(CLOSED_MSG)

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

    def inbox_tag_names(self):
        """인박스 묶음 이름 목록(같은 이름은 하나로). 이미 태그로 있는지, 보내기 전 묶음 수."""
        have = {r["name"] for r in self.d.q("SELECT name FROM tags")}
        out = {}
        for b in self.d.q("SELECT id, title, stage FROM inbox_batches ORDER BY updated_at DESC, id DESC"):
            name = (b["title"] or "").strip()
            if not name:
                continue
            o = out.setdefault(name, {"name": name, "exists": name in have, "batches": 0, "open": 0})
            o["batches"] += 1
            o["open"] += b["stage"] != "sent"
        return list(out.values())

    def tags_from_inbox(self, names):
        """고른 묶음 이름을 태그로 만들고, 같은 이름의 보내기 전 묶음에 그 태그를 붙인다. 이미 있는 태그는 건너뛴다.
        → (만든 태그 수, 태그를 붙인 묶음 수)"""
        names = list(dict.fromkeys((n or "").strip() for n in names or []))
        names = [n for n in names if n]
        made = attached = 0
        with self.d.tx() as c:
            for name in names:
                if c.execute("SELECT 1 FROM tags WHERE name=?", (name,)).fetchone():
                    continue
                tid = c.execute("INSERT INTO tags(name) VALUES(?)", (name,)).lastrowid
                made += 1
                for bid, ids in c.execute("SELECT id, tag_ids FROM inbox_batches WHERE TRIM(title)=? AND stage<>'sent'", (name,)).fetchall():
                    ids = json.loads(ids or "[]")
                    if tid not in ids:
                        c.execute("UPDATE inbox_batches SET tag_ids=? WHERE id=?", (json.dumps(ids + [tid]), bid))
                        attached += 1
        return made, attached

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
            c.execute("UPDATE records SET tags_ver=COALESCE(tags_ver,0)+1 WHERE id IN (SELECT record_id FROM record_tags WHERE tag_id=?)", (int(tid),))
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
                n = 0
                for tid in tids:
                    if mode == "remove":
                        n += c.execute("DELETE FROM record_tags WHERE record_id=? AND tag_id=?", (rid, tid)).rowcount
                    else:
                        n += c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?,?)", (rid, tid)).rowcount
                if n:
                    c.execute("UPDATE records SET tags_ver=COALESCE(tags_ver,0)+1 WHERE id=?", (rid,))
        return len(rids)

    def tag_records_changed(self, record_ids, tag_ids, mode="add"):
        """tag_records와 같고, 실제로 바뀐 (기록, 태그, 바뀐 뒤 태그 버전)을 돌려준다(되돌리기용)."""
        rids = [int(x) for x in record_ids or []]
        tids = [int(x) for x in tag_ids or []]
        with self.d._lock:  # 확인·쓰기·버전 읽기 사이에 다른 저장이 끼지 않게(RLock이라 안쪽 tx도 같은 잠금)
            have = {(r["record_id"], r["tag_id"]) for r in self.d.q(
                f"SELECT record_id, tag_id FROM record_tags WHERE record_id IN ({','.join('?' * len(rids)) or 'NULL'})", tuple(rids))}
            self.tag_records(rids, tids, mode)
            ver = {r["id"]: r["tags_ver"] or 0 for r in self.d.q(
                f"SELECT id, tags_ver FROM records WHERE id IN ({','.join('?' * len(rids)) or 'NULL'})", tuple(rids))}
        if mode == "remove":
            return [[r, t, ver.get(r, 0)] for r in rids for t in tids if (r, t) in have]
        return [[r, t, ver.get(r, 0)] for r in rids for t in tids if (r, t) not in have]

    def undo_tag_pairs(self, pairs, mode):
        """일괄 태그 되돌리기: mode는 처음 실행한 동작(add면 지금 빼고, remove면 다시 붙인다).
        건너뜀: 마감·삭제된 기록, 지운 태그, 그 뒤 태그가 다시 바뀐 기록(태그 버전이 다름).
        → (되돌린 수, 건너뛴 수, 그 뒤 바뀌어 건너뛴 수)"""
        done = skipped = changed = 0
        bumped = set()
        with self.d.tx() as c:
            for p in pairs or []:
                rid, tid = int(p[0]), int(p[1])
                ver = int(p[2]) if len(p) > 2 else None
                r = c.execute("SELECT group_id, item, student_no, COALESCE(tags_ver,0) FROM records WHERE id=?", (rid,)).fetchone()
                if not r or self.is_closed(r[0], r[1], r[2]) or not c.execute("SELECT 1 FROM tags WHERE id=?", (tid,)).fetchone():
                    skipped += 1
                    continue
                if ver is not None and r[3] != ver + (1 if rid in bumped else 0):
                    skipped += 1
                    changed += 1
                    continue
                if mode == "add":
                    c.execute("DELETE FROM record_tags WHERE record_id=? AND tag_id=?", (rid, tid))
                else:
                    c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?,?)", (rid, tid))
                if rid not in bumped:
                    c.execute("UPDATE records SET tags_ver=COALESCE(tags_ver,0)+1 WHERE id=?", (rid,))
                    bumped.add(rid)
                done += 1
        return done, skipped, changed

    # ---------- 태그별 기록 ----------
    def record_state(self, rid):
        """기록 한 건의 지금 값(태그별 기록 화면의 저장·되돌리기 확인용)."""
        r = self.record(rid)
        tids = sorted(x["tag_id"] for x in self.d.q("SELECT tag_id FROM record_tags WHERE record_id=?", (int(rid),)))
        f = self.final(r["group_id"], r["item"], r["student_no"])
        return {"id": r["id"], "content": r["content"], "date": r["date"] or "", "title": r["title"] or "", "tag_ids": tids,
                "bytes": count_bytes(r["content"]), "updated_at": r["updated_at"],
                "closed": bool(f and f["closed"]), "stale": bool(f and f["stale"]), "has_final": bool(f and f["text"])}

    def revert_record(self, rid, before, after):
        """이 화면에서 저장한 것을 되돌린다. 그 뒤 다른 곳에서 다시 고쳤거나 마감했으면 덮지 않는다."""
        with self.d.tx() as c:  # 확인과 쓰기를 한 잠금 안에서
            cur = self.record_state(rid)
            if cur["closed"]:
                raise ClosedError("그 사이 마감되어 되돌리지 않았습니다. 고치려면 항목별 기록에서 마감을 해제하세요.")
            if not self._same(cur, after):
                raise ConflictError("이 화면에서 저장한 뒤 내용이 다시 바뀌어 되돌리지 않았습니다. 지금 내용을 확인해 주세요.")
            data = {k: v for k, v in (before or {}).items() if k in ("content", "date", "title", "tag_ids")}
            if "tag_ids" in data:
                live = {r["id"] for r in self.d.q("SELECT id FROM tags")}
                data["tag_ids"] = [int(x) for x in data["tag_ids"] if int(x) in live]
            self._write_record(c, self.record(rid), data)
        return self.record_state(rid)

    @staticmethod
    def _same(cur, want):
        for k, v in (want or {}).items():
            now = cur.get(k)
            same = sorted(int(x) for x in v or []) == now if k == "tag_ids" else (v or "").strip() == (now or "").strip()
            if not same:
                return False
        return True

    def tag_view(self, role, tag_id, flt=None):
        """태그 하나(0이면 '태그 없음')가 붙은 기록 전부. 볼 수 있는 담당(slots)만.
        flt: scope('' / 'c:학년-반' / 's:담당id:수업'), slot('' / 'i:항목' / 'g:담당id:항목'), status(all/open/closed), q(찾기), inactive(비활성 포함)
        - 학년-반: 그 반 학생의 모든 기록. 수업: 그 담당·수업 학생의 그 담당 기록만.
        - 태그별 수는 태그 선택을 뺀 나머지 필터를 적용해 센다."""
        flt = flt or {}
        slots = self.slots(role)
        sidx = {(s["group_id"], s["item"]): i for i, s in enumerate(slots)}
        gmeta = {g["id"]: g for g in self.d.groups()}
        mem = {}
        for gid in {s["group_id"] for s in slots}:
            for m in self.d.members(gid):
                mem[(gid, m["student_no"])] = m
        smaps = {}
        rows = self.d.q("SELECT id, group_id, item, student_no, kind, seq, date, title, content, updated_at, pos FROM records")
        tagmap = {}
        for t in self.d.q("SELECT record_id, tag_id FROM record_tags"):
            tagmap.setdefault(t["record_id"], []).append(t["tag_id"])
        stu = {s["student_no"]: s for s in self.d.q("SELECT * FROM students")}
        # 필터 선택지: 볼 수 있는 담당의 반·수업·항목(지금 0건이어도 그대로 둔다)
        classes, sections = {}, {}
        for (gid, sno), m in mem.items():
            if m["grade"] and m["class_no"]:
                classes[f"c:{m['grade']}-{m['class_no']}"] = (m["grade"], m["class_no"])
            g = gmeta.get(gid)
            if g and g["kind"] == "subject" and m["section"]:
                sections[f"s:{gid}:{m['section']}"] = (g["name"], g["semester"] or 0, m["section"])
        recs = []
        for r in rows:
            key = (r["group_id"], r["item"])
            if key not in sidx:
                continue
            m = mem.get((r["group_id"], r["student_no"]))
            if m is None:
                s0 = stu.get(r["student_no"]) or {"name": "", "grade": None, "class_no": None, "number": None}
                m = {**s0, "student_no": r["student_no"], "active": 0, "section": "", "gone": True}
            if key not in smaps:
                smaps[key] = self.status_map(*key)
            st = smaps[key].get(r["student_no"], {})
            g = gmeta[r["group_id"]]
            sl = slots[sidx[key]]
            recs.append({**r, "tags": sorted(tagmap.get(r["id"], [])), "bytes": count_bytes(r["content"]),
                         "name": m["name"], "grade": m["grade"], "class_no": m["class_no"], "number": m["number"],
                         "section": m.get("section") or "", "active": bool(m["active"]), "gone": bool(m.get("gone")),
                         "slot_label": sl["label"], "group_name": g["name"], "gkind": g["kind"], "semester": g["semester"],
                         "status": st.get("status", "progress"), "closed": bool(st.get("closed")), "stale": bool(st.get("stale")),
                         "has_final": bool(st.get("has_final")), "slot_order": sidx[key]})
        scope, slot = flt.get("scope") or "", flt.get("slot") or ""
        status, q = flt.get("status") or "all", (flt.get("q") or "").strip()

        def keep(r):
            if not flt.get("inactive") and not r["active"]:
                return False
            if scope.startswith("c:"):
                if f"c:{r['grade']}-{r['class_no']}" != scope:
                    return False
            elif scope.startswith("s:"):
                _, gid, sec = scope.split(":", 2)
                if r["group_id"] != int(gid) or r["section"] != sec:
                    return False
            if slot.startswith("i:") and r["item"] != slot[2:]:
                return False
            if slot.startswith("g:"):
                _, gid, it = slot.split(":", 2)
                if (r["group_id"], r["item"]) != (int(gid), it):
                    return False
            if status == "open" and r["closed"]:
                return False
            if status == "closed" and not r["closed"]:
                return False
            if q and not any(q in (r[k] or "") for k in ("name", "student_no", "content", "title")):
                return False
            return True

        base = [r for r in recs if keep(r)]
        counts = {}
        untagged = 0
        for r in base:
            if not r["tags"]:
                untagged += 1
            for t in r["tags"]:
                counts[t] = counts.get(t, 0) + 1
        tags = [{**t, "count": counts.get(t["id"], 0)} for t in self.d.q("SELECT id, name FROM tags ORDER BY sort_order, name")]
        tid = None if tag_id in (None, "") else int(tag_id)
        if tid is None:
            sel = []
        elif tid == 0:
            sel = [r for r in base if not r["tags"]]
        else:
            sel = [r for r in base if tid in r["tags"]]
        sel.sort(key=lambda r: (r["grade"] or 99, r["class_no"] or 999, r["number"] or 999, r["student_no"], r["slot_order"],
                                r["pos"] is None, r["pos"] or 0, r["kind"] == "record", r["seq"] or 0, r["id"]))
        items = []
        for it in ("autonomy", "career", "behavior", "subject", "club"):
            if any(s["item"] == it for s in slots):
                items.append({"key": f"i:{it}", "label": ITEM_LABEL[it] + (" 전체" if it in ("subject", "club") else "")})
        return {
            "tags": tags, "untagged": untagged, "records": sel,
            "students": len({r["student_no"] for r in sel}),
            "options": {
                "classes": [{"key": k, "label": f"{v[0]}학년 {v[1]}반"} for k, v in sorted(classes.items(), key=lambda x: x[1])],
                "sections": [{"key": k, "label": f"{v[0]}({v[1]}학기) · {v[2]}" if v[1] else f"{v[0]} · {v[2]}"} for k, v in sorted(sections.items(), key=lambda x: x[1])],
                "items": items,
                "slots": [{"key": f"g:{s['group_id']}:{s['item']}", "label": s["label"]} for s in slots if s["kind"] != "homeroom"],
            },
        }

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

    def add_existing_bulk(self, gid, item, rows, kind="existing"):
        """여러 학생 한꺼번에 — 전부 넣거나 전부 취소.
        kind='existing': 이미 쓴 생기부(학생당 한 줄). kind='record': 학생관찰기록(한 학생 여러 줄, 회차는 이어 붙임)."""
        self.slot(gid, item)
        for r in rows:
            self._member(gid, r["student_no"])
            self.require_open(gid, item, r["student_no"])
        with self.d.tx() as c:
            for r in rows:
                sno = str(r["student_no"])
                if kind == "record":
                    seq = (c.execute("SELECT COALESCE(MAX(seq),0) FROM records WHERE group_id=? AND item=? AND student_no=? AND kind='record'",
                                     (int(gid), item, sno)).fetchone()[0] or 0) + 1
                    c.execute(
                        "INSERT INTO records(group_id,item,student_no,kind,seq,date,title,content,source) VALUES(?,?,?,'record',?,?,?,?,?)",
                        (int(gid), item, sno, seq, (r.get("date") or "").strip(), (r.get("title") or "").strip(), r["content"].strip(), "record-bulk"),
                    )
                else:
                    c.execute(
                        "INSERT INTO records(group_id,item,student_no,kind,seq,title,content,source) VALUES(?,?,?,'existing',NULL,?,?,?)",
                        (int(gid), item, sno, "이미 쓴 생기부", r["content"].strip(), "existing-bulk"),
                    )
                self._stale(c, gid, item, sno)
        return len(rows)

    def finals_bulk_view(self, gid, item):
        """기존 완성문 → 최종안 일괄: 학생마다 기존 완성문 목록(오래된 것부터)과 지금 최종안·마감."""
        self.slot(gid, item)
        exist = {}
        for r in self.d.q("SELECT id, student_no, title, content, created_at, updated_at FROM records WHERE group_id=? AND item=? AND kind='existing' ORDER BY id",
                          (int(gid), item)):
            exist.setdefault(r["student_no"], []).append({"id": r["id"], "title": r["title"], "content": r["content"], "bytes": count_bytes(r["content"]),
                                                          "created_at": r["created_at"], "updated_at": r["updated_at"]})
        finals = {f["student_no"]: f for f in self.d.q("SELECT student_no, text, closed FROM finals WHERE group_id=? AND item=?", (int(gid), item))}
        out = []
        for m in self.d.members(gid):
            f = finals.get(m["student_no"])
            out.append({"student_no": m["student_no"], "name": m["name"], "grade": m["grade"], "class_no": m["class_no"], "number": m["number"],
                        "active": bool(m["active"]), "closed": bool(f and f["closed"]), "final": (f["text"] if f else "") or "",
                        "existing": exist.get(m["student_no"], [])})
        return out

    def finals_from_existing(self, gid, item, picks):
        """picks: [{student_no, record_id}] — 고른 기존 완성문을 그대로 최종안으로. 전부 하거나 전부 취소.
        되돌리기용으로 바꾸기 전 최종안과 새로 넣은 글을 돌려준다."""
        self.slot(gid, item)
        active = {m["student_no"]: m for m in self.d.members(gid) if m["active"]}
        seen, undo = set(), []
        with self.d.tx() as c:
            for p in picks:
                sno = str(p.get("student_no") or "")
                if sno in seen:
                    raise DbError("같은 학생이 두 번 들어 있습니다.")
                seen.add(sno)
                if sno not in active:
                    raise DbError(f"보낼 수 없는 학생입니다({sno}): 명렬에 없거나 비활성입니다.")
                self.require_open(gid, item, sno)
                r = c.execute("SELECT * FROM records WHERE id=?", (int(p.get("record_id") or 0),)).fetchone()
                if not r or r["group_id"] != int(gid) or r["item"] != item or r["student_no"] != sno or r["kind"] != "existing":
                    raise DbError(f"{active[sno]['name']}: 기존 완성문이 바뀌었습니다. 창을 다시 열어 주세요.")
                prev = c.execute("SELECT text, source, meta, stale FROM finals WHERE group_id=? AND item=? AND student_no=?", (int(gid), item, sno)).fetchone()
                undo.append({"student_no": sno, "prev": dict(prev) if prev else None, "now": r["content"]})
                self._upsert_final(c, gid, item, sno, r["content"], f"record:{r['id']}", {"op": "record", "kind": "existing", "bulk": True})
        return len(seen), undo

    def undo_finals(self, gid, item, undo):
        """일괄 보내기 되돌리기: 그 뒤로 최종안을 고치거나 마감하지 않은 학생만 되돌린다."""
        self.slot(gid, item)
        done, skipped = 0, []
        with self.d.tx() as c:
            for u in undo:
                sno = u["student_no"]
                cur = c.execute("SELECT text, closed FROM finals WHERE group_id=? AND item=? AND student_no=?", (int(gid), item, sno)).fetchone()
                if not cur or cur["closed"] or cur["text"] != u["now"]:
                    skipped.append(sno)
                    continue
                p = u["prev"]
                if p is None:
                    c.execute("DELETE FROM finals WHERE group_id=? AND item=? AND student_no=?", (int(gid), item, sno))
                else:
                    c.execute("UPDATE finals SET text=?, source=?, meta=?, stale=?, updated_at=datetime('now','localtime') WHERE group_id=? AND item=? AND student_no=?",
                              (p["text"], p["source"], p["meta"], p["stale"], int(gid), item, sno))
                done += 1
        return done, skipped

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
        # 마감 확인·변경 확인·쓰기를 한 잠금(트랜잭션) 안에서: 그 사이 다른 저장이 끼지 않는다
        with self.d.tx() as c:
            r = self.record(rid)
            self.require_open(r["group_id"], r["item"], r["student_no"])
            if data.get("expect") and not self._same(self.record_state(rid), data["expect"]):
                # 태그별 기록: 화면에 불러온 뒤 다른 곳에서 바뀌었으면 덮지 않는다
                raise ConflictError("이 기록은 화면을 연 뒤 다른 곳에서 바뀌었습니다. 지금 내용을 불러와 확인한 뒤 고쳐 주세요.")
            self._write_record(c, r, data)

    def _write_record(self, c, r, data):
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
        if fields:
            sets = ", ".join(f"{k}=?" for k in fields)
            c.execute(f"UPDATE records SET {sets}, updated_at=datetime('now','localtime') WHERE id=?", (*fields.values(), r["id"]))
        if "tag_ids" in data:
            old = sorted(x[0] for x in c.execute("SELECT tag_id FROM record_tags WHERE record_id=?", (r["id"],)).fetchall())
            new = sorted({int(t) for t in data["tag_ids"] or []})
            if old != new:
                c.execute("DELETE FROM record_tags WHERE record_id=?", (r["id"],))
                for tid in new:
                    c.execute("INSERT OR IGNORE INTO record_tags(record_id, tag_id) VALUES(?,?)", (r["id"], tid))
                c.execute("UPDATE records SET tags_ver=COALESCE(tags_ver,0)+1 WHERE id=?", (r["id"],))
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

    def delete_records(self, rids):
        """여러 기록을 한꺼번에 지운다(정제 후보 포함). 마감된 학생의 기록이 하나라도 있으면 아무것도 지우지 않는다."""
        ids = sorted({int(x) for x in rids or []})
        if not ids:
            raise DbError("지울 기록을 고르세요.")
        marks = ",".join("?" * len(ids))
        rows = self.d.q(f"SELECT id, group_id, item, student_no FROM records WHERE id IN ({marks})", tuple(ids))
        if len(rows) != len(ids):
            raise DbError("이미 지워진 기록이 있습니다. 화면을 새로 고친 뒤 다시 골라 주세요.")
        slots = {(r["group_id"], r["item"], r["student_no"]) for r in rows}
        for gid, item, sno in slots:
            self.require_open(gid, item, sno)
        with self.d.tx() as c:
            c.execute(f"DELETE FROM results WHERE record_id IN ({marks})", tuple(ids))
            c.execute(f"DELETE FROM records WHERE id IN ({marks})", tuple(ids))
            for gid, item, sno in slots:
                self._stale(c, gid, item, sno)
        return {"deleted": len(ids), "students": len({r["student_no"] for r in rows})}

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
    def _pair_cols(self, gid, item, sno, target):
        """표에 붙일 합산 칸: target(이 학생 목표), first_bytes(1학기), pair_total."""
        pi = self.pair_info(gid, item, sno)
        if pi and pi["role"] == "second":
            return {"target": pi["target"], "first_bytes": pi["first_bytes"], "pair_total": pi["total"]}
        return {"target": target}

    def batch_info(self, gid, item):
        """학생마다 일괄 종합 가능 여부."""
        g, target = self.slot(gid, item)
        sts = self.status_map(gid, item)
        out = []
        for m in self.d.members(gid):
            recs = self.d.q("SELECT id, kind, content, weight FROM records WHERE group_id=? AND item=? AND student_no=? ORDER BY pos IS NULL, pos, kind='record', COALESCE(seq,0), id",
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
                "results": len(slot_res), "status": (sts.get(m["student_no"]) or {}).get("status", "none"),
                **self._pair_cols(gid, item, m["student_no"], target),
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

    def close_info(self, gid, item):
        """일괄 마감 창: 학생마다 상태·최종안 바이트·목표·확인 사항."""
        _, target = self.slot(gid, item)
        sts = self.status_map(gid, item)
        out = []
        for m in self.d.members(gid):
            o = sts.get(m["student_no"], {})
            pc = self._pair_cols(gid, item, m["student_no"], target)
            fb = o.get("final_bytes")
            notes = []
            if o.get("stale"):
                notes.append("채택 후 기록 변경")
            if fb and pc.get("target") and fb > pc["target"]:
                notes.append("목표 분량 초과")
            if pc.get("pair_total") and fb and (pc.get("first_bytes") or 0) + fb > pc["pair_total"]:
                notes.append("1·2학기 합산 초과")
            out.append({"student_no": m["student_no"], "name": m["name"], "grade": m["grade"], "class_no": m["class_no"], "number": m["number"],
                        "active": bool(m["active"]), "status": o.get("status", "none"), "final_bytes": fb, "notes": notes, **pc})
        return {"target": target, "students": out}

    def close_many(self, gid, item, snos, closed):
        """여러 학생 마감/해제를 한 번에. 최종안이 없거나 비활성인 학생은 건너뛴다. 반환: (바꾼 학번, 건너뛴 [학번, 이유])."""
        self.slot(gid, item)
        active = {m["student_no"]: bool(m["active"]) for m in self.d.members(gid)}
        done, skipped = [], []
        with self.d.tx() as c:
            for sno in dict.fromkeys(str(x) for x in snos):
                if sno not in active:
                    skipped.append([sno, "명렬에 없음"])
                    continue
                f = c.execute("SELECT text, closed FROM finals WHERE group_id=? AND item=? AND student_no=?", (int(gid), item, sno)).fetchone()
                if closed and not active[sno]:
                    skipped.append([sno, "비활성"])
                    continue
                if closed and not (f and (f["text"] or "").strip()):
                    skipped.append([sno, "최종안 없음"])
                    continue
                if not f or bool(f["closed"]) == bool(closed):
                    skipped.append([sno, "이미 마감" if closed else "마감 아님"])
                    continue
                c.execute("UPDATE finals SET closed=?, closed_at=CASE WHEN ? THEN datetime('now','localtime') ELSE NULL END WHERE group_id=? AND item=? AND student_no=?",
                          (1 if closed else 0, 1 if closed else 0, int(gid), item, sno))
                done.append(sno)
        return done, skipped

    # ---------- 내보내기 ----------
    def export_rows(self, gid, item, only_closed=False, order="no"):
        _, target = self.slot(gid, item)
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
                         "closed": closed, "text": text, "bytes": count_bytes(text) if text else 0,
                         **self._pair_cols(gid, item, m["student_no"], target)})
        if order == "name":
            rows.sort(key=lambda r: (r["name"], r["student_no"]))
        else:
            rows.sort(key=lambda r: r["student_no"])
        return rows


    def pair_groups(self, gid):
        """1·2학기 합산 과목이면 (1학기 담당, 2학기 담당, 합산 바이트). 아니면 None."""
        g = self.d.group(gid)
        if g["kind"] != "subject":
            return None
        if g.get("pair_id") and g.get("pair_total") and g["semester"] == 2:
            p = self.d.group(g["pair_id"])
            if p["kind"] == "subject" and p["semester"] == 1:
                return p, g, int(g["pair_total"])
        if g["semester"] == 1:
            s2 = next((x for x in self.d.groups() if x.get("pair_id") == g["id"] and x.get("pair_total") and x["semester"] == 2 and x["kind"] == "subject"), None)
            if s2:
                return g, s2, int(s2["pair_total"])
        return None

    def export_combined(self, gid, only_closed=False, order="no"):
        """1·2학기 합산 과목을 한 학생 한 줄로: 1학기 최종안, 빈 줄 하나, 2학기 최종안(생기부 조회 화면처럼).
        only_closed면 두 학기 모두 마감한 학생만. 바이트는 두 최종안의 합(빈 줄은 세지 않음)."""
        pg = self.pair_groups(gid)
        if not pg:
            raise DbError("1·2학기 합산으로 연결된 과목이 아닙니다.")
        g1, g2, total = pg
        fin = lambda g: {f["student_no"]: f for f in self.d.q("SELECT * FROM finals WHERE group_id=? AND item='subject'", (g["id"],))}
        f1, f2 = fin(g1), fin(g2)
        mem = {}
        for g in (g1, g2):
            for m in self.d.members(g["id"]):
                if m["active"]:
                    mem.setdefault(m["student_no"], m)
        rows = []
        for sno, m in mem.items():
            a, b = f1.get(sno), f2.get(sno)
            t1, t2 = (a["text"] if a else "") or "", (b["text"] if b else "") or ""
            c1, c2 = bool(a and a["closed"]), bool(b and b["closed"])
            if only_closed and not (c1 and c2):
                continue
            b1, b2 = count_bytes(t1) if t1 else 0, count_bytes(t2) if t2 else 0
            rows.append({"student_no": sno, "name": m["name"], "grade": m["grade"], "class_no": m["class_no"], "number": m["number"],
                         "text1": t1, "text2": t2, "text": "\n\n".join(x.strip() for x in (t1, t2) if x.strip()),
                         "closed1": c1, "closed2": c2, "closed": c1 and c2, "bytes1": b1, "bytes2": b2, "bytes": b1 + b2, "total": total})
        if order == "name":
            rows.sort(key=lambda r: (r["name"], r["student_no"]))
        else:
            rows.sort(key=lambda r: r["student_no"])
        return {"first": g1["label"], "second": g2["label"], "total": total, "rows": rows}


def _result_out(r):
    out = dict(r)
    out["locked"] = bool(r["locked"])
    out["bytes"] = count_bytes(r["text"])
    try:
        out["meta"] = json.loads(r["meta"] or "{}")
    except ValueError:
        out["meta"] = {}
    return out
