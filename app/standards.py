"""과목별 성취기준: 붙여넣기·텍스트 PDF·한글(hwpx)에서 글자 읽기, 저장, 프롬프트 규칙."""
import re
import zipfile
import xml.etree.ElementTree as ET

from .db import DbError, YearDb

LEVELS = {3: "ABC", 5: "ABCDE"}
LEVEL_HINT = {
    5: "A(매우 우수)·B(우수)·C(보통)·D(미흡)·E(매우 미흡)",
    3: "A(우수)·B(보통)·C(미흡)",
}


def read_pdf_text(path: str) -> str:
    """글자가 있는 PDF만(교육과정 문서). 스캔 이미지 PDF는 읽지 않는다."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(path)
        pages = [(p.extract_text() or "") for p in reader.pages]
    except Exception:
        raise DbError("PDF를 열지 못했습니다.")
    text = "\n\n".join(t.strip() for t in pages if t.strip())
    if len(re.sub(r"\s", "", text)) < 10:
        raise DbError("텍스트를 읽을 수 없는 PDF입니다. 붙여넣기나 hwpx를 이용해 주세요.")
    return _tidy(text)


def read_hwpx_text(path: str) -> str:
    """hwpx(zip 안의 Contents/section*.xml)에서 문단 글자를 순서대로 읽는다."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise DbError("hwpx 파일을 열지 못했습니다. 한글에서 '다른 이름으로 저장 > hwpx'로 저장한 파일인지 확인해 주세요.")
    with zf:
        names = sorted((n for n in zf.namelist() if re.match(r"Contents/section\d+\.xml$", n)),
                       key=lambda n: int(re.search(r"(\d+)", n.rsplit("/", 1)[1]).group(1)))
        if not names:
            raise DbError("hwpx 안에서 본문을 찾지 못했습니다.")
        paras = []
        for n in names:
            try:
                root = ET.fromstring(zf.read(n))
            except ET.ParseError:
                continue
            parent = {c: p for p in root.iter() for c in p}
            owned = {}  # 문단 → 그 문단에 직접 딸린 글자(표 셀 안 문단은 따로)
            order = [p for p in root.iter() if p.tag.endswith("}p")]
            for t in root.iter():
                if not t.tag.endswith("}t"):
                    continue
                a = parent.get(t)
                while a is not None and not a.tag.endswith("}p"):
                    a = parent.get(a)
                if a is not None:
                    owned.setdefault(a, []).append(t.text or "")
            for p in order:
                t = "".join(owned.get(p, []))
                if t.strip():
                    paras.append(t.strip())
    text = "\n".join(paras)
    if not text.strip():
        raise DbError("hwpx에서 글자를 찾지 못했습니다.")
    return _tidy(text)


def _tidy(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class Standards:
    def __init__(self, d: YearDb):
        self.d = d

    def _subject(self, gid):
        g = self.d.group(gid)
        if g["kind"] != "subject":
            raise DbError("성취기준은 과목에만 넣을 수 있습니다.")
        return g

    def get(self, gid):
        g = self._subject(gid)
        rows = self.d.q("SELECT * FROM standards WHERE group_id=?", (int(gid),))
        r = rows[0] if rows else {"group_id": int(gid), "text": "", "source": "", "updated_at": ""}
        levels = {}
        for m in self.d.members(gid):
            if m["active"]:
                levels[m["level"] or "-"] = levels.get(m["level"] or "-", 0) + 1
        return {**r, "level_scale": g["level_scale"], "levels": levels}

    def save(self, gid, text, source=None):
        self._subject(gid)
        with self.d.tx() as c:
            c.execute(
                """INSERT INTO standards(group_id, text, source, updated_at) VALUES(?,?,?,datetime('now','localtime'))
                   ON CONFLICT(group_id) DO UPDATE SET text=excluded.text,
                       source=COALESCE(?, standards.source), updated_at=excluded.updated_at""",
                (int(gid), text or "", source or "", source),
            )

    def overview(self):
        out = []
        for g in self.d.groups():
            if g["kind"] == "subject":
                r = self.d.q("SELECT text, updated_at FROM standards WHERE group_id=?", (g["id"],))
                out.append({"id": g["id"], "label": g["label"], "has": bool(r and (r[0]["text"] or "").strip()), "updated_at": r[0]["updated_at"] if r else ""})
        return out


OUTLINE_ITEMS = {"homeroom": ("autonomy", "career"), "club": ("club",)}


class Outlines:
    """자율·진로(담임반)·동아리 활동 개요. 학교에서 정한 활동을 한 줄에 하나씩 적어 두고, 기록 없는 학생 생성에 쓴다."""

    def __init__(self, d: YearDb):
        self.d = d

    def _check(self, gid, item):
        g = self.d.group(gid)
        if item not in OUTLINE_ITEMS.get(g["kind"], ()):
            raise DbError("활동 개요는 자율활동·진로활동(담임반)과 동아리에만 넣을 수 있습니다.")
        return g

    def get(self, gid, item):
        self._check(gid, item)
        rows = self.d.q("SELECT * FROM outlines WHERE group_id=? AND item=?", (int(gid), item))
        return rows[0] if rows else {"group_id": int(gid), "item": item, "text": "", "source": "", "updated_at": ""}

    def save(self, gid, item, text, source=None):
        self._check(gid, item)
        with self.d.tx() as c:
            c.execute(
                """INSERT INTO outlines(group_id, item, text, source, updated_at) VALUES(?,?,?,?,datetime('now','localtime'))
                   ON CONFLICT(group_id, item) DO UPDATE SET text=excluded.text,
                       source=COALESCE(?, outlines.source), updated_at=excluded.updated_at""",
                (int(gid), item, text or "", source or "", source),
            )

    def overview(self):
        out = []
        for g in self.d.groups():
            for item in OUTLINE_ITEMS.get(g["kind"], ()):
                r = self.d.q("SELECT text, updated_at FROM outlines WHERE group_id=? AND item=?", (g["id"], item))
                out.append({"id": g["id"], "item": item, "label": g["label"], "has": bool(r and (r[0]["text"] or "").strip()), "updated_at": r[0]["updated_at"] if r else ""})
        return out


def outline_lines(text: str) -> list[str]:
    """활동 개요 → 활동 목록(빈 줄 빼고 한 줄에 하나)."""
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def outline_rule(lines: list[str]) -> str:
    """시스템 프롬프트에 붙일 활동 개요 규칙(코드 고정). lines: 이 학생이 참여한 활동."""
    body = "\n".join(f"- {ln}" for ln in lines)
    return ("\n\n[활동 개요 — 반드시 참고]\n<활동개요>\n" + body + "\n</활동개요>\n"
            "- 이 학생은 학생관찰기록이 없다. 위 활동 개요에 적힌 활동에 참여한 것으로 보고 문장을 만든다.\n"
            "- 개요에 없는 활동, 구체적인 사건·수치·역할·결과를 지어내지 않는다. 활동의 목적과 내용에서 자연스럽게 드러나는 배움과 태도를 중심으로 쓴다.\n")


def avoid_rule(texts: list[str]) -> str:
    """같은 기준 자료로 다른 학생에게 이미 만든 문장: 이것과 겹치지 않게(코드 고정, 학번·이름 없음)."""
    texts = [t.strip()[:1500] for t in texts if (t or "").strip()]
    if not texts:
        return ""
    body = "\n".join(f"<다른학생{i + 1}>\n{t}\n</다른학생{i + 1}>" for i, t in enumerate(texts))
    return ("\n\n[다른 학생 문장 — 겹치지 말 것]\n" + body + "\n"
            "- 위 문장들은 같은 기준 자료로 다른 학생에게 쓴 것이다. 표현·문장 구성·전개 순서를 50% 이상 다르게 쓴다.\n"
            "- 위 문장의 문구를 그대로 가져오지 않는다. 같은 활동이라도 다른 측면(과정·태도·배움)을 골라 쓴다.\n")


def similarity(a: str, b: str) -> float:
    """두 문장이 얼마나 겹치는지(0~1). 공백 뺀 글자 3개 묶음의 겹침 비율(Dice)."""
    def grams(t):
        t = re.sub(r"\s+", "", t or "")
        return {t[i:i + 3] for i in range(len(t) - 2)}
    ga, gb = grams(a), grams(b)
    if not ga or not gb:
        return 0.0
    return 2 * len(ga & gb) / (len(ga) + len(gb))


def check_level(level: str, scale: int) -> str:
    level = (level or "").strip().upper()
    if level and level not in LEVELS.get(scale or 5, "ABCDE"):
        raise DbError(f"성취수준은 {scale}단계({'·'.join(LEVELS.get(scale or 5, 'ABCDE'))}) 중에서 골라 주세요.")
    return level


def standards_rule(text: str, level: str, scale: int, only: bool) -> str:
    """시스템 프롬프트에 붙일 성취기준 규칙(코드 고정)."""
    scale = scale or 5
    out = "\n\n[성취기준 — 반드시 참고]\n<성취기준>\n" + (text or "").strip() + "\n</성취기준>\n"
    if only:
        out += ("- 이 학생은 학생관찰기록이 없다. 위 성취기준을 조합해 이 학생의 세부능력 및 특기사항 문장을 만든다.\n"
                "- 구체적인 활동명·사건·수치를 지어내지 않고, 성취기준에 드러난 역량과 학습 내용을 바탕으로 쓴다.\n")
    else:
        out += "- 주어진 기록을 위 성취기준의 관점에서 해석해, 기록이 어떤 성취기준과 연결되는지 드러나게 쓴다.\n"
    if "(3단계: A·C·E)" in (text or ""):
        out += "- '(3단계: A·C·E)' 표시가 있는 성취기준은 A·C·E 수준 설명만 있다. 학생 수준이 B면 A 설명을, D면 C 설명을 기준으로 삼는다.\n"
    if level:
        out += (f"- 이 학생의 성취수준은 {scale}단계 중 {level}이다({LEVEL_HINT[scale]}).\n"
                "- 성취수준에 맞는 표현 수위로 쓴다. 높을수록 심화·적용·주도성을, 낮을수록 기본 개념 이해와 노력·성장 가능성을 중심으로 쓰며, 부정적 표현은 피한다.\n"
                "- 성취수준 기호(A~E)나 등급을 문장에 쓰지 않는다.\n")
    return out
