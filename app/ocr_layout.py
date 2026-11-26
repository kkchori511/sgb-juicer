"""스캔 쪽의 글 배치: 기울기 보정과 2단 나누기(사용자 지정 2026-11-26).

CLOVA가 돌려준 낱말 좌표(네 꼭짓점)만으로 계산한다(그림 처리·추가 호출 없음).
1. 기울기: 가로로 긴 낱말들의 윗변·아랫변 기울기의 가운데 값. 10° 이하면 좌표를 거꾸로 돌려 보정,
   넘거나 들쭉날쭉하면 보정하지 않고 '다시 스캔 권장'으로 알린다.
2. 단 나누기: 글 가운데(30~70%)에서 낱말이 가로지르지 않는 세로 빈 띠(단 사이 여백)를 찾는다.
   여백을 가로지르는 줄(넓은 제목·머리글 등)은 그 자리에 두고, 그 사이 구간마다 왼쪽 단 → 오른쪽 단 순서로 줄을 만든다.
   머리글이 단마다 따로 있으면(가로 A3에 학습지 두 쪽) 왼쪽 단의 머리글이 맨 앞에 온다.
"""
import math
import re

MAX_FIX_DEG = 10.0  # 이보다 많이 기울면 보정하지 않고 다시 스캔을 권한다
MODES = ("auto", "off", "two")  # 자동 / 나누지 않음 / 2단으로 나누기


def words_of(img: dict) -> list:
    """CLOVA 한 쪽의 fields → [[글, x0, y0, x1, y1, x2, y2, x3, y3], ...] (꼭짓점 순서: 왼위·오위·오아래·왼아래)."""
    out = []
    for f in img.get("fields") or []:
        vs = ((f.get("boundingPoly") or {}).get("vertices") or [])
        if len(vs) != 4 or not all(isinstance(v.get("x"), (int, float)) and isinstance(v.get("y"), (int, float)) for v in vs):
            continue
        t = str(f.get("inferText") or "")
        if t.strip():
            out.append([t] + [round(float(c), 1) for v in vs for c in (v["x"], v["y"])])
    return out


def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return 0.0 if not n else xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def skew(words) -> dict:
    """{"deg": 보정할 각도(0이면 보정 안 함), "measured": 잰 각도, "warn": 다시 스캔 권장 여부}."""
    angs = []
    for w in words:
        x0, y0, x1, y1, x2, y2, x3, y3 = w[1:9]
        top = (x1 - x0, y1 - y0)
        bot = (x2 - x3, y2 - y3)
        width = math.hypot(*top)
        height = math.hypot(x3 - x0, y3 - y0)
        if len(w[0].strip()) < 2 or width < height * 1.5 or width < 8:
            continue
        for dx, dy in (top, bot):
            if dx > 0:
                angs.append(math.degrees(math.atan2(dy, dx)))
    if len(angs) < 6:
        return {"deg": 0.0, "measured": 0.0, "warn": False}
    med = _median(angs)
    close = sum(1 for a in angs if abs(a - med) <= 1.5) / len(angs)
    reliable = close >= 0.5
    warn = abs(med) > MAX_FIX_DEG or (not reliable and abs(med) > 2)
    deg = med if reliable and abs(med) <= MAX_FIX_DEG and abs(med) >= 0.3 else 0.0
    return {"deg": round(deg, 2), "measured": round(med, 2), "warn": warn}


def _rot(x, y, cx, cy, deg):
    if not deg:
        return x, y
    r = math.radians(-deg)
    c, s = math.cos(r), math.sin(r)
    dx, dy = x - cx, y - cy
    return cx + dx * c - dy * s, cy + dx * s + dy * c


def _rects(words, w, h, deg):
    """낱말마다 보정한 좌표의 사각형(rx0, ry0, rx1, ry1)과 원래 좌표의 사각형."""
    cx, cy = (w or 0) / 2, (h or 0) / 2
    out = []
    for i, wd in enumerate(words):
        pts = [(wd[1 + k * 2], wd[2 + k * 2]) for k in range(4)]
        rp = [_rot(x, y, cx, cy, deg) for x, y in pts]
        out.append({"i": i, "t": wd[0], "x0": min(p[0] for p in rp), "x1": max(p[0] for p in rp),
                    "y0": min(p[1] for p in rp), "y1": max(p[1] for p in rp),
                    "box": [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]})
    return out


def _rows(items):
    """낱말을 높이가 겹치는 것끼리 한 줄로(위에서 아래, 줄 안은 왼쪽에서 오른쪽)."""
    rows = []
    for it in sorted(items, key=lambda r: (r["y0"] + r["y1"]) / 2):
        yc, hh = (it["y0"] + it["y1"]) / 2, max(it["y1"] - it["y0"], 1)
        best = None
        for row in rows[-3:]:
            # 높이가 겹치는 정도로 판단(손글씨는 인쇄 글자보다 크고 조금 아래에 쓰여도 같은 줄로)
            ov = min(it["y1"], row["yc"] + row["h"] / 2) - max(it["y0"], row["yc"] - row["h"] / 2)
            if ov >= 0.4 * max(min(hh, row["h"]), 1):
                best = row
        if best is None:
            best = {"items": [], "yc": yc, "h": hh}
            rows.append(best)
        best["items"].append(it)
        n = len(best["items"])
        best["yc"] += (yc - best["yc"]) / n
        best["h"] += (hh - best["h"]) / n
    rows.sort(key=lambda r: r["yc"])
    for r in rows:
        r["items"].sort(key=lambda it: it["x0"])
    return rows


def _line(items):
    return {"text": " ".join(it["t"] for it in items),
            "box": [min(it["box"][0] for it in items), min(it["box"][1] for it in items),
                    max(it["box"][2] for it in items), max(it["box"][3] for it in items)]}


def _gutter(rects, forced):
    """단 사이 여백의 x(보정 좌표). 없으면 None."""
    if len(rects) < 6:
        return None
    X0, X1 = min(r["x0"] for r in rects), max(r["x1"] for r in rects)
    span = X1 - X0
    if span <= 0:
        return None
    lo, hi = X0 + span * 0.3, X0 + span * 0.7
    step = max(span / 400, 1.0)
    bins = []
    x = lo
    while x <= hi:
        # 이 x를 가로지르는 낱말의 높이 합(작을수록 여백)
        bins.append((x, sum(r["y1"] - r["y0"] for r in rects if r["x0"] < x < r["x1"])))
        x += step
    if not bins:
        return None
    low = min(c for _, c in bins)
    best, run = None, []
    for xb, c in bins + [(None, None)]:
        if c is not None and c <= low:
            run.append(xb)
            continue
        if run and (best is None or len(run) > len(best)):
            best = run
        run = []
    gx = (best[0] + best[-1]) / 2 if best else (X0 + X1) / 2
    if forced:
        return gx
    # 자동: 양쪽에 글이 있고(한쪽은 지문, 한쪽은 짧은 답일 수 있어 적어도 됨), 여백 띠가 있고, 여백을 가로지르는 줄이 적을 때만 2단
    width = (best[-1] - best[0] + step) if best else 0
    left = sum(1 for r in rects if (r["x0"] + r["x1"]) / 2 < gx)
    right = len(rects) - left
    total_h = sum(r["y1"] - r["y0"] for r in rects)
    # 여백 폭: 지문이 표 칸 끝까지 차 있으면 아주 좁다(실제 샘플 약 10px/1430px) — 1단 글은 위 '가로지르는 높이'에서 걸러진다
    if width < span * 0.004 or min(left, right) < max(5, len(rects) * 0.05) or low > total_h * 0.12:
        return None
    return gx


def _side(r, gx):
    """낱말이 경계의 어느 쪽인지: 'L' / 'R' / 'S'(경계를 걸침)."""
    if r["x1"] <= gx:
        return "L"
    if r["x0"] >= gx:
        return "R"
    # 경계(가로지르는 글이 가장 적은 곳)를 걸친 낱말: 제목처럼 두 쪽에 이어진 줄로 보고 그 줄을 통째로 제자리에
    # (실제 샘플: 제목 '작은'이 경계를 살짝 걸쳐 반쪽만 오른쪽으로 가던 것)
    return "S"


SIDES = ("both", "right", "left")  # 읽을 단: 둘 다 / 오른쪽만 / 왼쪽만(한쪽이 지문일 때, 사용자 지정 2026-11-26)
_ID_LABEL = re.compile(r"(학번|이름|성명)\s*[:：(]?")


def arrange(page: dict, mode: str = "auto", side: str = "both") -> dict:
    """CLOVA 한 쪽(image_lines 결과 + words) → 배치한 lines와 layout 정보.
    mode='off'이거나 낱말 좌표가 없으면 CLOVA가 정한 줄(raw_lines)을 그대로 쓴다.
    side='right'/'left': 그 단의 줄만 남긴다(경계를 가로지르는 제목 줄은 남김). 빼는 단 맨 위의 학번·이름 줄도 남긴다."""
    side = side if side in SIDES else "both"
    if side != "both" and mode == "off":
        mode = "two"  # 한쪽만 읽으려면 나눠야 함
    raw = page.get("raw_lines") if page.get("raw_lines") is not None else page.get("lines") or []
    words = page.get("words") or []
    out = {**page, "raw_lines": raw}
    if page.get("fail") or not words:
        out["lines"], out["layout"] = raw, {"cols": 1, "deg": 0, "warn": False, "measured": 0}
        return out
    sk = skew(words)
    lay = {"cols": 1, "deg": sk["deg"], "warn": sk["warn"], "measured": sk["measured"]}
    if mode == "off":
        out["lines"], out["layout"] = raw, lay
        return out
    rects = _rects(words, page.get("w"), page.get("h"), sk["deg"])
    gx = _gutter(rects, mode == "two" or side != "both")
    if gx is None:
        out["lines"], out["layout"] = raw, lay
        return out
    sides = {r["i"]: _side(r, gx) for r in rects}
    rows = _rows(rects)
    keep = {"both": ("L", "R"), "right": ("R",), "left": ("L",)}[side]
    drop = {"right": "L", "left": "R"}.get(side)
    lines, sec = [], []
    id_left = [4]  # 빼는 단에서 학번·이름 줄을 살펴볼 남은 줄 수(맨 위 몇 줄만)

    def flush():
        if drop and id_left[0] > 0:
            part = [it for row in sec for it in row["items"] if sides[it["i"]] == drop]
            for r in _rows(part):
                if id_left[0] <= 0:
                    break
                id_left[0] -= 1
                ln = _line(r["items"])
                if _ID_LABEL.search(ln["text"]):
                    lines.append(ln)
        for s in keep:
            part = [it for row in sec for it in row["items"] if sides[it["i"]] == s]
            lines.extend(_line(r["items"]) for r in _rows(part))
        sec.clear()

    ys = [r["y0"] for r in rects] + [r["y1"] for r in rects]
    for row in rows:
        if any(sides[it["i"]] == "S" for it in row["items"]):  # 경계를 가로지르는 줄: 제자리에 한 줄로
            flush()
            lines.append(_line(row["items"]))
        else:
            sec.append(row)
    flush()
    cx, cy = (page.get("w") or 0) / 2, (page.get("h") or 0) / 2
    # 원본 보기에 그릴 단 경계선(원래 좌표, 위·아래 끝점)과 그림 위·아래 끝에서의 x(자르기·회색 덮기용)
    (ax, ay), (bx, by) = (_rot(gx, min(ys), cx, cy, -sk["deg"]), _rot(gx, max(ys), cx, cy, -sk["deg"]))
    h = page.get("h") or 0
    at = (lambda y: ax + (bx - ax) * (y - ay) / (by - ay)) if by != ay else (lambda y: ax)
    lay.update(cols=2, side=side, line=[round(ax, 1), round(ay, 1), round(bx, 1), round(by, 1)], cut=[round(at(0), 1), round(at(h), 1)])
    out["lines"], out["layout"] = lines, lay
    return out


def cut_frac(page) -> float:
    """Qwen에 한쪽 단만 보낼 때 자를 위치(그림 너비 비율). 경계를 못 찾았으면 가운데."""
    lay = (page or {}).get("layout") or {}
    w = (page or {}).get("w") or 0
    if lay.get("cut") and w:
        return max(0.2, min(0.8, (lay["cut"][0] + lay["cut"][1]) / 2 / w))
    return 0.5
