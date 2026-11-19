"""v15 시험 파일(더미)을 v16으로 열기: 형식변경전 백업, 최종안에 그대로 쓴 기록(출처가 그 기록이고 글이 최종안에 그대로 있음)을 확정으로.
다른 글로 고친 최종안·출처가 기록이 아닌 최종안은 그대로. 글·마감·건수는 그대로."""
import json, os, shutil, sqlite3, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import backup, db
from app.paths import backup_dir

TABLES = ("students", "memberships", "groups", "tags", "records", "results", "finals")


def counts(path):
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        con.close()


def test_v15_to_v16():
    dst = db.year_path(2026)
    shutil.copy(os.path.join(ROOT, "tests", "fixtures", "v15_sample.sqlite"), dst)
    assert db.file_schema_version(dst) == 15
    before = counts(dst)
    d = db.open_year(2026)
    olds = [p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]
    assert len(olds) == 1 and (olds[0] / backup.DONE).exists()
    assert d.get_meta("schema_version") == str(db.SCHEMA_VERSION)
    d.checkpoint()
    assert counts(dst) == before
    conf = {r["student_no"]: r["confirmed"] for r in d.q("SELECT student_no, confirmed FROM records")}
    assert conf == {"20301": 1, "20302": 1, "20303": 1, "20304": 0, "20305": 0}, conf
    assert json.loads(d.get_meta("adopted_confirmed")) == [1, 2, 3]
    fin = {r["student_no"]: (r["text"], r["closed"], r["stale"]) for r in d.q("SELECT student_no, text, closed, stale FROM finals")}
    assert fin["20301"] == ("기존 완성문 하나", 1, 0) and fin["20303"] == ("앞 글. 기존 완성문 셋", 1, 0)  # 최종안·마감 그대로
    assert d.q("SELECT content FROM records WHERE id=4")[0]["content"] == "기존 완성문 넷"
    db.close_all()
    db.open_year(2026)  # 다시 열어도 그대로(백업 한 번)
    assert len([p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]) == 1


if __name__ == "__main__":
    test_v15_to_v16()
    print("test_migrate_v16 OK")
