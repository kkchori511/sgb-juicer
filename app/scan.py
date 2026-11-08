"""스캔 PDF 처리: 페이지 묶기, 학번·이름 규칙 추출(AI 미사용), 인적사항 줄 지우기, 원본 페이지 그림."""
import base64
import io
import re

from .paths import data_dir

HEAD_LINES = 8  # 학번·이름은 보통 첫 몇 줄(머리글)에 있다
RE_NO_LABEL = re.compile(r"학[ \t]*번[ \t]*[:：.]?[ \t]*(\d(?:[ \t]*\d){3,5})(?!\d)")
RE_NAME_LABEL = re.compile(r"(?:이[ \t]*름|성[ \t]*명)[ \t]*[:：.]?[ \t]*([가-힣](?:[ \t]?[가-힣]){1,4})(?![가-힣])")
RE_GCN = re.compile(r"(\d)[ \t]*학년[ \t]*(\d{1,2})[ \t]*반[ \t]*(\d{1,2})[ \t]*번")
RE_NO = re.compile(r"(?<!\d)(\d{5})(?!\d)")
LABEL_WORDS = re.compile(r"(학\s*번|이\s*름|성\s*명|학년|반|번호|번)\s*[:：.]?")


def scan_dir():
    d = data_dir() / "스캔"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdf_path(batch_id):
    return scan_dir() / f"batch_{int(batch_id)}.pdf"


def default_groups(n_pages: int, per: int):
    per = max(1, int(per or 1))
    return [list(range(i, min(i + per, n_pages))) for i in range(0, n_pages, per)]


def groups_from_starts(n_pages: int, starts: list[int], skipped: list[int]):
    """starts: 새 학생이 시작되는 페이지 번호(0부터), skipped: 뺄 페이지."""
    skip = set(int(x) for x in skipped or [])
    starts = sorted(set(int(x) for x in starts or []) | {0})
    groups, cur = [], []
    for p in range(n_pages):
        if p in starts and cur:
            groups.append(cur)
            cur = []
        if p not in skip:
            cur.append(p)
    if cur:
        groups.append(cur)
    return [g for g in groups if g]


def extract_ids(text: str, members: list[dict]):
    """(학번, 이름) — 머리글 줄에서 라벨·패턴·명렬 이름으로 찾는다. 못 찾으면 빈 문자열."""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    head = "\n".join(lines[:HEAD_LINES])
    no = name = ""
    m = RE_GCN.search(head)
    if m:
        g, c, n = (int(x) for x in m.groups())
        no = f"{g}{c:02d}{n:02d}"
    m = RE_NO_LABEL.search(head)
    if m:
        no = re.sub(r"\s", "", m.group(1))
    if not no:
        m = RE_NO.search(head)
        if m:
            no = m.group(1)
    m = RE_NAME_LABEL.search(head)
    if m:
        name = re.sub(r"\s", "", m.group(1))
        names = {x["name"] for x in members}
        if name not in names:
            pre = sorted((n for n in names if n and name.startswith(n)), key=len, reverse=True)
            name = pre[0] if pre else re.sub(r"(학번|학년|번호|반|번)$", "", name)
    if not name:
        # 명렬에 있는 이름이 머리글에 나오면 그 이름(긴 이름 먼저)
        compact = re.sub(r"\s", "", head)
        for mem in sorted(members, key=lambda x: -len(x["name"])):
            if mem["name"] and mem["name"] in compact:
                name = mem["name"]
                break
    if not name and no:
        # 학번 바로 뒤의 한글 2~4자
        m = re.search(re.escape(no) + r"\s*([가-힣]{2,4})", head.replace(" ", " "))
        if m:
            name = m.group(1)
    return no, name


def strip_ids(text: str, no: str, name: str) -> str:
    """머리글 줄에서 학번·이름·라벨을 지우고, 남는 것이 없으면 줄째 뺀다(AI에는 내용만)."""
    out = []
    lines = (text or "").splitlines()
    seen = 0
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        seen += 1
        if seen <= HEAD_LINES:
            l2 = line
            if no:
                l2 = re.sub(r"[ \t]*".join(re.escape(ch) for ch in no), "", l2)
            if name:
                l2 = re.sub(r"[ \t]*".join(re.escape(ch) for ch in name), "", l2)
            l2 = RE_GCN.sub("", l2)
            if l2 != line or LABEL_WORDS.search(line):
                rest = LABEL_WORDS.sub("", l2)
                if not re.sub(r"[\s:：.,()\[\]\-_/|·]", "", rest):
                    continue  # 인적사항만 있던 줄
                l2 = re.sub(r"(학\s*번|이\s*름|성\s*명)\s*[:：.]?", "", l2).strip()
            out.append(l2)
        else:
            out.append(line)
    return "\n".join(out).strip()


def _png(width, height, channels, stride, buf: bytes) -> bytes:
    """Pillow 없이 PNG 만들기(RGB/RGBA)."""
    import struct
    import zlib

    color = {3: 2, 4: 6}[channels]
    raw = bytearray()
    row = width * channels
    for y in range(height):
        raw.append(0)
        raw += buf[y * stride : y * stride + row]

    def chunk(t, data):
        c = struct.pack(">I", len(data)) + t + data
        return c + struct.pack(">I", zlib.crc32(t + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def render_page(batch_id, page: int, width: int = 900) -> str:
    """원본 보기: 페이지를 PNG(data URL)로. 이 PC 안에서만 쓴다."""
    import pypdfium2 as pdfium

    path = pdf_path(batch_id)
    if not path.exists():
        raise FileNotFoundError("원본 PDF가 없습니다.")
    pdf = pdfium.PdfDocument(str(path))
    try:
        p = pdf[int(page)]
        bm = p.render(scale=width / p.get_width(), rev_byteorder=True)
        png = _png(bm.width, bm.height, bm.n_channels, bm.stride, bytes(bm.buffer))
        return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
    finally:
        pdf.close()


def page_count(path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)
