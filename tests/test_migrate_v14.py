"""v13 시험 파일(더미)을 v14로 열기: 형식변경전 백업, 기록당 태그 하나(태그 관리 순서상 앞 태그만 남김),
인박스 묶음 태그도 하나로, 뗀 목록은 meta에 남김. 다른 자료는 그대로."""
import json, os, shutil, sqlite3, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import backup, db
from app.paths import backup_dir

TABLES = ("students", "memberships", "groups", "tags", "records", "results", "finals", "tag_works", "tag_cands")


def counts(path):
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        con.close()


def test_v13_to_v14():
    dst = db.year_path(2026)
    shutil.copy(os.path.join(ROOT, "tests", "fixtures", "v13_sample.sqlite"), dst)
    assert db.file_schema_version(dst) == 13
    before = counts(dst)
    d = db.open_year(2026)
    olds = [p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]
    assert len(olds) == 1 and (olds[0] / backup.DONE).exists()
    assert d.get_meta("schema_version") == str(db.SCHEMA_VERSION)
    d.checkpoint()
    assert counts(dst) == before
    tags = d.q("SELECT record_id, tag_id FROM record_tags ORDER BY record_id")
    assert [(r["record_id"], r["tag_id"]) for r in tags] == [(1, 1), (2, 2), (4, 1)]  # 기록 1: 독서+발표 → 독서(앞)
    assert json.loads(d.q("SELECT tag_ids FROM inbox_batches WHERE id=1")[0]["tag_ids"]) == [1]
    log = json.loads(d.get_meta("tag_single_removed"))
    assert log["records"] == [{"record_id": 1, "tag_id": 2, "tag": "발표"}] and log["inbox_batches"][0]["before"] == [2, 1]
    assert d.q("SELECT confirmed FROM records WHERE id=3")[0]["confirmed"] == 1  # 확정은 그대로
    db.close_all()
    db.open_year(2026)  # 다시 열어도 그대로
    assert len([p for p in backup_dir().iterdir() if p.name.endswith("_형식변경전")]) == 1


if __name__ == "__main__":
    test_v13_to_v14()
    print("test_migrate_v14 OK")
