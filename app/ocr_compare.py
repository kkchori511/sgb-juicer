"""하이브리드 OCR 비교: CLOVA 글과 AI 글을 글자 단위로 맞대어 다른 곳을 찾고, 사람이 고른 대로 최종 글을 만든다.

- 띄어쓰기·줄바꿈은 비교에서 뺀다. 같은 뜻의 기호(℃와 °C 등)는 같게 본다.
- 기본은 CLOVA 글. 고르지 않은 차이는 CLOVA 쪽을 쓴다(사용자 결정 2026-11-22).
- CLOVA가 본문에 넣은 그림 속 글자(AI는 그림 설명에 넣음)는 '그림 속 글자'로 따로 둔다.
- API를 부르지 않는다. 저장된 두 결과만 쓴다.
"""
import difflib
import re
import unicodedata

BIG_RATIO = 0.75  # 이보다 덜 비슷하면 페이지 통째로 비교
MERGE_GAP = 1  # 차이 사이 같은 글자가 이만큼 이하이면 한 차이로 묶는다
CTX = 10

EQUIV = {"℃": "°C", "˚": "°", "～": "~", "“": '"', "”": '"', "‘": "'", "’": "'", "，": ",", "．": ".", "：": ":"}


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def _compact(text: str, skip=()):
    """(비교용 글자 목록, 각 글자의 원문 위치). skip: 비교에서 뺄 원문 구간 [(s, e)]."""
    chars, pos = [], []
    for i, ch in enumerate(text):
        if ch.isspace() or any(s <= i < e for s, e in skip):
            continue
        for c in EQUIV.get(ch, ch):
            chars.append(c)
            pos.append(i)
    return chars, pos


def _src_range(pos, i1, i2, n):
    if i1 == i2:
        p = pos[i1] if i1 < len(pos) else n
        return p, p
    return pos[i1], pos[i2 - 1] + 1


def _line_starts(text):
    starts = [0]
    for m in re.finditer("\n", text):
        starts.append(m.end())
    return starts


def _line_of(starts, p):
    lo = 0
    for i, s in enumerate(starts):
        if s <= p:
            lo = i
    return lo


def clova_text(page) -> str:
    return nfc("\n".join(l["text"] for l in (page or {}).get("lines") or []))


def ai_text(page) -> str:
    return nfc("\n".join(l["text"] for l in (page or {}).get("lines") or []))


def masked_spans(clova_page: dict, mask: float):
    """AI에 가려 보낸 머리글 안의 CLOVA 줄(줄 가운데가 가린 높이 위) → 원문 구간."""
    h = (clova_page or {}).get("h") or 0
    if not mask or not h:
        return []
    out, pos = [], 0
    for l in (clova_page or {}).get("lines") or []:
        t = nfc(l["text"])
        box = l.get("box")
        if box and (box[1] + box[3]) / 2 < h * mask:
            out.append((pos, pos + len(t)))
        pos += len(t) + 1
    return out


def compare(clova_page: dict, ai_page: dict, mask: float = 0.0) -> dict:
    """{"a", "b", "ratio", "big", "diffs": [{id, kind, a:[s,e], b:[s,e], clova, ai, before, after, lines, box}], "fig_pos": [...]}
    mask: AI에 보낼 때 가린 위쪽 비율. 그 안의 CLOVA 줄은 비교하지 않고 CLOVA 글 그대로 둔다."""
    a, b = clova_text(clova_page), ai_text(ai_page)
    ca, pa = _compact(a, masked_spans(clova_page, mask))
    cb, pb = _compact(b)
    sm = difflib.SequenceMatcher(None, ca, cb, autojunk=False)
    ratio = sm.ratio() if (ca or cb) else 1.0
    ops = [o for o in sm.get_opcodes()]
    # 가까운 차이 묶기
    groups = []
    for k, (op, i1, i2, j1, j2) in enumerate(ops):
        if op == "equal":
            continue
        if groups:
            g = groups[-1]
            between = [o for o in ops if o[0] == "equal" and o[1] >= g[1] and o[2] <= i1]
            if all(o[2] - o[1] <= MERGE_GAP for o in between):
                groups[-1] = (g[0], i2, g[2], j2)
                continue
        groups.append((i1, i2, j1, j2))
    starts = _line_starts(a)
    alines = (clova_page or {}).get("lines") or []
    fig_words = re.sub(r"\s", "", " ".join(f.get("desc", "") for f in (ai_page or {}).get("figures") or []))
    # 원문 한 글자가 비교 글자 여러 개로 펼쳐진 경우(℃→°C) 그 글자를 통째로 넣는다(M4: 100℃/100°F → ℃ ↔ °F)
    def _widen(i1, i2, j1, j2):
        changed = True
        while changed:
            changed = False
            while 0 < i1 < len(pa) and pa[i1 - 1] == pa[i1] or (0 < j1 < len(pb) and pb[j1 - 1] == pb[j1]):
                i1, j1 = max(0, i1 - 1), max(0, j1 - 1)
                changed = True
            while (0 < i2 < len(pa) and pa[i2] == pa[i2 - 1]) or (0 < j2 < len(pb) and pb[j2] == pb[j2 - 1]):
                i2, j2 = min(len(pa), i2 + 1), min(len(pb), j2 + 1)
                changed = True
        return i1, i2, j1, j2
    groups = [_widen(*g) for g in groups]
    diffs = []
    for n, (i1, i2, j1, j2) in enumerate(groups):
        s, e = _src_range(pa, i1, i2, len(a))
        bs, be = _src_range(pb, j1, j2, len(b))
        lo, hi = _line_of(starts, s), _line_of(starts, max(s, e - 1))
        boxes = [alines[i].get("box") for i in range(lo, hi + 1) if i < len(alines) and alines[i].get("box")]
        box = [min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)] if boxes else None
        # 확대 그림이 이웃 줄 글씨를 물지 않게: 윗줄 아래 끝·아랫줄 위 끝(겹치지 않을 때만)
        prev_b = alines[lo - 1].get("box") if 0 < lo <= len(alines) else None
        next_b = alines[hi + 1].get("box") if hi + 1 < len(alines) else None
        clip = [prev_b[3] if prev_b and box and prev_b[3] < box[1] else None,
                next_b[1] if next_b and box and next_b[1] > box[3] else None]
        kind = "text"
        piece = a[s:e]
        if not b[bs:be].strip() and fig_words and piece.strip():
            # CLOVA만 읽은 줄이 AI 그림 설명에 다 들어 있으면 그림 속 글자
            parts = [re.sub(r"\s", "", x) for x in piece.split("\n") if x.strip()]
            if parts and all(p in fig_words for p in parts):
                kind = "figure"
        # Qwen 쪽을 고를 때는 앞뒤 띄어쓰기·줄바꿈까지 Qwen 원문대로(M5: '더끓였다', 줄 붙음 방지)
        ws, we = s, e
        while ws > 0 and a[ws - 1].isspace():
            ws -= 1
        while we < len(a) and a[we].isspace():
            we += 1
        bws, bwe = bs, be
        while bws > 0 and b[bws - 1].isspace():
            bws -= 1
        while bwe < len(b) and b[bwe].isspace():
            bwe += 1
        if ws == 0:
            bws = bs  # 맨 앞/맨 끝은 바깥 공백을 끌어오지 않는다
        if we == len(a):
            bwe = be
        diffs.append({
            "id": f"d{n}", "kind": kind, "a": [s, e], "b": [bs, be], "clova": piece, "ai": b[bs:be],
            "a_ws": [ws, we], "ai_ws": b[bws:bwe],
            "before": a[max(0, s - CTX):s].replace("\n", " "), "after": a[e:e + CTX].replace("\n", " "),
            "lines": [lo, hi], "box": box, "clip": clip,
        })
    # AI 그림 설명을 CLOVA 글 어디에 넣을지: AI 줄 끝 → 맞는 CLOVA 위치 → 그 줄 끝
    blines = _line_starts(b)
    blocks = sm.get_matching_blocks()
    fig_pos = []
    for f in (ai_page or {}).get("figures") or []:
        k = f.get("after_line", -1)
        if k < 0:
            fig_pos.append({"pos": 0, "desc": f["desc"]})
            continue
        bend = (blines[k + 1] - 1) if k + 1 < len(blines) else len(b)
        jb = sum(1 for p in pb if p < bend) - 1  # 그 줄 마지막 비교 글자
        ia = -1
        for blk in blocks:
            if blk.size and blk.b <= jb:
                ia = blk.a + min(jb - blk.b, blk.size - 1)
        if ia < 0:
            fig_pos.append({"pos": 0, "desc": f["desc"]})
            continue
        line = _line_of(starts, pa[ia])
        end = (starts[line + 1] - 1) if line + 1 < len(starts) else len(a)
        fig_pos.append({"pos": end, "desc": f["desc"]})
    return {"a": a, "b": b, "ratio": round(ratio, 3), "big": ratio < BIG_RATIO and bool(ca) and bool(cb), "diffs": diffs, "fig_pos": fig_pos}


def _fig_reps(cmp, spans=()):
    """그림 설명 넣기. 줄 끝이면 '\n[그림]', 줄 시작(맨 앞·바꾼 구간이 줄바꿈까지 먹은 뒤)이면 '[그림]\n'(R3)."""
    a = cmp["a"]
    reps = []
    for f in cmp["fig_pos"]:
        p = f["pos"]
        for s, e in spans:
            if s < p < e:
                p = e
        tag = "[그림: " + f["desc"] + "]"
        at_line_start = p == 0 or a[p - 1:p] == "\n"
        reps.append((p, p, (tag + "\n") if at_line_start else ("\n" + tag)))
    return reps


def resolve(cmp: dict, review: dict | None, figures: bool = True, ai_page: dict | None = None) -> str:
    """사람이 고른 대로 최종 글.
    review: {"d": {id: {"pick": "clova"|"ai"|"edit", "text"}}, "page": None|"clova"|"ai"|"edit", "text"}
    page를 고르면 페이지 통째로(크게 다른 페이지, [CLOVA 선택]/[Qwen 선택]이 크게 다른 쪽에서 쓰는 통째 선택)."""
    from .ocr_vision import page_text

    review = review or {}
    page = review.get("page")
    if page == "edit":
        return nfc(review.get("text") or "").strip()
    if page == "ai":
        return nfc(page_text(ai_page or {}, figures))
    if page == "clova" or cmp["big"]:
        return _apply(cmp["a"], _fig_reps(cmp) if figures else []).strip()
    dec = review.get("d") or {}
    reps = []
    for d in cmp["diffs"]:
        c = dec.get(d["id"]) or {}
        if d["kind"] == "figure" and not c:
            if figures:  # 그림 설명([그림: …])이 대신하므로 본문에 끼어든 이름표 줄은 뺀다
                reps.append((d["a"][0], d["a"][1], ""))
            continue
        if c.get("pick") == "ai":
            if "a_ws" in d:
                reps.append((d["a_ws"][0], d["a_ws"][1], d["ai_ws"]))
            else:
                reps.append((d["a"][0], d["a"][1], d["ai"]))
        elif c.get("pick") == "edit":
            reps.append((d["a"][0], d["a"][1], nfc(c.get("text") or "")))
    if figures:
        reps += _fig_reps(cmp, [tuple(d.get("a_ws") or d["a"]) for d in cmp["diffs"]])
    return _apply(cmp["a"], reps).strip()


def _apply(text, reps):
    """(시작, 끝, 새 글) 목록을 뒤에서부터 바꾼다. 같은 자리 삽입은 들어온 순서대로."""
    out = text
    # 뒤에서부터. 같은 자리에 여럿 넣을 때는 나중 것을 먼저 넣어 결과가 들어온 순서가 되게(L1)
    for _, (s, e, new) in sorted(enumerate(reps), key=lambda r: (r[1][0], r[1][1], r[0]), reverse=True):
        if not new and s < e:
            if s > 0 and e < len(out) and out[s - 1] == " " and out[e] == " ":
                e += 1
            elif out[s - 1:s] in ("\n", "") and out[e:e + 1] == "\n":
                e += 1  # 줄째 지운 경우 빈 줄을 남기지 않는다
        out = out[:s] + new + out[e:]
    return out


def unreviewed(cmp: dict, review: dict | None) -> int:
    review = review or {}
    if review.get("page"):
        return 0
    if cmp["big"]:
        return 1
    dec = review.get("d") or {}
    return sum(1 for d in cmp["diffs"] if d["kind"] == "text" and d["id"] not in dec)


def final_texts(sc: dict) -> list:
    """스캔 묶음의 페이지별 최종 글. 하이브리드면 비교·검토 결과, 한쪽만 있으면 그 결과."""
    from . import ocr, ocr_vision

    n = int(sc.get("pages") or 0)
    mode = sc.get("mode") or "clova"
    clova = (sc.get("clova") or []) if mode in ("clova", "hybrid") else []
    ai = ((sc.get("ai") or {}).get("pages") or []) if mode in ("ai", "hybrid") else []
    mask = (sc.get("ai") or {}).get("mask") or 0
    out = []
    for p in range(n):
        rv = (sc.get("review") or {}).get(str(p)) or {}
        figs = rv.get("figs", True)
        cp = clova[p] if p < len(clova) else None
        ap = ai[p] if p < len(ai) else None
        ap_ok = bool(ap) and not ap.get("error")
        cp_ok = bool(cp) and not cp.get("fail")
        if rv.get("page") == "edit":
            out.append(nfc(rv.get("text") or "").strip())
        elif cp_ok and ap_ok:
            out.append(resolve(compare(cp, ap, mask), rv, figs, ap))
        elif cp_ok:
            out.append(ocr.page_text(cp))
        elif ap_ok:  # CLOVA가 이 쪽을 못 읽었으면 정상인 Qwen 글(M1)
            out.append(nfc(ocr_vision.page_text(ap, figs)))
        else:
            out.append("")  # 둘 다 실패 — 실패 문구를 학생 내용에 넣지 않는다(화면은 '글자 없음')
    return out


# ---------- 3단계: 글자 보정 제안(그림 없이 글만, 사용자가 버튼을 눌렀을 때만) ----------
FIX_SYSTEM = (
    "당신은 학생 학습지 OCR 결과를 비교하는 도우미입니다. 같은 손글씨 학습지를 두 OCR(CLOVA, Qwen)이 따로 읽었고, "
    "두 결과가 다른 곳만 아래에 있습니다. 당신은 그림을 볼 수 없습니다.\n"
    "각 차이마다 학생이 실제로 썼을 가능성이 높은 쪽을 고르세요.\n"
    "- pick: \"clova\"(CLOVA 쪽), \"ai\"(Qwen 쪽), \"merge\"(두 후보의 글자만 순서대로 골라 섞은 것 — text에 씀) 중 하나.\n"
    "- 목표는 학생이 쓴 글자 그대로입니다. 맞춤법이 맞다는 이유만으로 고르지 마세요(학생이 틀리게 썼을 수 있음). "
    "앞뒤 문맥에서 실제로 있는 낱말·말이 되는 문장인지, 글자 모양이 비슷해 헷갈리기 쉬운지를 근거로 하세요.\n"
    "- 한쪽이 '(없음)'이면 그 OCR이 글자를 빠뜨렸거나 다른 쪽이 덧붙인 것입니다.\n"
    "- 두 후보에 없는 새 낱말이나 내용을 만들지 마세요.\n"
    "- reason은 20자 안팎 한국어.\n"
    "출력은 JSON 하나만: {\"items\": [{\"id\": \"d0\", \"pick\": \"clova\", \"text\": \"\", \"reason\": \"...\"}]}"
)


def redact(text: str, values=(), regexes=()) -> str:
    """신원 글자를 ○로 바꾼다(글자 수 유지 — 원문 위치로 자른 조각이 서로 맞게).
    values: 지울 값(이름·학번, 사이 띄어쓰기 허용), regexes: 그룹 1(없으면 전체)을 지울 정규식."""
    marks = [False] * len(text)
    pats = []
    for v in values:
        v = re.sub(r"\s", "", str(v or ""))
        if len(v) >= 2:
            pats.append((re.compile(r"[ \t]*".join(re.escape(ch) for ch in v)), 0))
    for r in regexes:  # 캡처 그룹이 있으면 그룹 모두(예: n학년 n반 n번의 세 숫자, Codex 재검토 R2), 없으면 전체
        pats.append((r, list(range(1, r.groups + 1)) or [0]))
    for r, gs in pats:
        for m in r.finditer(text):
            for g in (gs if isinstance(gs, list) else [gs]):
                if m.start(g) < 0:
                    continue
                for i in range(m.start(g), m.end(g)):
                    marks[i] = True
    return "".join("○" if mk and not ch.isspace() else ch for ch, mk in zip(text, marks))


def fix_user(cmp: dict, scrub=lambda t: t) -> str:
    """보낼 글: 차이 id, 앞뒤 문맥, 두 후보. scrub은 쪽 전체 글(CLOVA·Qwen 각각)에서 먼저 신원을 지우는 함수 —
    조각으로 자른 뒤 지우면 이름이 차이 경계에서 쪼개져 새어 나간다(Codex 검토 H3)."""
    A, B = scrub(cmp["a"]), scrub(cmp["b"])
    out = []
    for d in cmp["diffs"]:
        if d["kind"] != "text":
            continue
        s, e = d["a"]
        bs, be = d["b"]
        before = A[max(0, s - CTX):s].replace("\n", " ")
        after = A[e:e + CTX].replace("\n", " ")
        qb = B[bs:be]
        # CLOVA 쪽이 신원으로 지워진 자리면 Qwen 후보도 지운다(Qwen이 이름을 다르게 읽은 경우: 가나다/가누다)
        if "○" in A[s:e] or (A[s - 1:s] == "○" and A[e:e + 1] == "○"):
            qb = re.sub(r"\S", "○", qb)
        out.append(f"[{d['id']}] 앞: {before} | CLOVA: {A[s:e] or '(없음)'} | Qwen: {qb or '(없음)'} | 뒤: {after}")
    return "\n".join(out)


def _interleaves(text: str, a: str, b: str) -> bool:
    """text가 a와 b에서 순서를 지켜 글자를 골라 섞은 것인지(같은 글자를 두 번 쓰지 않음)."""
    from functools import lru_cache

    @lru_cache(maxsize=None)
    def ok(i, j, k):
        if i == len(text):
            return True
        ch = text[i]
        for jj in range(j, len(a)):
            if a[jj] == ch and ok(i + 1, jj + 1, k):
                return True
        for kk in range(k, len(b)):
            if b[kk] == ch and ok(i + 1, j, kk + 1):
                return True
        return False
    return ok(0, 0, 0)


def parse_fix(obj, diffs):
    """AI 답 → {id: {"pick", "text", "reason", "new"}}. new: 두 후보에 없는 글자를 만들었는지."""
    by = {d["id"]: d for d in diffs if d["kind"] == "text"}
    out = {}
    for it in (obj or {}).get("items") or []:
        if not isinstance(it, dict) or it.get("id") not in by or it.get("pick") not in ("clova", "ai", "merge"):
            continue
        d = by[it["id"]]
        text = d["clova"] if it["pick"] == "clova" else d["ai"] if it["pick"] == "ai" else nfc(str(it.get("text") or ""))[:200]
        sq = lambda t: re.sub(r"\s", "", t)
        unchecked = False
        if it["pick"] in ("clova", "ai") or text in (d["clova"], d["ai"]):
            new = False  # 후보 그대로(R6)
        elif len(sq(text)) > 60:
            new, unchecked = False, True  # 너무 길어 자동으로 확인 못 함 — '새 글자'로 단정하지 않음
        else:
            new = not _interleaves(sq(text), sq(d["clova"]), sq(d["ai"]))
        if it["pick"] == "merge" and text in (d["clova"], d["ai"]):
            it["pick"] = "clova" if text == d["clova"] else "ai"
        out[it["id"]] = {"pick": it["pick"], "text": text, "reason": str(it.get("reason") or "")[:80], "new": new, "unchecked": unchecked}
    return out


# ---------- 통째로 검토 쪽: AI로 조합하기(사용자 지정 2026-11-24) ----------
MERGE_SYSTEM = (
    "당신은 학생 학습지 OCR 결과를 합치는 도우미입니다. 같은 손글씨 학습지 한 쪽을 두 OCR(CLOVA, Qwen)이 따로 읽었는데 "
    "결과가 크게 다릅니다. 당신은 그림을 볼 수 없습니다.\n"
    "두 결과를 맞춰 보고 학생이 실제로 썼을 글을 한 편으로 만드세요.\n"
    "- 목표는 학생이 쓴 글자 그대로입니다. 맞춤법·띄어쓰기·문장을 고치거나 다듬지 마세요(학생이 틀리게 썼을 수 있음).\n"
    "- 두 결과 어디에도 없는 낱말이나 내용을 만들지 마세요. 한쪽에만 있는 내용은 앞뒤 문맥에 맞으면 넣습니다.\n"
    "- 같은 내용을 두 번 넣지 말고, 줄 순서는 학습지의 위에서 아래 순서를 따르세요.\n"
    "- ○는 지운 이름·학번입니다. ○는 고치지 말고 개수까지 그대로 두세요.\n"
    "- 그림 설명([그림: …])은 넣지 마세요.\n"
    "출력은 JSON 하나만: {\"text\": \"합친 글(줄바꿈은 \\n)\"}"
)


def merge_user(a: str, b: str) -> str:
    """보낼 글: 신원을 지운 두 쪽 전체 글(CLOVA·Qwen)."""
    return f"[CLOVA]\n{a}\n\n[Qwen]\n{b}"


def restore_ids(merged: str, sources) -> tuple[str, int]:
    """조합 글의 ○(지운 이름·학번)를 원문 글자로 되돌린다. sources: [(지운 글, 원문)] — 글자 수가 같다(redact).
    조합 글과 지운 글을 맞춰 보아 같은 자리로 이어진 ○ 묶음만 원문 글자로 바꾼다. → (되돌린 글, 못 되돌린 ○ 수)"""
    import difflib

    out = list(merged)
    todo = {i for i, ch in enumerate(merged) if ch == "○"}
    for scrubbed, orig in sources:
        if not todo or len(scrubbed) != len(orig):
            continue
        sm = difflib.SequenceMatcher(None, merged, scrubbed, autojunk=False)
        for a, b, n in sm.get_matching_blocks():
            if n - merged[a:a + n].count("○") < 2:
                continue  # ○만 맞은 묶음은 자리를 믿을 수 없음(앞뒤 글자도 같이 맞아야)
            for k in range(n):
                i, j = a + k, b + k
                if i in todo and scrubbed[j] == "○" and orig[j] != "○":
                    out[i] = orig[j]
                    todo.discard(i)
    return "".join(out), len(todo)


def new_words(merged: str, a: str, b: str) -> list:
    """두 OCR 글 어디에도 없는 낱말(띄어쓰기 무시) — 화면에서 ⚠로 표시."""
    pool = re.sub(r"\s", "", (a or "") + "\n" + (b or ""))
    out = []
    for w in re.findall(r"[^\s.,!?'\"()\[\]:;·~/-]+", merged or ""):
        if "○" in w or len(w) < 2 or w in out:
            continue
        if w not in pool:
            out.append(w)
    return out
