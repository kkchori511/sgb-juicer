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
    assert [x["name"] for x in cat["examples"]] == ["[수학] 방정식을 다시 세움."]  # 이름 없는 예시도 목록 이름이 보임
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



def test_codex_v033_fixes():
    """Codex 점검(v0.33.0) B1~B8 재발 막기."""
    import threading
    import time as _t
    from app import banned, prompts, trait_dict
    from app.paths import data_dir
    api = Api()
    d = api._db()
    # B1 같은 때 저장해도 ID가 겹치지 않고 하나만 지워짐
    real = _t.time
    _t.time = lambda: 1795158612.123
    try:
        a = examples.save({"item": "subject", "subject": "수학", "text": "같은 때 1."})
        b = examples.save({"item": "subject", "subject": "수학", "text": "같은 때 2."})
    finally:
        _t.time = real
    n0 = len(examples.load())
    examples.delete(b["id"])
    assert a["id"] != b["id"] and len(examples.load()) == n0 - 1
    # B2 60자 이름도 끝나고 60자를 넘지 않음
    done = []
    th = threading.Thread(target=lambda: done.append(share._new_name("가" * 60, {"가" * 60, "가" * 54 + " (가져옴)"})), daemon=True)
    th.start()
    th.join(2)
    assert done and len(done[0]) == 60 and done[0] not in {"가" * 60, "가" * 54 + " (가져옴)"}
    # B3 긴 태그 이름이 잘려 다른 태그를 덮지 않음
    long = "나" * 40
    ok(api.add_tag(long))
    pkg = {"format": "sgb-settings", "format_version": 1, "items": {"tags": [{"name": long + "다", "chain": {"src": "original", "steps": [{"prompt": "다른 지침"}]}}]}}
    assert share.preview(pkg, d)["tags"][0]["exists"] is False
    share.apply(pkg, {"tags": {"0": "overwrite"}}, d)
    assert d.q("SELECT 1 FROM tags WHERE name=?", (long + "다",)) and d.q("SELECT 1 FROM tags WHERE name=?", (long,))
    # B4 뒤 항목이 잘못되면 아무것도 넣지 않음
    p = os.path.join(DATA, "b4.sgbset")
    json.dump({"format": "sgb-settings", "format_version": 1, "items": {"prompts": [{"key": "x", "name": "넣으면안됨", "prompt": "p"}],
                                                                       "trait_dict": {"types": [], "areas": {}}}}, open(p, "w", encoding="utf-8"))
    ok(api.share_open(p))
    assert not api.share_import({"prompts": {"0": "new"}, "trait_dict": "replace"})["ok"]
    assert not any(x["name"] == "넣으면안됨" for x in prompts.build_library(config.load().get("prompt_lib"), None)[0])
    # B5 같은 때 두 번 백업해도 덮지 않음
    assert share.backup_config(data_dir()) != share.backup_config(data_dir())
    # B6 합치기: 겹치는 항목 안의 새 표기·새 설명도 들어옴
    banned.save([{"terms": ["원래말"], "repl": "대체", "except": []}])
    share.apply({"format": "sgb-settings", "items": {"banned": [{"terms": ["원래말", "추가표기"], "repl": "다른", "except": []}]}}, {"banned": "merge"})
    assert banned.load() == [{"terms": ["원래말", "추가표기"], "repl": "대체", "except": []}]
    t0 = trait_dict.load()["types"][0]["name"]
    share.apply({"format": "sgb-settings", "items": {"trait_dict": {"types": [{"name": t0, "descs": ["새 설명"]}], "areas": {}}}}, {"trait_dict": "merge"})
    assert "새 설명" in trait_dict.load()["types"][0]["descs"]
    # B8 이름 없는 예시: 보이는 이름으로 겹침을 알고, 덮어쓰기는 늘지 않음
    examples.save({"item": "subject", "subject": "과학", "text": "실험 결과를 정리함."})
    key = next(x["key"] for x in share.catalog()["examples"] if x["name"] == "[과학] 실험 결과를 정리함.")
    pkg = share.build({"examples": [key]})
    assert share.preview(pkg)["examples"][0]["exists"]
    n0 = len(examples.load())
    share.apply(pkg, {"examples": {"0": "overwrite"}})
    assert len(examples.load()) == n0


if __name__ == "__main__":
    test_all()
    test_codex_v033_fixes()
    print("SHARE FIXES OK")
