"""설정 꾸러미(v0.33): 고른 것만 담기, 개인 정보 점검, 비밀값·학생 자료 빼기, 가져오기(겹침 처리·합치기·태그 프롬프트)."""
import json
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, examples, share, vocab  # noqa: E402
from app.api import Api  # noqa: E402


def ok(r):
    assert r.get("ok"), r
    return r


def test_all():
    config.save({"openrouter_key": "sk-SECRET", "clova_secret": "CLOVA-SECRET", "models": ["m", "", "", ""], "setup_done": True})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    p = api.roster_from_text("20301\t김하나")
    ok(api.roster_apply(hr, api.roster_build(hr, p["raw"], p["header"], p["columns"])["rows"]))
    pid = ok(api.prompt_save({"name": "내 세특 지침", "prompt": "김하나 학생처럼 쓰지 말 것", "example": ""}))["id"]
    ok(api.prompt_save({"name": "깔끔 지침", "prompt": "짧게 쓴다", "example": ""}))
    ex = examples.save({"item": "subject", "subject": "수학", "text": "방정식을 다시 세움."})
    vocab.save({"on": True, "verbs": ["탐구하다"], "evals": ["돋보이다"]})
    ok(api.add_tag("독서"))
    d = api._db()
    tid = d.q("SELECT id FROM tags WHERE name='독서'")[0]["id"]
    from app.tagwork import TagWork
    w = TagWork(d).work_for_tag(tid)
    with d.tx() as c:
        c.execute("UPDATE tag_works SET confirmed=? WHERE id=?", (json.dumps({"chain": {"src": "original", "steps": [{"prompt": "독서 활동으로 정리", "example": "", "request": ""}]}}), w["id"]))

    cat = ok(api.share_catalog())["catalog"]
    keys = {x["name"]: x for x in cat["prompts"]}
    assert "내 세특 지침" in keys and keys["내 세특 지침"]["warn"] == ["김하나"]  # 명렬 이름 점검
    assert not any(x["builtin"] for x in cat["prompts"])  # 고치지 않은 기본 프롬프트는 없음
    assert [x["name"] for x in cat["tags"]] == ["독서"] and cat["vocab"]["available"] and not cat["banned"]["available"]

    pkg = share.build({"prompts": [keys["깔끔 지침"]["key"]], "examples": [ex["id"]], "tags": ["독서"], "vocab": True}, d)
    blob = json.dumps(pkg, ensure_ascii=False)
    assert "SECRET" not in blob and "20301" not in blob and "김하나" not in blob  # 비밀값·학생 자료 없음
    assert set(pkg["items"]) == {"prompts", "examples", "tags", "vocab"}
    import unicodedata
    nfd = unicodedata.normalize("NFD", "김쌤")
    assert share.build({"vocab": True}, d, nfd + "/:")["author"] == "김쌤"  # 완성형(NFC), 파일 이름에 못 쓰는 글자 뺌
    assert share.file_name(nfd) == f"김쌤의 꾸러미_{__import__('datetime').datetime.now():%y%m%d}.sgbset" and share.file_name(nfd) == unicodedata.normalize("NFC", share.file_name(nfd))
    path = os.path.join(DATA, "a.sgbset")
    json.dump(pkg, open(path, "w", encoding="utf-8"), ensure_ascii=False)

    # 받는 쪽처럼: 같은 이름 프롬프트가 있으면 새 이름으로, 어휘는 합치기, 태그는 새로 만든 태그에
    with d.tx() as c:
        c.execute("DELETE FROM tag_works")
        c.execute("DELETE FROM tags")
    vocab.save({"on": True, "verbs": ["비교하다"], "evals": []})
    pv = ok(api.share_open(path))["preview"]
    assert pv["prompts"][0]["exists"] and pv["tags"][0]["exists"] is False and pv["vocab"]["count"] == 2
    r = ok(api.share_import({"prompts": {"0": "new"}, "examples": {"0": "new"}, "tags": {"0": "overwrite"}, "vocab": "merge"}))
    assert r["done"] == {"prompts": 1, "examples": 1, "vocab": "merge", "tags": 1} and r["backup"]
    assert os.path.exists(os.path.join(DATA, "backups", r["backup"]))
    names = [x["name"] for x in ok(api.prompt_list())["prompts"]]
    assert "깔끔 지침" in names and "깔끔 지침 (가져옴)" in names
    assert vocab.load()["verbs"] == ["비교하다", "탐구하다"]
    tid = d.q("SELECT id FROM tags WHERE name='독서'")[0]["id"]
    assert TagWork(d).work_for_tag(tid)["confirmed"]["chain"]["steps"][0]["prompt"] == "독서 활동으로 정리"
    assert sum(1 for e in examples.load() if e["text"] == "방정식을 다시 세움.") == 2

    # 꾸러미가 아닌 파일, 아무것도 안 고름
    bad = os.path.join(DATA, "b.sgbset")
    open(bad, "w").write("{}")
    assert not api.share_open(bad)["ok"]
    ok(api.share_open(path))
    assert not api.share_import({"prompts": {"0": "skip"}, "vocab": "skip"})["ok"]


if __name__ == "__main__":
    test_all()
    print("SHARE OK")
