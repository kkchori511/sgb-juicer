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
    diffs = []
    for n, (i1, i2, j1, j2) in enumerate(groups):
        s, e = _src_range(pa, i1, i2, len(a))
        bs, be = _src_range(pb, j1, j2, len(b))
        lo, hi = _line_of(starts, s), _line_of(starts, max(s, e - 1))
        boxes = [alines[i].get("box") for i in range(lo, hi + 1) if i < len(alines) and alines[i].get("box")]
        box = [min(x[0] for x in boxes), min(x[1] for x in boxes), max(x[2] for x in boxes), max(x[3] for x in boxes)] if boxes else None
        kind = "text"
        piece = a[s:e]
        if not b[bs:be].strip() and fig_words and piece.strip():
            # CLOVA만 읽은 줄이 AI 그림 설명에 다 들어 있으면 그림 속 글자
            parts = [re.sub(r"\s", "", x) for x in piece.split("\n") if x.strip()]
            if parts and all(p in fig_words for p in parts):
                kind = "figure"
        diffs.append({
            "id": f"d{n}", "kind": kind, "a": [s, e], "b": [bs, be], "clova": piece, "ai": b[bs:be],
            "before": a[max(0, s - CTX):s].replace("\n", " "), "after": a[e:e + CTX].replace("\n", " "),
            "lines": [lo, hi], "box": box,
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
    reps = []
    for f in cmp["fig_pos"]:
        p = f["pos"]
        for s, e in spans:
            if s < p < e:
                p = e
        reps.append((p, p, ("\n[그림: " + f["desc"] + "]") if p else ("[그림: " + f["desc"] + "]\n")))
    return reps


def resolve(cmp: dict, review: dict | None, figures: bool = True, ai_page: dict | None = None) -> str:
    """사람이 고른 대로 최종 글.
    review: {"d": {id: {"pick": "clova"|"ai"|"edit", "text"}}, "page": None|"clova"|"ai"|"edit", "text"}
    page를 고르면 페이지 통째로(크게 다른 페이지, [이 페이지 모두 AI 쪽]이 아닌 통째 선택)."""
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
            reps.append((d["a"][0], d["a"][1], d["ai"]))
        elif c.get("pick") == "edit":
            reps.append((d["a"][0], d["a"][1], nfc(c.get("text") or "")))
    if figures:
        reps += _fig_reps(cmp, [tuple(d["a"]) for d in cmp["diffs"]])
    return _apply(cmp["a"], reps).strip()


def _apply(text, reps):
    """(시작, 끝, 새 글) 목록을 뒤에서부터 바꾼다. 같은 자리 삽입은 들어온 순서대로."""
    out = text
    for s, e, new in sorted(reps, key=lambda r: (r[0], r[1]), reverse=True):
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
    clova = sc.get("clova") or []
    ai = (sc.get("ai") or {}).get("pages") or []
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
        elif cp:
            out.append(ocr.page_text(cp))
        elif ap_ok:
            out.append(nfc(ocr_vision.page_text(ap, figs)))
        else:
            out.append("")
    return out


# ---------- 3단계: 글자 보정 제안(그림 없이 글만, 사용자가 버튼을 눌렀을 때만) ----------
FIX_SYSTEM = (
    "당신은 학생 학습지 OCR 결과를 비교하는 도우미입니다. 같은 손글씨 학습지를 두 OCR(CLOVA, AI)이 따로 읽었고, "
    "두 결과가 다른 곳만 아래에 있습니다. 당신은 그림을 볼 수 없습니다.\n"
    "각 차이마다 학생이 실제로 썼을 가능성이 높은 쪽을 고르세요.\n"
    "- pick: \"clova\"(CLOVA 쪽), \"ai\"(AI 쪽), \"merge\"(두 후보의 글자를 섞은 것 — text에 씀) 중 하나.\n"
    "- 목표는 학생이 쓴 글자 그대로입니다. 맞춤법이 맞다는 이유만으로 고르지 마세요(학생이 틀리게 썼을 수 있음). "
    "앞뒤 문맥에서 실제로 있는 낱말·말이 되는 문장인지, 글자 모양이 비슷해 헷갈리기 쉬운지를 근거로 하세요.\n"
    "- 한쪽이 '(없음)'이면 그 OCR이 글자를 빠뜨렸거나 다른 쪽이 덧붙인 것입니다.\n"
    "- 두 후보에 없는 새 낱말이나 내용을 만들지 마세요.\n"
    "- reason은 20자 안팎 한국어.\n"
    "출력은 JSON 하나만: {\"items\": [{\"id\": \"d0\", \"pick\": \"clova\", \"text\": \"\", \"reason\": \"...\"}]}"
)


def fix_user(diffs, clean=lambda s: s):
    """보낼 글: 차이 id, 앞뒤 문맥, 두 후보. clean으로 학번·이름을 지운다."""
    out = []
    for d in diffs:
        if d["kind"] != "text":
            continue
        out.append(f"[{d['id']}] 앞: {clean(d['before'])} | CLOVA: {clean(d['clova']) or '(없음)'} | AI: {clean(d['ai']) or '(없음)'} | 뒤: {clean(d['after'])}")
    return "\n".join(out)


def parse_fix(obj, diffs):
    """AI 답 → {id: {"pick", "text", "reason", "new"}}. new: 두 후보에 없는 글자를 만들었는지."""
    by = {d["id"]: d for d in diffs if d["kind"] == "text"}
    out = {}
    for it in (obj or {}).get("items") or []:
        if not isinstance(it, dict) or it.get("id") not in by or it.get("pick") not in ("clova", "ai", "merge"):
            continue
        d = by[it["id"]]
        text = d["clova"] if it["pick"] == "clova" else d["ai"] if it["pick"] == "ai" else nfc(str(it.get("text") or ""))[:200]
        pool = set(re.sub(r"\s", "", d["clova"] + d["ai"]))
        new = any(ch not in pool for ch in re.sub(r"\s", "", text))
        if it["pick"] == "merge" and text in (d["clova"], d["ai"]):
            it["pick"] = "clova" if text == d["clova"] else "ai"
        out[it["id"]] = {"pick": it["pick"], "text": text, "reason": str(it.get("reason") or "")[:80], "new": new}
    return out
