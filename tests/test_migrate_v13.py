"""v12 시험 파일(더미 자료)을 v13으로 열기: 형식변경전 백업, 자료 그대로, 기록 확정 칸 생김(모두 미확정).
예전에 결과로 바꿔 둔 기록은 미확정 + '이전 반영본' 결과로, 태그 변환 결과는 항목별 결과 묶음에 보인다."""
import os, shutil, sqlite3, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import backup, db
from app.paths import backup_dir
from app.records import Records

TABLES = ("students", "memberships", "groups", "tags", "records", "record_tags", "results", "finals", "tag_works", "tag_cands")


def snap(path):
    con = sqlite3.connect(path)
    try:
        out = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
        out["rec"] = con.execute("SELECT id, content, original, tags_ver, content_ver FROM records ORDER BY id").fetchall()
        out["res"] = con.execute("SELECT id, record_id, text FROM results ORDER BY id").fetchall()
        out["fin"] = con.execute("SELECT group_id, item, student_no, text, stale, closed FROM finals ORDER BY 1,2,3").fetchall()
        return out
    finally:
        con.close()


def test_v12_to_v13():
    dst = db.year_path(2026)
    shutil.copy(os.path.join(ROOT, "tests", "fixtures", "v12_sample.sqlite"), dst)
    assert db.file_schema_version(dst) == 12
    before = snap(dst)
    assert before["records"] == 4 and before["tag_cands"] == 1
    d = db.open_year(2026)
    olds = [p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]
    assert len(olds) == 1 and (olds[0] / backup.DONE).exists()
    assert d.get_meta("schema_version") == "13"
    d.checkpoint()
    assert snap(dst) == before, "자료가 바뀜"
    assert d.q("SELECT COUNT(*) n FROM records WHERE confirmed=1")[0]["n"] == 0
    rec = Records(d)
    r1 = rec.records(1, "career", "20301")[0]
    assert not r1["confirmed"] and any(x["src"] == "tag" and x["text"] == "더미 태그 시험 결과." for x in r1["bundle"])
    r2 = rec.records(1, "career", "20302")[0]
    assert not r2["confirmed"] and r2["orig"] == "발표를 준비함." and r2["bundle"][0]["label"] == "이전 반영본"
    db.close_all()


if __name__ == "__main__":
    test_v12_to_v13()
    print("test_migrate_v13 OK")
