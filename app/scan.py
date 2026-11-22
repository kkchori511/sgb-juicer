"""스캔 PDF 처리: 페이지 묶기, 학번·이름 규칙 추출(AI 미사용), 인적사항 줄 지우기, 원본 페이지 그림."""
import base64
import io
import re
import threading

from .paths import data_dir

# PDFium(pypdfium2)은 스레드 안전하지 않다(문서 객체가 달라도). 열기·그리기·닫기를 모두 이 잠금 안에서 한다.
PDFIUM_LOCK = threading.RLock()

HEAD_LINES = 8  # 학번·이름은 보통 첫 몇 줄(머리글)에 있다
RE_NO_LABEL = re.compile(r"학[ \t]*번[ \t]*[:：.]?[ \t]*(\d(?:[ \t]*\d){3,5})(?!\d)")
# 라벨은 낱말 전체만('이름을'·'성명서' 같은 본문 낱말은 라벨이 아님). 라벨 뒤에는 구분 기호나 빈칸이 있어야 한다.
_LBL = r"(?<![가-힣])(?:이[ \t]*름|성[ \t]*명)(?![가-힣])"
RE_NAME_LABEL = re.compile(_LBL + r"(?:[ \t]*[:：.][ \t]*|[ \t]+)([가-힣](?:[ \t]?[가-힣]){1,4})(?![가-힣])")
# '이름:'이 줄 끝에 있고 이름은 다음 줄에 따로 있는 모양(손글씨 칸을 OCR이 줄을 나눠 읽을 때)
RE_NAME_LABEL_EOL = re.compile(_LBL + r"[ \t]*[:：.][ \t]*$")  # 구분 기호 필수('10399 이름' 같은 줄과 구분)
RE_NAME_ONLY_LINE = re.compile(r"^[ \t]*([가-힣](?:[ \t]?[가-힣]){1,4})[ \t]*$")
# 이름으로 잡으면 안 되는 라벨 낱말(머리글 칸 이름) — 낱말 전체가 같을 때만('반유진'의 '반'은 성)
RE_NOT_NAME = re.compile(r"(?:이름|성명|학번|학년|번호|반|번|날짜|일자|과목|주제|학교|교과)")
RE_GCN = re.compile(r"(\d)[ \t]*학년[ \t]*(\d{1,2})[ \t]*반[ \t]*(\d{1,2})[ \t]*번")
RE_NO = re.compile(r"(?<!\d)(\d{5})(?!\d)")
# 머리글 라벨 낱말(낱말 전체만)
LABEL_WORDS = re.compile(r"(?<![가-힣])(?:학[ \t]*번|이[ \t]*름|성[ \t]*명|학[ \t]*년|번[ \t]*호|반|번)(?![가-힣])[ \t]*[:：.]?")
LABEL_KEY = r"(?<![가-힣])(?:학[ \t]*번|이[ \t]*름|성[ \t]*명)(?![가-힣])[ \t]*"


def scan_root():
    d = data_dir() / "스캔"
    d.mkdir(parents=True, exist_ok=True)
    return d


def scan_dir(year):
    """학년도별 스캔 원본 폴더(묶음 번호는 학년도마다 1부터라 섞이지 않게)."""
    d = scan_root() / str(int(year))
    d.mkdir(parents=True, exist_ok=True)
    return d


def pdf_path(year, batch_id):
    return scan_dir(year) / f"batch_{int(batch_id)}.pdf"


def migrate_flat(owner_of):
    """v0.4~0.7은 스캔/batch_N.pdf(학년도 구분 없음)에 두었다. 주인이 하나뿐이면 그 학년도로 옮기고,
    애매하면 스캔/_확인필요로 옮긴다. owner_of(n) -> 그 번호의 스캔 묶음을 가진 학년도 목록."""
    import shutil

    moved = []
    for f in list(scan_root().glob("batch_*.pdf")):
        m = re.match(r"batch_(\d+)\.pdf$", f.name)
        if not m:
            continue
        years = owner_of(int(m.group(1)))
        if len(years) == 1:
            dest = pdf_path(years[0], int(m.group(1)))
            if not dest.exists():
                shutil.move(str(f), str(dest))
                moved.append(f"{f.name} → {years[0]}")
                continue
        q = scan_root() / "_확인필요"
        q.mkdir(exist_ok=True)
        shutil.move(str(f), str(q / f.name))
        moved.append(f"{f.name} → _확인필요")
    return moved


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


def _lines(text):
    return [l for l in (text or "").splitlines() if l.strip()]


def _clean_name(v):
    v = re.sub(r"\s", "", v or "")
    v = re.sub(r"(학번|학년|번호)$", "", v)  # '홍길동학번'처럼 붙어 읽힌 다음 칸 라벨
    return "" if len(v) < 2 or RE_NOT_NAME.fullmatch(v) else v


def label_names(text: str, members: list[dict] | None = None) -> list[str]:
    """라벨('이름'·'성명')로 자리가 확실한 이름 값들(머리글 안). 반복 라벨도 모두 본다.
    '이름:'이 줄 끝이면 다음 줄 — 명렬 이름이거나 2~3글자 낱말 하나일 때만(빈 이름 칸 뒤 긴 제목을 이름으로 잡지 않게).
    명렬 밖 값도 지우기에는 쓴다(잘못 읽힌 이름이 AI로 가지 않게). 학생 매칭용 이름은 extract_ids가 명렬로 거른다."""
    lines = _lines(text)
    roster = {m["name"] for m in members or [] if m.get("name")}
    out = []
    for i, line in enumerate(lines[:HEAD_LINES]):
        for m in RE_NAME_LABEL.finditer(line):
            v = _clean_name(m.group(1))
            if v:
                out.append(v)
        if RE_NAME_LABEL_EOL.search(line) and i + 1 < len(lines):
            m = RE_NAME_ONLY_LINE.match(lines[i + 1])
            v = _clean_name(m.group(1)) if m else ""
            if v and (v in roster or len(v) <= 3):
                out.append(v)
    return list(dict.fromkeys(out))


def near_no_names(text: str, no: str, members: list[dict] | None) -> list[str]:
    """라벨 없이 '학번 이름'으로 쓴 머리글: 학번이 명렬에 있고, 학번 바로 뒤 낱말이 그 학생 이름과 거의 같으면
    (같은 길이, 한 글자까지 다름 — OCR이 잘못 읽은 이름) 지울 값으로 돌려준다. 본문 낱말은 이름과 달라 남는다."""
    want = next((m.get("name") or "" for m in members or [] if str(m.get("student_no") or "") == no), "") if no else ""
    if not want:
        return []
    head = "\n".join(_lines(text)[:HEAD_LINES])
    out = []
    for m in re.finditer(r"(?<!\d)" + re.escape(no) + r"[ \t]*([가-힣]{2,5})(?![가-힣])", head):
        v = m.group(1)
        if len(v) == len(want) and sum(a != b for a, b in zip(v, want)) <= 1:
            out.append(v)
    return out


def extract_ids(text: str, members: list[dict]):
    """(학번, 이름) — 머리글 줄에서 라벨·패턴·명렬 이름으로 찾는다. 못 찾으면 빈 문자열.
    명렬이 있으면 명렬에 있는 이름만 이름으로 인정한다(못 읽으면 매칭에서 직접 고름).
    라벨 없는 '학번 뒤 한글'은 이름으로 보지 않는다(본문 낱말을 이름으로 잡아 본문을 지우지 않게)."""
    lines = _lines(text)
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
    roster = sorted({x["name"] for x in members if x.get("name")}, key=len, reverse=True)
    for v in label_names(text, members):
        if not roster:
            name = v
            break
        if v in roster:
            name = v
            break
        pre = [n for n in roster if v.startswith(n)]  # '김철수학' 같은 붙어 읽힘
        if pre:
            name = pre[0]
            break
    if not name and roster:
        # 명렬에 있는 이름이 머리글에 낱말로 나오면 그 이름(긴 이름 먼저)
        for n in roster:
            if re.search(r"(?<![가-힣])" + r"[ \t]*".join(re.escape(ch) for ch in n) + r"(?![가-힣])", head):
                name = n
                break
    return no, name


def _sub_value(line, value, digits):
    if not value:
        return line
    body = r"[ \t]*".join(re.escape(ch) for ch in value)
    edge = (r"(?<!\d)", r"(?!\d)") if digits else (r"(?<![가-힣])", r"(?![가-힣])")
    return re.sub(edge[0] + body + edge[1], "", line)


def strip_ids(text: str, no: str, name: str, extra_names=()) -> str:
    """머리글 줄에서 학번·이름·라벨을 지우고, 남는 것이 없으면 줄째 뺀다(AI에는 내용만).
    지우는 것은 낱말 전체로 나온 값과 라벨뿐이다. 본문 중간에 쓴 이름은 남을 수 있다."""
    out = []
    lines = (text or "").splitlines()
    seen = 0
    names = [n for n in dict.fromkeys([name, *extra_names]) if n]
    for line in lines:
        if not line.strip():
            out.append(line)
            continue
        seen += 1
        if seen > HEAD_LINES + 1:  # +1: 8번째 줄 '이름:' 다음 줄 이름
            out.append(line)
            continue
        l2 = _sub_value(line, no, True)
        for n in names:
            l2 = _sub_value(l2, n, False)
        l2 = RE_GCN.sub("", l2)
        changed = l2 != line
        if changed or LABEL_WORDS.search(line):
            rest = LABEL_WORDS.sub("", l2)
            if not re.sub(r"[\s:：.,()\[\]\-_/|·]", "", rest):
                continue  # 인적사항만 있던 줄
            # 값을 지운 줄은 라벨도 지우고, 그대로인 줄은 구분 기호가 붙은 라벨('이름:')만 지운다
            l2 = re.sub(LABEL_KEY + (r"[:：.]?" if changed else r"[:：]"), "", l2).strip()
        out.append(l2)
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


def strip_pages(texts: list[str], no: str, name: str, members: list[dict]) -> str:
    """학생 한 명의 여러 페이지: 페이지마다 머리글의 학번·이름을 지운 뒤 합친다.
    (양면 학습지는 두 번째 페이지에도 학번·이름 칸이 있다.) 첫 페이지 값, 그 페이지에서 읽은 값,
    라벨 자리의 값(명렬에 없게 잘못 읽힌 이름 포함)을 모두 지운다."""
    out = []
    for t in texts:
        p_no, p_name = extract_ids(t, members)
        extra = [p_name, *label_names(t, members), *near_no_names(t, p_no or no, members)]
        c = strip_ids(t, no, name, extra)
        if p_no and p_no != no:
            c = strip_ids(c, p_no, "")
        out.append(c)
    return "\n\n".join(x for x in out if x.strip()).strip()


def render_page(year, batch_id, page: int, width: int = 900) -> str:
    """원본 보기: 페이지를 PNG(data URL)로. 이 PC 안에서만 쓴다."""
    import pypdfium2 as pdfium

    path = pdf_path(year, batch_id)
    if not path.exists():
        raise FileNotFoundError("원본 PDF가 없습니다.")
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            p = pdf[int(page)]
            bm = p.render(scale=width / p.get_width(), rev_byteorder=True)
            w, h, ch, stride, raw = bm.width, bm.height, bm.n_channels, bm.stride, bytes(bm.buffer)
            bm.close()
            p.close()
        finally:
            pdf.close()
    png = _png(w, h, ch, stride, raw)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def page_count(path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(path)).pages)


def render_crop(year, batch_id, page: int, box, w, h, clip=None, width: int = 1400, pad: float = 0.35) -> str:
    """차이 난 줄 확대: box([x0, y0, x1, y1], CLOVA 좌표 w×h 기준)에 위아래 여백을 두고 페이지 가로 전체를 잘라 PNG로.
    clip([윗줄 아래 끝, 아랫줄 위 끝], 없으면 None): 여백이 이웃 줄 글씨까지 들어가지 않게 자른다."""
    import pypdfium2 as pdfium

    path = pdf_path(year, batch_id)
    if not path.exists():
        raise FileNotFoundError("원본 PDF가 없습니다.")
    with PDFIUM_LOCK:
        pdf = pdfium.PdfDocument(str(path))
        try:
            p = pdf[int(page)]
            bm = p.render(scale=width / p.get_width(), rev_byteorder=True)
            bw, bh, ch, stride, raw = bm.width, bm.height, bm.n_channels, bm.stride, bytes(bm.buffer)
            bm.close()
            p.close()
        finally:
            pdf.close()
    sy = bh / float(h or bh)
    x0, y0, x1, y1 = (float(v) for v in box)
    line_h = max(10.0, (y1 - y0) * sy)
    top = max(0, int(y0 * sy - line_h * pad))
    bot = min(bh, int(y1 * sy + line_h * pad))
    c0, c1 = (list(clip) + [None, None])[:2] if clip else (None, None)
    if c0 is not None:
        top = max(top, min(int(y0 * sy), int(float(c0) * sy) + 2))
    if c1 is not None:
        bot = min(bot, max(int(y1 * sy) + 1, int(float(c1) * sy) - 2))
    if bot <= top:
        top, bot = 0, min(bh, 60)
    png = _png(bw, bot - top, ch, stride, raw[top * stride: bot * stride])
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")
