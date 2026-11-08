"""항목별 내보내기: xlsx와 클립보드(셀 병합 없음, 한 행에 학생 한 명)."""
import platform
import subprocess

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

YELLOW = PatternFill("solid", fgColor="FFF2B3")
HEAD = PatternFill("solid", fgColor="E3ECFD")


def columns(scope: str):
    """scope: full(학번·이름·상태·최종안) / text(최종안만)"""
    if scope == "text":
        return [("text", "최종안")]
    return [("student_no", "학번"), ("name", "이름"), ("state", "상태"), ("text", "최종안"), ("bytes", "바이트")]


def _value(row, key):
    if key == "state":
        return "마감" if row["closed"] else "미마감"
    return row.get(key, "")


def write_xlsx(path: str, rows: list[dict], scope: str, sheet_title: str):
    cols = columns(scope)
    wb = Workbook()
    ws = wb.active
    ws.title = (sheet_title or "생기부")[:31].replace("/", "-").replace("\\", "-").replace("?", "").replace("*", "").replace("[", "(").replace("]", ")").replace(":", "-")
    ws.append([label for _, label in cols])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEAD
    for r in rows:
        ws.append([_value(r, k) for k, _ in cols])
        if not r["closed"]:
            for c in ws[ws.max_row]:
                c.fill = YELLOW
    widths = {"student_no": 10, "name": 10, "state": 8, "text": 90, "bytes": 8}
    for i, (k, _) in enumerate(cols, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = widths.get(k, 12)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    wb.save(path)


def to_tsv(rows: list[dict], scope: str, header: bool) -> str:
    """엑셀에 붙여넣을 수 있는 탭 구분 글. 셀 안 줄바꿈은 따옴표로 감싼다."""
    cols = columns(scope)

    def cell(v):
        s = str(v if v is not None else "")
        if any(ch in s for ch in ('"', "\t", "\n", "\r")):
            return '"' + s.replace('"', '""') + '"'
        return s

    lines = []
    if header:
        lines.append("\t".join(label for _, label in cols))
    for r in rows:
        lines.append("\t".join(cell(_value(r, k)) for k, _ in cols))
    return "\r\n".join(lines)


def write_clipboard(text: str):
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)
        return
    if system != "Windows":
        raise OSError("이 운영체제에서는 클립보드 복사를 지원하지 않습니다.")
    import ctypes
    from ctypes import wintypes

    CF_UNICODETEXT = 13
    GMEM_MOVEABLE = 0x0002
    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    data = text.encode("utf-16-le") + b"\x00\x00"
    if not user32.OpenClipboard(None):
        raise OSError("클립보드를 열지 못했습니다.")
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
        ptr = kernel32.GlobalLock(h)
        ctypes.memmove(ptr, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            raise OSError("클립보드에 쓰지 못했습니다.")
    finally:
        user32.CloseClipboard()
