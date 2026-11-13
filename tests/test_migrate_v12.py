"""v11 시험 파일(더미 자료)을 v12로 열기: 형식변경전 백업, 자료 그대로, 태그 변환 표·내용 버전 생김."""
import os, shutil, sqlite3, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import backup, db
from app.paths import backup_dir

TABLES = ("students", "memberships", "groups", "tags", "records", "record_tags", "results", "finals", "inbox_batches", "standards")


def snap(path):
    con = sqlite3.connect(path)
    try:
        out = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        out["rec"] = con.execute("SELECT id, content, original, tags_ver FROM records ORDER BY id").fetchall()
        out["res"] = con.execute("SELECT id, record_id, text, meta FROM results ORDER BY id").fetchall()
        out["fin"] = con.execute("SELECT group_id, item, student_no, text, source, meta, stale, closed FROM finals ORDER BY group_id, item, student_no").fetchall()
        out["tags"] = con.execute("SELECT record_id, tag_id FROM record_tags ORDER BY record_id, tag_id").fetchall()
        out["ib"] = con.execute("SELECT id, title, group_id, item, meta FROM inbox_batches ORDER BY id").fetchall()
        out["std"] = con.execute("SELECT * FROM standards").fetchall()
        out["mem"] = con.execute("SELECT group_id, student_no, active, section FROM memberships ORDER BY group_id, student_no").fetchall()
        return out
    finally:
        con.close()


def test_v11_to_v12():
    dst = db.year_path(2026)
    shutil.copy(os.path.join(ROOT, "tests", "fixtures", "v11_sample.sqlite"), dst)
    assert db.file_schema_version(dst) == 11
    before = snap(dst)
    assert before["records"] == 4 and before["results"] == 2 and before["finals"] == 1
    d = db.open_year(2026)
    olds = [p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]
    assert len(olds) == 1 and (olds[0] / backup.DONE).exists()
    assert db.file_schema_version(olds[0] / "2026학년도.sqlite") == 11
    assert d.get_meta("schema_version") == "12"
    d.checkpoint()
    after = snap(dst)
    assert after == before, "자료가 바뀜"
    for t in ("tag_works", "tag_cands", "tag_runs", "tag_applies"):
        assert d.q(f"SELECT COUNT(*) n FROM {t}")[0]["n"] == 0
    # 내용 버전: 내용·소속이 바뀔 때만 오른다(태그·순서·날짜는 그대로)
    rid = d.q("SELECT id FROM records ORDER BY id LIMIT 1")[0]["id"]
    ver = lambda: d.q("SELECT content_ver v FROM records WHERE id=?", (rid,))[0]["v"]
    assert ver() == 0
    with d.tx() as c:
        c.execute("UPDATE records SET date='2026-04-01', pos=3, tags_ver=tags_ver+1 WHERE id=?", (rid,))
    assert ver() == 0
    with d.tx() as c:
        c.execute("UPDATE records SET content='바뀐 내용' WHERE id=?", (rid,))
    assert ver() == 1
    with d.tx() as c:
        c.execute("UPDATE records SET content='바뀐 내용' WHERE id=?", (rid,))  # 같은 글이면 그대로
    assert ver() == 1
    with d.tx() as c:
        c.execute("UPDATE records SET item='autonomy' WHERE id=?", (rid,))
    assert ver() == 2
    db.close_all()
    db.open_year(2026)  # 다시 열어도 백업을 또 만들지 않음
    assert len([p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]) == 1


if __name__ == "__main__":
    test_v11_to_v12()
    print("test_migrate_v12 OK")
