"""2단 나누기·기울기 보정(사용자 지정 2026-11-26): 가짜 CLOVA 낱말 좌표로 읽는 순서를 확인."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import ocr_layout as L  # noqa: E402

W, H = 1400, 1000


def word(t, x0, y0, x1, y1, deg=0.0):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if deg:
        r = math.radians(deg)
        c, s = math.cos(r), math.sin(r)
        pts = [(W / 2 + (x - W / 2) * c - (y - H / 2) * s, H / 2 + (x - W / 2) * s + (y - H / 2) * c) for x, y in pts]
    return [t] + [round(v, 1) for p in pts for v in p]


def line(prefix, n, x, y, deg=0.0, ww=90, gap=12):
    return [word(f"{prefix}{k}", x + k * (ww + gap), y, x + k * (ww + gap) + ww, y + 30, deg) for k in range(n)]


def page(deg=0.0, header_span=False, mid_span=False):
    ws = []
    if header_span:  # 단을 가로지르는 제목(한 낱말이 여백을 넓게 걸침)
        ws.append(word("공통제목입니다", 300, 40, 1100, 80, deg))
    y = 120
    for i in range(8):
        ws += line(f"L{i}_", 5, 60, y, deg)    # 왼쪽 단: x 60~560
        ws += line(f"R{i}_", 5, 760, y, deg)   # 오른쪽 단: x 760~1260
        y += 50
        if mid_span and i == 3:
            ws.append(word("가운데가로지름", 200, y, 1200, y + 30, deg))
            y += 50
    page = {"lines": [{"text": "섞인 원래 줄", "box": None}], "w": W, "h": H, "fail": "", "words": ws}
    return page


def texts(p):
    return [l["text"] for l in p["lines"]]


def test_two_columns():
    a = L.arrange(page(), "auto")
    t = texts(a)
    assert a["layout"]["cols"] == 2, a["layout"]
    assert t[0].startswith("L0_0") and t[7].startswith("L7_0") and t[8].startswith("R0_0") and t[-1].startswith("R7_0"), t
    assert all(" R" not in x for x in t[:8])  # 왼쪽 단 줄에 오른쪽 낱말이 섞이지 않음
    assert a["lines"][0]["box"][0] == 60  # 원래 좌표 상자(원본 줄 잘라 보기용)
    # 나누지 않음: CLOVA 줄 그대로
    assert texts(L.arrange(page(), "off")) == ["섞인 원래 줄"]


def test_header_and_middle_span():
    a = L.arrange(page(header_span=True, mid_span=True), "auto")
    t = texts(a)
    assert a["layout"]["cols"] == 2
    assert t[0] == "공통제목입니다", t
    i = t.index("가운데가로지름")
    # 제목 → (왼 0~3, 오 0~3) → 가로지름 → (왼 4~7, 오 4~7)
    assert [x[:2] for x in t[1:i]] == ["L0", "L1", "L2", "L3", "R0", "R1", "R2", "R3"], t
    assert [x[:2] for x in t[i + 1:]] == ["L4", "L5", "L6", "L7", "R4", "R5", "R6", "R7"], t


def test_skew_fix_and_warn():
    a = L.arrange(page(deg=4), "auto")
    assert abs(a["layout"]["deg"] - 4) < 0.3 and not a["layout"]["warn"], a["layout"]
    t = texts(a)
    assert [x[:2] for x in t] == [f"L{i}" for i in range(8)] + [f"R{i}" for i in range(8)], t
    assert all(len(x.split()) == 5 for x in t)  # 기울어도 한 줄이 한 줄로
    b = L.arrange(page(deg=14), "auto")
    assert b["layout"]["warn"] and b["layout"]["deg"] == 0, b["layout"]  # 너무 기울면 보정 안 하고 알림


def test_single_column_untouched():
    ws = []
    for i in range(10):
        ws.append(word(f"긴줄{i}", 60, 100 + i * 50, 1300, 130 + i * 50))
    p = {"lines": [{"text": "원래", "box": None}], "w": W, "h": H, "fail": "", "words": ws}
    a = L.arrange(p, "auto")
    assert a["layout"]["cols"] == 1 and texts(a) == ["원래"]
    # 2단으로 나누기를 골라도 가로지르는 줄만 있으면 그대로 줄 순서
    assert [x for x in texts(L.arrange(p, "two"))] == [f"긴줄{i}" for i in range(10)]


if __name__ == "__main__":
    test_two_columns()
    test_header_and_middle_span()
    test_skew_fix_and_warn()
    test_single_column_untouched()
    print("LAYOUT OK")
