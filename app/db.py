"""학년도별 학생 자료(SQLite). 파일: 데이터 폴더/2026학년도.sqlite

v1: 역할·담당(학급/과목/동아리)·학생·소속(명렬)·일정.
v2: 태그·학생관찰기록·AI 결과 후보·최종안(마감). 기록 다루는 함수는 records.py.
v3: 자료 인박스(묶음·행·정제 후보). 다루는 함수는 inbox.py.
v4: 인박스 행에 원본 페이지 번호(pages) — 스캔 PDF 원본 보기용.
v5: 과목별 성취기준(standards).
v6: 기록 순서(records.pos). v7: 선택과목 수업(memberships.section). v8: 1·2학기 합산 과목(groups.pair_id·pair_total).
v9: 기록 태그 버전(records.tags_ver). v10: 자율·진로·동아리 활동 개요(outlines). v11: 인박스 행 열 역할(inbox_rows.ext).
v12: 태그 AI 변환(tag_works·tag_cands·tag_runs·tag_applies), 기록 내용 버전(records.content_ver, 트리거로 증가).
v13: 기록 확정(records.confirmed·confirmed_at). 확정본=content, 원문=original(없으면 content).

자료 형식 규칙: 표·열은 더하기만 한다(지우거나 이름을 바꾸지 않는다). 화면을 없애도 그 자료 표는 남긴다.
형식이 바뀌는 첫 실행 때는 열기 전에 '형식변경전' 백업을 만든다(backup.before_migration).
"""
import re
import sqlite3
import threading
from contextlib import contextmanager

from .paths import data_dir

SCHEMA_VERSION = 13
KINDS = ("homeroom", "subject", "club")
ROLES = ("homeroom", "subject")  # 담임 / 비담임

# 항목별 기본 목표 분량(바이트)
DEFAULT_TARGETS = {"autonomy": 1500, "career": 1500, "behavior": 900, "subject": 1500, "club": 1500}

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('homeroom','subject','club')),
    name TEXT NOT NULL,
    semester INTEGER,            -- 과목만: 1 또는 2
    grade INTEGER,               -- 학급: 학년
    class_no INTEGER,            -- 학급: 반
    level_scale INTEGER DEFAULT 5, -- 과목만: 성취수준 3 또는 5단계
    target_bytes INTEGER,        -- 과목·동아리 목표 분량(없으면 기본값)
    pair_id INTEGER,             -- 2학기 과목: 세특 바이트를 함께 쓰는 1학기 과목
    pair_total INTEGER,          -- 그 합산 목표(예: 1500)
    sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS students (
    student_no TEXT PRIMARY KEY, -- 학번(문자열, 앞자리 0 보존)
    name TEXT NOT NULL,
    grade INTEGER,
    class_no INTEGER,
    number INTEGER
);
CREATE TABLE IF NOT EXISTS memberships (
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    student_no TEXT NOT NULL REFERENCES students(student_no),
    active INTEGER NOT NULL DEFAULT 1,
    level TEXT DEFAULT '',
    section TEXT DEFAULT '',     -- 선택과목: 같은 수업(예: 물리학 A반). 비면 학년-반으로 묶음
    PRIMARY KEY (group_id, student_no)
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    item TEXT NOT NULL,              -- autonomy/career/behavior/subject/club
    student_no TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'record', -- record(학생관찰기록) / existing(이미 쓴 생기부)
    seq INTEGER,                     -- 회차
    date TEXT DEFAULT '',
    title TEXT DEFAULT '',           -- 활동명
    content TEXT NOT NULL DEFAULT '',
    original TEXT,                   -- AI 결과로 바꾸기 전 원문
    source TEXT DEFAULT 'manual',
    weight REAL,                     -- 종합 비중(%) 직접 지정값
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    pos INTEGER,                     -- 화면에서 끌어 바꾼 순서(없으면 기본 순서)
    tags_ver INTEGER DEFAULT 0,      -- 태그가 바뀔 때마다 1씩(v9)
    content_ver INTEGER DEFAULT 0,   -- 내용·소속이 바뀔 때마다 1씩(v12, 트리거)
    confirmed INTEGER DEFAULT 0,     -- 기록 확정(v13): 1이면 content가 확정본, 최종안 이어 붙이기 대상
    confirmed_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_records_slot ON records(group_id, item, student_no);
CREATE TABLE IF NOT EXISTS record_tags (
    record_id INTEGER NOT NULL REFERENCES records(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (record_id, tag_id)
);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    item TEXT NOT NULL,
    student_no TEXT NOT NULL,
    record_id INTEGER REFERENCES records(id) ON DELETE CASCADE, -- 있으면 기록 한 건의 후보, 없으면 학생×항목 후보
    op TEXT NOT NULL,                -- refine / polish / synth
    text TEXT NOT NULL,
    locked INTEGER NOT NULL DEFAULT 0,
    meta TEXT DEFAULT '{}',          -- 모델·지침·근거 기록·비율
    cost REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_results_slot ON results(group_id, item, student_no);
CREATE TABLE IF NOT EXISTS finals (
    group_id INTEGER NOT NULL,
    item TEXT NOT NULL,
    student_no TEXT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    source TEXT DEFAULT '',          -- 어디서 채택했는지
    meta TEXT DEFAULT '{}',
    stale INTEGER NOT NULL DEFAULT 0, -- 채택 후 기록이 바뀜
    closed INTEGER NOT NULL DEFAULT 0,
    closed_at TEXT,
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (group_id, item, student_no)
);
CREATE TABLE IF NOT EXISTS inbox_batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '',
    group_id INTEGER,                -- 대상 명렬(담당)
    item TEXT,                       -- 보낼 항목
    source TEXT DEFAULT 'paste',     -- paste / xlsx / scan
    structure TEXT DEFAULT 'multi',  -- multi(여러 학생) / single(한 학생 여러 회차) / shared(한 문서 → 여러 학생)
    stage TEXT NOT NULL DEFAULT 'import', -- import / match / refine / review / sent
    meta TEXT DEFAULT '{}',          -- 원본 표, 해석 설정
    date TEXT DEFAULT '',
    tag_ids TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    sent_at TEXT,
    sent_summary TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS inbox_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES inbox_batches(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL,
    source_ref TEXT DEFAULT '',      -- 원본 위치(예: 3행, C4셀, 1~2쪽)
    ext_no TEXT DEFAULT '',          -- 원본에서 읽은 학번
    ext_name TEXT DEFAULT '',        -- 원본에서 읽은 이름
    ext TEXT DEFAULT '{}',           -- 원본에서 읽은 학년·반·번호·반/번호·학적변동(JSON, v11)
    student_no TEXT,                 -- 연결한 학생
    state TEXT NOT NULL DEFAULT 'none', -- confirmed / suggested / none / excluded
    exclude_reason TEXT DEFAULT '',
    note TEXT DEFAULT '',            -- 매칭 안내(이름 다름, 동명이인 등)
    line INTEGER DEFAULT 0,          -- 원본에서 몇 번째 학생 줄인지
    pages TEXT DEFAULT '',           -- 스캔: 원본 페이지 번호(0부터, 쉼표)
    label TEXT DEFAULT '',           -- 회차·활동 제목
    date TEXT DEFAULT '',
    content TEXT NOT NULL DEFAULT '',  -- 원문(인적사항 뺀 내용)
    used_text TEXT                    -- 보낼 내용(정제 후보를 고르면 바뀜, 없으면 원문)
);
CREATE INDEX IF NOT EXISTS ix_inbox_rows ON inbox_rows(batch_id, ord);
CREATE TABLE IF NOT EXISTS inbox_cands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_id INTEGER NOT NULL REFERENCES inbox_rows(id) ON DELETE CASCADE,
    text TEXT NOT NULL,
    meta TEXT DEFAULT '{}',
    cost REAL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS standards (
    group_id INTEGER PRIMARY KEY REFERENCES groups(id) ON DELETE CASCADE,
    text TEXT NOT NULL DEFAULT '',   -- 성취기준·성취수준 설명(선생님이 고친 최종본)
    source TEXT DEFAULT '',          -- 마지막으로 가져온 곳(붙여넣기/파일 이름)
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS outlines (
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    item TEXT NOT NULL,              -- autonomy / career / club
    text TEXT NOT NULL DEFAULT '',   -- 활동 개요(한 줄에 활동 하나)
    source TEXT DEFAULT '',
    updated_at TEXT DEFAULT (datetime('now','localtime')),
    PRIMARY KEY (group_id, item)
);
CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,          -- YYYY-MM-DD
    title TEXT NOT NULL
);
-- v12: 태그 AI 변환. 기록이 지워져도 이력은 남긴다(record_id에 FK를 걸지 않음).
CREATE TABLE IF NOT EXISTS tag_works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tag_id INTEGER,                  -- 태그가 지워져도 작업 이력은 남김
    tag_name TEXT NOT NULL DEFAULT '', -- 만들 때 태그 이름
    draft TEXT DEFAULT '{}',         -- 고치는 중인 프롬프트 {prompt, example, lib_id, lib_name}
    confirmed TEXT DEFAULT '',       -- 확정한 설정 {cand_id, steps:[{prompt, example, request}], at}
    created_at TEXT DEFAULT (datetime('now','localtime')),
    updated_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE TABLE IF NOT EXISTS tag_cands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL,
    record_id INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'trial', -- trial(시험, 기록마다 3칸) / bulk(일괄 변환 결과)
    run_id INTEGER,                  -- bulk일 때 실행
    parent_id INTEGER,               -- [이 후보를 더 고치기]로 만든 경우 앞 후보
    steps TEXT DEFAULT '[]',         -- 원문에서 이 결과까지 거친 단계 [{prompt, example, request}]
    input_src TEXT DEFAULT 'original', -- original(처음 원문) / current(그때 기록 내용) / cand(앞 후보)
    input_text TEXT DEFAULT '',      -- 이 단계에 보낸 글
    record_ver INTEGER,              -- 만들 때 기록 내용 버전(반영 때 바뀌었는지 확인)
    record_text TEXT DEFAULT '',     -- 만들 때 기록 내용
    text TEXT NOT NULL DEFAULT '',   -- AI 결과
    edited TEXT,                     -- 검토하며 고친 글(없으면 text)
    checked INTEGER NOT NULL DEFAULT 0, -- 검토 표 체크
    locked INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok', -- ok / failed
    error TEXT DEFAULT '',
    model TEXT DEFAULT '',
    cost REAL DEFAULT 0,
    meta TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS ix_tag_cands_work ON tag_cands(work_id, record_id);
CREATE INDEX IF NOT EXISTS ix_tag_cands_run ON tag_cands(run_id);
CREATE TABLE IF NOT EXISTS tag_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL,
    steps TEXT DEFAULT '[]',         -- 이번 일괄에 쓴 확정 단계(그때 그대로)
    filter TEXT DEFAULT '{}',        -- 그때 화면 조건
    targets TEXT DEFAULT '[]',       -- 고정한 대상 기록 id
    status TEXT NOT NULL DEFAULT 'running', -- running / done / stopped
    created_at TEXT DEFAULT (datetime('now','localtime')),
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS tag_applies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL,
    batch TEXT NOT NULL,             -- 한 번 [반영]에 함께 바뀐 묶음(되돌리기 단위)
    record_id INTEGER NOT NULL,
    cand_id INTEGER,
    before_text TEXT NOT NULL,
    before_ver INTEGER,
    after_text TEXT NOT NULL,
    after_ver INTEGER,
    created_at TEXT DEFAULT (datetime('now','localtime')),
    undone_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_tag_applies_work ON tag_applies(work_id, batch);
CREATE INDEX IF NOT EXISTS ix_tag_applies_record ON tag_applies(record_id);
"""


class DbError(Exception):
    code = None


class ConflictError(DbError):
    """화면을 연 뒤 다른 곳에서 바뀌어 저장하지 않음(태그별 기록)."""
    code = "conflict"


class ClosedError(DbError):
    code = "closed"


def file_schema_version(path) -> int:
    """열지 않고(이전 형식 그대로) 파일의 자료 형식 번호를 읽는다. 읽지 못하면 0."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        finally:
            con.close()
        return _int(row[0]) or 0 if row else 0
    except sqlite3.Error:
        return 0


def year_path(year: int):
    return data_dir() / f"{int(year)}학년도.sqlite"


def list_years() -> list[int]:
    years = []
    for p in data_dir().glob("*학년도.sqlite"):
        m = re.match(r"^(\d{4})학년도\.sqlite$", p.name)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


class YearDb:
    """한 학년도 파일. 모든 접근은 lock으로 직렬화한다(pywebview는 여러 스레드에서 부른다)."""

    def __init__(self, year: int):
        self.year = int(year)
        self.path = year_path(self.year)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = FULL")
        self._conn.executescript(SCHEMA)
        self._migrate()
        if (_int(self.get_meta("schema_version")) or 0) < SCHEMA_VERSION:
            self.set_meta("schema_version", str(SCHEMA_VERSION))

    def _migrate(self):
        """이전 버전 파일에 빠진 열을 채운다(CREATE IF NOT EXISTS로는 열이 추가되지 않음)."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(inbox_rows)")}
        if "pages" not in cols:
            self._conn.execute("ALTER TABLE inbox_rows ADD COLUMN pages TEXT DEFAULT ''")
        if "ext" not in cols:  # v11: 인박스 열 역할(학년·반·번호·반/번호·학적변동)
            self._conn.execute("ALTER TABLE inbox_rows ADD COLUMN ext TEXT DEFAULT '{}'")
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(records)")}
        if "pos" not in cols:
            self._conn.execute("ALTER TABLE records ADD COLUMN pos INTEGER")
        if "tags_ver" not in cols:  # v9: 기록의 태그가 바뀔 때마다 1씩(일괄 태그 되돌리기 확인용)
            self._conn.execute("ALTER TABLE records ADD COLUMN tags_ver INTEGER DEFAULT 0")
        if "content_ver" not in cols:  # v12: 내용·소속이 바뀔 때마다 1씩(태그 변환 반영 때 그사이 바뀌었는지 확인)
            self._conn.execute("ALTER TABLE records ADD COLUMN content_ver INTEGER DEFAULT 0")
        if "confirmed" not in cols:  # v13: 기록 확정
            self._conn.execute("ALTER TABLE records ADD COLUMN confirmed INTEGER DEFAULT 0")
            self._conn.execute("ALTER TABLE records ADD COLUMN confirmed_at TEXT")
        self._conn.execute(
            "CREATE TRIGGER IF NOT EXISTS tr_records_content_ver AFTER UPDATE OF content, group_id, item, student_no ON records "
            "WHEN NEW.content IS NOT OLD.content OR NEW.group_id IS NOT OLD.group_id OR NEW.item IS NOT OLD.item OR NEW.student_no IS NOT OLD.student_no "
            "BEGIN UPDATE records SET content_ver=COALESCE(OLD.content_ver,0)+1 WHERE id=NEW.id; END")
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(groups)")}
        if "pair_id" not in cols:
            self._conn.execute("ALTER TABLE groups ADD COLUMN pair_id INTEGER")
            self._conn.execute("ALTER TABLE groups ADD COLUMN pair_total INTEGER")
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(memberships)")}
        if "section" not in cols:
            self._conn.execute("ALTER TABLE memberships ADD COLUMN section TEXT DEFAULT ''")

    def close(self):
        with self._lock:
            self._conn.close()

    @contextmanager
    def tx(self):
        """전부 성공하거나 전부 취소."""
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def q(self, sql, args=()):
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, args).fetchall()]

    def checkpoint(self):
        """수동 저장: 쓰기 기록(WAL)을 자료 파일에 반영한다."""
        with self._lock:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def backup_to(self, dest_path):
        with self._lock:
            dst = sqlite3.connect(dest_path)
            try:
                self._conn.backup(dst)
            finally:
                dst.close()

    # ---------- meta ----------
    def get_meta(self, key, default=None):
        rows = self.q("SELECT value FROM meta WHERE key=?", (key,))
        return rows[0]["value"] if rows else default

    def set_meta(self, key, value):
        with self.tx() as c:
            c.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))

    def role(self):
        return self.get_meta("role", "")

    def set_role(self, role):
        if role not in ROLES:
            raise DbError("역할 값이 올바르지 않습니다.")
        self.set_meta("role", role)

    # ---------- 담당 ----------
    def groups(self):
        rows = self.q(
            """SELECT g.*,
                      (SELECT COUNT(*) FROM memberships m WHERE m.group_id=g.id) AS total,
                      (SELECT COUNT(*) FROM memberships m WHERE m.group_id=g.id AND m.active=1) AS active
               FROM groups g ORDER BY CASE g.kind WHEN 'homeroom' THEN 0 WHEN 'subject' THEN 1 ELSE 2 END,
                                      g.semester, g.sort_order, g.id"""
        )
        for g in rows:
            g["label"] = group_label(g)
        # 2학기 과목: 이름 끝 숫자만 다른 1학기 과목을 합산 짝으로 추천(공통수학2 → 공통수학1)
        firsts = {_stem(g["name"]): g["id"] for g in rows if g["kind"] == "subject" and g["semester"] == 1 and _stem(g["name"]) != g["name"]}
        for g in rows:
            g["pair_suggest"] = None
            if g["kind"] == "subject" and g["semester"] == 2 and not g.get("pair_id") and _stem(g["name"]) != g["name"]:
                g["pair_suggest"] = firsts.get(_stem(g["name"]))
        return rows

    def group(self, gid):
        rows = [g for g in self.groups() if g["id"] == int(gid)]
        if not rows:
            raise DbError("담당을 찾지 못했습니다.")
        return rows[0]

    def add_group(self, kind, name="", semester=None, grade=None, class_no=None, level_scale=5):
        kind = str(kind)
        if kind not in KINDS:
            raise DbError("담당 종류가 올바르지 않습니다.")
        name = (name or "").strip()
        if kind == "homeroom":
            grade, class_no = _int(grade), _int(class_no)
            if not grade or not class_no:
                raise DbError("담임반의 학년과 반을 입력해 주세요.")
            if self.q("SELECT 1 FROM groups WHERE kind='homeroom'"):
                raise DbError("담임반은 하나만 등록할 수 있습니다.")
            name = f"{grade}학년 {class_no}반"
            semester = None
        elif kind == "subject":
            semester = _int(semester)
            if semester not in (1, 2):
                raise DbError("과목의 학기(1 또는 2)를 골라 주세요.")
            if not name:
                raise DbError("과목 이름을 입력해 주세요.")
            if self.q("SELECT 1 FROM groups WHERE kind='subject' AND name=?", (name,)):
                raise DbError(f"'{name}' 과목이 이미 있습니다. 학기마다 과목 이름이 달라야 합니다.")
            level_scale = 3 if _int(level_scale) == 3 else 5
        else:
            semester = None
            if not name:
                raise DbError("동아리 이름을 입력해 주세요.")
            if self.q("SELECT 1 FROM groups WHERE kind='club' AND name=?", (name,)):
                raise DbError(f"'{name}' 동아리가 이미 있습니다.")
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO groups(kind,name,semester,grade,class_no,level_scale) VALUES(?,?,?,?,?,?)",
                (kind, name, semester, _int(grade) if kind == "homeroom" else None,
                 _int(class_no) if kind == "homeroom" else None, level_scale if kind == "subject" else None),
            )
            return cur.lastrowid

    def update_group(self, gid, **fields):
        g = self.group(gid)
        allowed = {}
        if "name" in fields and g["kind"] != "homeroom":
            name = (fields["name"] or "").strip()
            if not name:
                raise DbError("이름을 입력해 주세요.")
            if self.q("SELECT 1 FROM groups WHERE kind=? AND name=? AND id<>?", (g["kind"], name, g["id"])):
                raise DbError(f"'{name}'이(가) 이미 있습니다.")
            allowed["name"] = name
        if "semester" in fields and g["kind"] == "subject":
            s = _int(fields["semester"])
            if s not in (1, 2):
                raise DbError("학기는 1 또는 2입니다.")
            allowed["semester"] = s
        if "level_scale" in fields and g["kind"] == "subject":
            allowed["level_scale"] = 3 if _int(fields["level_scale"]) == 3 else 5
        if "target_bytes" in fields and g["kind"] != "homeroom":
            t = _int(fields["target_bytes"])
            allowed["target_bytes"] = t if t and t > 0 else None
        if "pair_id" in fields and g["kind"] == "subject":
            pid = _int(fields["pair_id"])
            if not pid:
                allowed.update(pair_id=None, pair_total=None)
            else:
                p = self.group(pid)
                if p["id"] == g["id"] or p["kind"] != "subject":
                    raise DbError("합산할 과목을 다시 골라 주세요.")
                if g["semester"] != 2 or p["semester"] != 1:
                    raise DbError("합산은 2학기 과목에서 1학기 과목을 골라 연결합니다.")
                total = _int(fields.get("pair_total"))
                if not total or total <= 0:
                    raise DbError("합산 목표 바이트를 넣어 주세요(예: 1500).")
                allowed.update(pair_id=p["id"], pair_total=total)
        if g["kind"] == "homeroom" and ("grade" in fields or "class_no" in fields):
            gr = _int(fields.get("grade", g["grade"]))
            cl = _int(fields.get("class_no", g["class_no"]))
            if not gr or not cl:
                raise DbError("학년과 반을 입력해 주세요.")
            allowed.update(grade=gr, class_no=cl, name=f"{gr}학년 {cl}반")
        if not allowed:
            return 0
        sets = ", ".join(f"{k}=?" for k in allowed)
        unpaired = 0
        with self.tx() as c:
            c.execute(f"UPDATE groups SET {sets} WHERE id=?", (*allowed.values(), g["id"]))
            # 학기를 바꾸면 맞지 않게 된 합산 연결을 푼다(2학기 → 1학기 연결만 유효)
            if "semester" in allowed and allowed["semester"] != g["semester"]:
                if allowed["semester"] != 2 and g.get("pair_id"):
                    unpaired += c.execute("UPDATE groups SET pair_id=NULL, pair_total=NULL WHERE id=?", (g["id"],)).rowcount
                if allowed["semester"] != 1:
                    unpaired += c.execute("UPDATE groups SET pair_id=NULL, pair_total=NULL WHERE pair_id=?", (g["id"],)).rowcount
        return unpaired

    def group_impact(self, gid):
        g = self.group(gid)
        one = lambda sql: self.q(sql, (int(gid),))[0]["n"]
        return {
            "label": g["label"], "members": g["total"],
            "records": one("SELECT COUNT(*) n FROM records WHERE group_id=?"),
            "finals": one("SELECT COUNT(*) n FROM finals WHERE group_id=? AND text<>''"),
            "closed": one("SELECT COUNT(*) n FROM finals WHERE group_id=? AND closed=1"),
            "results": one("SELECT COUNT(*) n FROM results WHERE group_id=?"),
            "batches": one("SELECT COUNT(*) n FROM inbox_batches WHERE group_id=?"),
            "standards": one("SELECT COUNT(*) n FROM standards WHERE group_id=? AND text<>''"),
            "outlines": one("SELECT COUNT(*) n FROM outlines WHERE group_id=? AND text<>''"),
        }

    def delete_group(self, gid):
        with self.tx() as c:
            c.execute("DELETE FROM inbox_batches WHERE group_id=?", (int(gid),))
            c.execute("DELETE FROM memberships WHERE group_id=?", (int(gid),))
            c.execute("DELETE FROM results WHERE group_id=?", (int(gid),))
            c.execute("DELETE FROM finals WHERE group_id=?", (int(gid),))
            c.execute("DELETE FROM records WHERE group_id=?", (int(gid),))
            c.execute("DELETE FROM standards WHERE group_id=?", (int(gid),))
            c.execute("DELETE FROM outlines WHERE group_id=?", (int(gid),))
            c.execute("DELETE FROM groups WHERE id=?", (int(gid),))
            c.execute("UPDATE groups SET pair_id=NULL, pair_total=NULL WHERE pair_id=?", (int(gid),))
            c.execute("DELETE FROM students WHERE student_no NOT IN (SELECT student_no FROM memberships)")

    # ---------- 명렬 ----------
    def members(self, gid):
        return self.q(
            """SELECT s.student_no, s.name, s.grade, s.class_no, s.number, m.active, m.level, COALESCE(m.section,'') AS section
               FROM memberships m JOIN students s USING(student_no)
               WHERE m.group_id=? ORDER BY s.student_no""",
            (int(gid),),
        )

    def set_section(self, gid, student_nos, section):
        """선택과목 수업 지정(비우면 학년-반으로 묶음)."""
        nos = [str(n) for n in student_nos or []]
        if not nos:
            return 0
        marks = ",".join("?" * len(nos))
        with self.tx() as c:
            return c.execute(f"UPDATE memberships SET section=? WHERE group_id=? AND student_no IN ({marks})",
                             ((section or "").strip()[:40], int(gid), *nos)).rowcount

    def known_names(self, student_nos):
        if not student_nos:
            return {}
        marks = ",".join("?" * len(student_nos))
        return {r["student_no"]: r["name"] for r in self.q(f"SELECT student_no,name FROM students WHERE student_no IN ({marks})", tuple(student_nos))}

    def apply_roster(self, gid, rows, replace=True):
        """rows: [{student_no, name, grade, class_no, number, level}] — 검사를 통과한 행.
        replace=True: 새 명렬에 없는 기존 학생은 기록이 있으면 비활성화하고, 없으면 소속에서 뺀다.
        replace=False(추가): 기존 학생은 그대로 두고 새 학생만 더하거나 정보를 고친다."""
        g = self.group(gid)
        nos = [r["student_no"] for r in rows]
        if len(set(nos)) != len(nos):
            raise DbError("학번이 중복된 행이 있습니다.")
        with self.tx() as c:
            for r in rows:
                c.execute(
                    """INSERT INTO students(student_no,name,grade,class_no,number) VALUES(?,?,?,?,?)
                       ON CONFLICT(student_no) DO UPDATE SET name=excluded.name, grade=excluded.grade,
                           class_no=excluded.class_no, number=excluded.number""",
                    (r["student_no"], r["name"], _int(r.get("grade")), _int(r.get("class_no")), _int(r.get("number"))),
                )
                c.execute(
                    """INSERT INTO memberships(group_id,student_no,active,level,section) VALUES(?,?,1,?,?)
                       ON CONFLICT(group_id,student_no) DO UPDATE SET
                           level=CASE WHEN excluded.level<>'' THEN excluded.level ELSE memberships.level END,
                           section=CASE WHEN excluded.section<>'' THEN excluded.section ELSE memberships.section END""",
                    (g["id"], r["student_no"], (r.get("level") or "").strip().upper(), (r.get("section") or "").strip()[:40]),
                )
            if not replace:
                return {"count": len(rows), "removed": 0, "deactivated": 0}
            # 새 명렬에 없는 학생: 기록이 있으면 비활성화(자료 보존), 없으면 소속에서 뺀다.
            existing = [r["student_no"] for r in c.execute("SELECT student_no FROM memberships WHERE group_id=?", (g["id"],))]
            missing = [n for n in existing if n not in set(nos)]
            removed = deactivated = 0
            for n in missing:
                has = c.execute(
                    """SELECT 1 FROM records WHERE group_id=? AND student_no=?
                       UNION SELECT 1 FROM finals WHERE group_id=? AND student_no=?
                       UNION SELECT 1 FROM results WHERE group_id=? AND student_no=?
                       UNION SELECT 1 FROM inbox_rows r JOIN inbox_batches b ON b.id=r.batch_id
                             WHERE b.group_id=? AND r.student_no=? AND b.stage<>'sent' LIMIT 1""",
                    (g["id"], n, g["id"], n, g["id"], n, g["id"], n),
                ).fetchone()
                if has:
                    deactivated += c.execute("UPDATE memberships SET active=0 WHERE group_id=? AND student_no=?", (g["id"], n)).rowcount
                else:
                    removed += c.execute("DELETE FROM memberships WHERE group_id=? AND student_no=?", (g["id"], n)).rowcount
            c.execute("DELETE FROM students WHERE student_no NOT IN (SELECT student_no FROM memberships)")
        return {"count": len(rows), "removed": removed, "deactivated": deactivated}

    def set_active(self, gid, student_nos, active, all_groups=False):
        """소속별 비활성화. all_groups=True면 그 학생의 모든 소속(전출)."""
        nos = [str(n) for n in student_nos or []]
        if not nos:
            return 0
        marks = ",".join("?" * len(nos))
        with self.tx() as c:
            if all_groups:
                cur = c.execute(f"UPDATE memberships SET active=? WHERE student_no IN ({marks})", (1 if active else 0, *nos))
            else:
                cur = c.execute(
                    f"UPDATE memberships SET active=? WHERE group_id=? AND student_no IN ({marks})",
                    (1 if active else 0, int(gid), *nos),
                )
            return cur.rowcount

    def _member_scope(self, c, gid, nos, all_groups):
        if all_groups:
            marks = ",".join("?" * len(nos))
            return [(r[0], r[1]) for r in c.execute(f"SELECT group_id, student_no FROM memberships WHERE student_no IN ({marks})", nos)]
        return [(int(gid), n) for n in nos]

    def member_impact(self, gid, student_nos, all_groups=False):
        """학생을 지울 때 함께 지워지는 자료 수."""
        nos = [str(n) for n in student_nos or []]
        out = {"records": 0, "finals": 0, "results": 0, "inbox": 0}
        with self._lock:
            c = self._conn
            for g, n in self._member_scope(c, gid, nos, all_groups):
                out["records"] += c.execute("SELECT COUNT(*) FROM records WHERE group_id=? AND student_no=?", (g, n)).fetchone()[0]
                out["finals"] += c.execute("SELECT COUNT(*) FROM finals WHERE group_id=? AND student_no=? AND text<>''", (g, n)).fetchone()[0]
                out["results"] += c.execute("SELECT COUNT(*) FROM results WHERE group_id=? AND student_no=?", (g, n)).fetchone()[0]
                out["inbox"] += c.execute("""SELECT COUNT(*) FROM inbox_rows r JOIN inbox_batches b ON b.id=r.batch_id
                                             WHERE b.group_id=? AND r.student_no=? AND b.stage<>'sent'""", (g, n)).fetchone()[0]
        return out

    def remove_members(self, gid, student_nos, all_groups=False):
        """학생을 소속에서 지운다(전출 삭제). 그 소속의 기록·후보·최종안도 지우고,
        보내지 않은 인박스 행은 학생 연결만 푼다. all_groups=True면 이 학년도의 모든 소속에서."""
        nos = [str(n) for n in student_nos or []]
        if not nos:
            return 0
        with self.tx() as c:
            scope = self._member_scope(c, gid, nos, all_groups)
            for g, n in scope:
                c.execute("DELETE FROM record_tags WHERE record_id IN (SELECT id FROM records WHERE group_id=? AND student_no=?)", (g, n))
                c.execute("DELETE FROM results WHERE group_id=? AND student_no=?", (g, n))
                c.execute("DELETE FROM records WHERE group_id=? AND student_no=?", (g, n))
                c.execute("DELETE FROM finals WHERE group_id=? AND student_no=?", (g, n))
                c.execute("""UPDATE inbox_rows SET student_no=NULL, state='none', note='학생이 명렬에서 삭제됨'
                             WHERE student_no=? AND batch_id IN (SELECT id FROM inbox_batches WHERE group_id=? AND stage<>'sent')""", (n, g))
                c.execute("DELETE FROM memberships WHERE group_id=? AND student_no=?", (g, n))
            c.execute("DELETE FROM students WHERE student_no NOT IN (SELECT student_no FROM memberships)")
            return len(scope)

    def set_level(self, gid, student_no, level):
        with self.tx() as c:
            c.execute("UPDATE memberships SET level=? WHERE group_id=? AND student_no=?", ((level or "").strip().upper(), int(gid), str(student_no)))

    def student_groups(self):
        """{student_no: [group_id, ...]} — 활성 소속만."""
        out = {}
        for r in self.q("SELECT student_no, group_id FROM memberships WHERE active=1"):
            out.setdefault(r["student_no"], []).append(r["group_id"])
        return out

    # ---------- 일정 ----------
    def schedules(self):
        return self.q("SELECT * FROM schedules ORDER BY date, id")

    def add_schedule(self, date, title):
        date, title = (date or "").strip(), (title or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise DbError("날짜를 골라 주세요.")
        if not title:
            raise DbError("일정 내용을 입력해 주세요.")
        with self.tx() as c:
            return c.execute("INSERT INTO schedules(date,title) VALUES(?,?)", (date, title)).lastrowid

    def update_schedule(self, sid, date, title):
        date, title = (date or "").strip(), (title or "").strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date) or not title:
            raise DbError("날짜와 내용을 확인해 주세요.")
        with self.tx() as c:
            c.execute("UPDATE schedules SET date=?, title=? WHERE id=?", (date, title, int(sid)))

    def delete_schedule(self, sid):
        with self.tx() as c:
            c.execute("DELETE FROM schedules WHERE id=?", (int(sid),))

    # ---------- 목표 분량 ----------
    def targets(self):
        out = dict(DEFAULT_TARGETS)
        for k in out:
            v = _int(self.get_meta(f"target_{k}"))
            if v and v > 0:
                out[k] = v
        return out

    def set_target(self, item, value):
        if item not in DEFAULT_TARGETS:
            raise DbError("항목이 올바르지 않습니다.")
        v = _int(value)
        if not v or v <= 0:
            raise DbError("목표 분량은 1 이상의 숫자입니다.")
        self.set_meta(f"target_{item}", v)


def group_label(g: dict) -> str:
    if g["kind"] == "homeroom":
        return f"담임 {g['grade']}-{g['class_no']}"
    if g["kind"] == "subject":
        return f"{g['name']}·{g['semester']}학기"
    return f"{g['name']}·연간"


def _stem(name):
    """과목 이름 끝의 학기 표시(1·2, Ⅰ·Ⅱ, I·II)를 뗀다."""
    return re.sub(r"\s*(?:[12]|Ⅰ|Ⅱ|II|I)\s*$", "", name or "")


def _int(v):
    try:
        if v is None or v == "":
            return None
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


_open = {}
_open_lock = threading.Lock()
_premig_done = False  # 이번 실행에서 형식변경전 백업을 이미 만들었는지


def open_year(year: int) -> YearDb:
    global _premig_done
    with _open_lock:
        db = _open.get(int(year))
        if db is None:
            path = year_path(year)
            if path.exists() and file_schema_version(path) < SCHEMA_VERSION:
                if not _premig_done:
                    from . import backup  # 순환 import 피함
                    try:
                        backup.before_migration()
                    except Exception as e:
                        raise DbError(f"자료 형식을 바꾸기 전 백업을 만들지 못해 열지 않았습니다: {e}") from e
                    _premig_done = True
            db = YearDb(year)
            _open[int(year)] = db
        return db


def close_all():
    with _open_lock:
        for db in _open.values():
            db.close()
        _open.clear()
