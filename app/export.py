"""항목별 내보내기: xlsx와 클립보드(셀 병합 없음, 한 행에 학생 한 명)."""
import platform
import subprocess

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

YELLOW = PatternFill("solid", fgColor="FFF2B3")
HEAD = PatternFill("solid", fgColor="E3ECFD")


def columns(scope: str):
    """scope: full(학년·반·번호·이름·상태·최종안·바이트) / text(최종안만)"""
    if scope == "text":
        return [("text", "최종안")]
    return [("grade", "학년"), ("class_no", "반"), ("number", "번호"), ("name", "이름"), ("state", "상태"), ("text", "최종안"), ("bytes", "바이트")]


def _value(row, key):
    if key == "state":
        return "마감" if row["closed"] else "미마감"
    v = row.get(key, "")
    return "" if v is None else v


def _sheet_name(t: str) -> str:
    t = (t or "생기부").replace("/", "-").replace("\\", "-").replace("?", "").replace("*", "").replace("[", "(").replace("]", ")").replace(":", "-")
    return t[:31] or "생기부"


def _fill(ws, rows: list[dict], cols):
    ws.append([label for _, label in cols])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = HEAD
    for r in rows:
        vals = [_value(r, k) for k, _ in cols]
        for v in vals:
            if isinstance(v, str) and len(v) > 32767:
                raise ValueError(f"{r['student_no']} 학생의 글이 엑셀 한 칸에 넣을 수 있는 길이(32,767자)를 넘습니다.")
        ws.append(vals)
        for c in ws[ws.max_row]:
            if isinstance(c.value, str):
                c.data_type = "s"  # '='로 시작해도 수식이 아니라 글자로
        if not r["closed"]:
            for c in ws[ws.max_row]:
                c.fill = YELLOW
    widths = {"grade": 6, "class_no": 6, "number": 6, "name": 10, "state": 8, "text": 90, "bytes": 8}
    for i, (k, _) in enumerate(cols, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = widths.get(k, 12)
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"


def class_label(r: dict) -> str:
    g, c = r.get("grade"), r.get("class_no")
    if not c:
        return "반 없음"
    return f"{g}학년 {c}반" if g else f"{c}반"


def split_by_class(rows: list[dict]) -> list[tuple[str, list[dict]]]:
    """반별로 나눔(학년·반 순). 반 안의 줄 순서는 그대로(학번순·이름순 정렬 유지)."""
    groups: dict = {}
    for r in rows:
        groups.setdefault((r.get("grade") or 0, r.get("class_no") or 0), []).append(r)
    return [(class_label(v[0]), v) for _, v in sorted(groups.items(), key=lambda kv: (kv[0][0] == 0 and kv[0][1] == 0, kv[0]))]


def write_xlsx(path: str, rows: list[dict], scope: str, sheet_title: str, split: bool = False):
    """split=True면 반별로 시트를 나눈다(시트 이름 'N학년 M반'). 학생이 없으면 빈 시트 하나."""
    cols = columns(scope)
    wb = Workbook()
    parts = split_by_class(rows) if split and rows else [(sheet_title, rows)]
    for k, (name, part) in enumerate(parts):
        ws = wb.active if k == 0 else wb.create_sheet()
        ws.title = _sheet_name(name)
        _fill(ws, part, cols)
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
