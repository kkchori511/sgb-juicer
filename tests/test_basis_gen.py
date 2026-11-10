"""v0.17 기준 자료로 생성·자료 보존: 활동 개요, 다른 학생 문장 피하기, 비슷함 계산, 형식변경전 백업, 백업 보관, 업데이트 경고."""
import os, shutil, sqlite3, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import backup, config, db, openrouter, prompts, updater
from app.api import Api
from app.paths import backup_dir
from app.standards import outline_lines, similarity

SENT = []  # AI에 보낸 시스템 프롬프트


def fake_chat(key, model, system, user, privacy=False):
    SENT.append(system)
    return f"자치 활동에 참여하며 협력하는 태도를 보임 {len(SENT)}번째 문장임.", 0.0


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0

TABLES = ["groups", "students", "memberships", "tags", "records", "record_tags", "results", "finals", "inbox_batches", "inbox_rows", "standards", "schedules"]


def counts(path):
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        con.close()


def ok(r):
    assert r.get("ok"), r
    return r


def test_migration():
    """v9 파일을 새 버전으로 열면: 열기 전에 형식변경전 백업, 자료 건수 그대로, 형식 10, outlines 표 생김."""
    src = os.path.join(ROOT, "tests", "fixtures", "v9_sample.sqlite")
    dst = db.year_path(2026)
    shutil.copy(src, dst)
    before = counts(dst)
    assert db.file_schema_version(dst) == 9
    assert before["records"] > 0 and before["standards"] == 1
    d = db.open_year(2026)
    olds = [p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]
    assert len(olds) == 1, list(backup_dir().iterdir())
    copy = olds[0] / "2026학년도.sqlite"
    assert copy.exists() and (olds[0] / backup.DONE).exists()
    assert db.file_schema_version(copy) == 9  # 바꾸기 전 그대로
    assert counts(copy) == before
    assert d.get_meta("schema_version") == str(db.SCHEMA_VERSION) == "10"
    d._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    assert counts(dst) == before, (counts(dst), before)  # 자료 건수가 줄지 않음
    assert d.q("SELECT COUNT(*) n FROM outlines")[0]["n"] == 0
    # 다시 열어도(이미 새 형식) 백업을 또 만들지 않음
    db.close_all()
    db.open_year(2026)
    assert len([p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]) == 1


def test_prune():
    """하루 백업은 7개, 업데이트전·형식변경전은 따로 3개."""
    root = backup_dir()
    for p in root.iterdir():
        shutil.rmtree(p)
    for i in range(10):
        (root / f"2026-01-{i + 1:02d}_090000").mkdir()
        (root / f"2026-01-{i + 1:02d}_090001_업데이트전").mkdir()
    (root / "2026-01-01_090002_형식변경전").mkdir()
    backup.prune()
    names = sorted(p.name for p in root.iterdir())
    normal = [n for n in names if n.count("_") == 1]
    special = [n for n in names if n.count("_") >= 2]
    assert len(normal) == 7 and normal[0] == "2026-01-04_090000", normal
    assert len(special) == 3 and "2026-01-10_090001_업데이트전" in special, special  # 가장 최근 3개


def test_outline_gen():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "current_year": 2026})
    api = Api()
    hr = next(g for g in db.open_year(2026).groups() if g["kind"] == "homeroom")["id"]
    sub = next(g for g in db.open_year(2026).groups() if g["kind"] == "subject")["id"]
    # 활동 개요: 담임반 자율·진로, 동아리만
    ok(api.outline_save(hr, "autonomy", "3월 학급 자치회 — 규칙 정하기\n\n4월 과학의 날 — 포스터 제작\n", "붙여넣기", 2026))
    assert api.outline_get(hr, "autonomy")["text"].startswith("3월")
    assert not api.outline_save(sub, "autonomy", "x")["ok"]
    assert not api.outline_save(hr, "behavior", "x")["ok"]
    ov = ok(api.standards_overview())
    assert {(x["id"], x["item"]) for x in ov["outlines"] if x["has"]} == {(hr, "autonomy")}
    lines = outline_lines(api.outline_get(hr, "autonomy")["text"])
    assert lines == ["3월 학급 자치회 — 규칙 정하기", "4월 과학의 날 — 포스터 제작"]

    members = [m["student_no"] for m in db.open_year(2026).members(hr) if m["active"]]
    a, b, c = members[1], members[2], members[5]
    SENT.clear()
    r = ok(api.ai_standards_only(hr, "autonomy", a, {"lines": lines[:1]}))
    assert "규칙 정하기" in SENT[-1] and "과학의 날" not in SENT[-1]  # 고른 활동만 보냄
    assert "[다른 학생 문장" not in SENT[-1]  # 처음에는 피할 문장 없음
    assert a not in SENT[-1]  # 학번은 보내지 않음
    ok(api.ai_standards_only(hr, "autonomy", b, {"lines": lines}))
    assert "[다른 학생 문장 — 겹치지 말 것]" in SENT[-1] and "1번째 문장" in SENT[-1] and "50% 이상" in SENT[-1]
    assert not api.ai_standards_only(hr, "autonomy", c, {"lines": []})["ok"]  # 활동을 하나도 안 고름
    assert not api.ai_standards_only(hr, "behavior", c, {"lines": lines})["ok"]  # 행특은 안 됨
    res = db.open_year(2026).q("SELECT meta FROM results WHERE id=?", (r["id"],))[0]["meta"]
    assert '"outline_only"' in res
    sim = ok(api.basis_similarity(hr, "autonomy", None))["similar"]
    assert set(sim) == {a, b} and sim[a]["with"] == b and sim[a]["sim"] > 0.5  # 가짜 AI 문장은 거의 같음
    # 세특: 성취기준만으로(기존 동작) + 피할 문장
    m = [x["student_no"] for x in db.open_year(2026).members(sub) if x["active"]]
    std = {"text": "[10공수1-01-01] 다항식의 사칙연산을 할 수 있다.", "level": "B"}
    ok(api.ai_standards_only(sub, "subject", m[0], std))
    ok(api.ai_standards_only(sub, "subject", m[2], std))  # m[1]은 마감된 학생
    assert "[성취기준 — 반드시 참고]" in SENT[-1] and "[다른 학생 문장" in SENT[-1]
    # 다른 담당 문장은 피할 문장에 섞이지 않음
    assert "규칙 정하기" not in SENT[-1]
    # C05: 일반 종합 후보가 많아도 기준 자료 후보를 피할 문장으로 찾음
    d = db.open_year(2026)
    with d.tx() as cur:
        for k in range(45):
            cur.execute("INSERT INTO results(group_id,item,student_no,op,text,meta) VALUES(?,?,?,?,?,?)", (hr, "autonomy", "99999", "synth", f"일반 {k}", "{}"))
    assert len(api._basis_avoid(api._rec(), hr, "autonomy", c)) == 2
    # C06: 후보를 만든 학생은 '입력 중'(기록 없음 아님)
    bi = {x["student_no"]: x for x in ok(api.batch_info(hr, "autonomy"))["students"]}
    assert bi[a]["status"] == "progress" and bi[a]["results"] == 1 and bi[c]["status"] == "none", (bi[a], bi[c])
    # C08: 담당 삭제 영향에 활동 개요가 나오고, 지우면 함께 지워짐
    im = d.group_impact(hr)
    assert im["outlines"] == 1, im


def test_rules():
    assert "50% 이상 다르게" in prompts.DEFAULT_PROMPTS["subject"]["synth"]["prompt"]
    assert all("50% 이상" in prompts.DEFAULT_PROMPTS[i]["synth"]["prompt"] for i in prompts.ITEMS)
    assert similarity("가나다라마바사", "가나다라마바사") == 1.0 and similarity("가나다라", "하파타카") == 0.0


def test_update_warning():
    body = "## 바뀐 점\n- 새 기능\n\n## ⚠ 업데이트 전 꼭 읽기\n- '일괄 종합' 메뉴가 없어집니다.\n- 자료는 그대로입니다.\n\n## 그 밖\n- 버그 수정\n\n**Full Changelog**: x"
    assert updater.warning_of(body) == "- '일괄 종합' 메뉴가 없어집니다.\n- 자료는 그대로입니다."
    assert updater.warning_of("## 바뀐 점\n- 없음") == ""

    # 하위 제목(###)은 절 안에 포함, 같은 수준(##)에서 끝
    assert updater.warning_of("## ⚠ 업데이트 전 꼭 읽기\n### 메뉴\n- a\n## 다음\n- b") == "### 메뉴\n- a"

    class Res:
        def __init__(self, data, ok=True): self.data, self.ok = data, ok
        def json(self): return self.data
    pages = {1: [{"tag_name": "v9.0.3", "body": "## ⚠ 업데이트 전 꼭 읽기\n- 미래", "prerelease": True},
                 {"tag_name": "v9.0.2", "body": "## ⚠ 업데이트 전 꼭 읽기\n- B"}],
             2: [{"tag_name": "v9.0.1", "body": "## ⚠ 업데이트 전 꼭 읽기\n### 메뉴\n- A"},
                 {"tag_name": "v0.1.0", "body": "## ⚠ 업데이트 전 꼭 읽기\n- 옛것"}]}
    old_get = updater.requests.get
    try:
        updater.requests.get = lambda url, **k: Res(pages.get(int(url.rsplit("page=", 1)[1]), []))
        w, complete = updater.warnings_between("v9.0.2", "## ⚠ 업데이트 전 꼭 읽기\n- B", local="0.17.0")
        assert complete and w == "[v9.0.1]\n### 메뉴\n- A\n\n[v9.0.2]\n- B", w  # 둘째 쪽(건너뛴 버전)까지, 옛 버전·시험판 빼고
        # 목록을 못 읽으면 '확인 못 함' → 경고 없음과 구분해 입력을 받는다
        updater.requests.get = lambda url, **k: Res([], ok=False)
        w, complete = updater.warnings_between("v9.0.2", "", local="0.17.0")
        assert not complete and w == ""
        assert updater._warning_text("v9.0.2", "").startswith(updater.INCOMPLETE[:20])
    finally:
        updater.requests.get = old_get
    # 경고가 있는 업데이트는 '확인했어요'를 입력해야 진행
    api = Api()
    api._update_info = {"version": "9.0.2", "warning": "- B", "sha256": "0" * 64}
    r = api.update_apply("확인")
    assert not r["ok"] and "확인했어요" in r["error"], r


if __name__ == "__main__":
    test_migration()
    test_prune()
    test_outline_gen()
    test_rules()
    test_update_warning()
    print("test_basis_gen OK")
