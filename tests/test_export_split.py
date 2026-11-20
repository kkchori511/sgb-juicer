"""세특 내보내기 xlsx: 반별 시트 나누기(학년·반 순, 반 안 순서 유지) / 한 시트로 합치기."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openpyxl import load_workbook  # noqa: E402

from app import export  # noqa: E402


def row(g, c, n, name, closed=True):
    return {"student_no": f"{g}{c:02d}{n:02d}", "grade": g, "class_no": c, "number": n, "name": name, "closed": closed, "text": f"{name} 글", "bytes": 9}


def test_split():
    rows = [row(2, 3, 1, "다"), row(2, 1, 2, "나"), row(2, 1, 1, "가"), row(2, 3, 2, "라", False)]
    d = tempfile.mkdtemp()
    p = os.path.join(d, "a.xlsx")
    export.write_xlsx(p, rows, "full", "2026_세특", split=True)
    wb = load_workbook(p)
    assert wb.sheetnames == ["2학년 1반", "2학년 3반"]
    assert [r[3] for r in wb["2학년 1반"].iter_rows(min_row=2, values_only=True)] == ["나", "가"]  # 들어온 순서 그대로
    assert [r[3] for r in wb["2학년 3반"].iter_rows(min_row=2, values_only=True)] == ["다", "라"]
    assert wb["2학년 3반"]["A3"].fill.fgColor.rgb.endswith("FFF2B3")  # 미마감 노란색
    p2 = os.path.join(d, "b.xlsx")
    export.write_xlsx(p2, rows, "full", "2026_세특")
    wb = load_workbook(p2)
    assert wb.sheetnames == ["2026_세특"] and wb.active.max_row == 5
    p3 = os.path.join(d, "c.xlsx")
    export.write_xlsx(p3, [], "full", "빈것", split=True)
    assert load_workbook(p3).sheetnames == ["빈것"]


if __name__ == "__main__":
    test_split()
    print("EXPORT SPLIT OK")
