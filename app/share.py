"""설정 꾸러미(v0.33): 내 착즙기 설정 일부를 골라 파일(.sgbset)로 다른 선생님에게 건넨다.

- 담을 수 있는 것: 프롬프트(직접 만든 것·고친 기본), 예시(직접 만든 것·고친 기본), 세특 어휘, 기재 유의어, 행특 설계 사전,
  태그 프롬프트(지금 학년도에서 태그별 기록에 확정한 설정).
- 처음부터 담지 않는 것: API 키·CLOVA(스캔) 값·모델, 학년도 자료(명렬·학번·이름·기록·최종안), 일정, 분량 목표, 화면 설정.
- 담기 전 점검: 글 속에 명렬의 학생 이름이나 학번처럼 보이는 말이 있으면 알린다(내보내기 화면에서 확인).
- 가져오기: 미리보기에서 골라 넣는다. 이름이 겹치면 항목마다 건너뛰기 / 덮어쓰기 / 새 이름으로 추가.
  어휘·유의어·사전은 합치기 / 통째로 바꾸기. 넣기 전에 지금 설정 파일을 자료 폴더에 복사해 둔다.
"""
import copy
import datetime as dt
import json
import re
import shutil

from . import VERSION, banned, config, examples, prompts, trait_dict, vocab
from .db import DbError

FORMAT = "sgb-settings"
FORMAT_VER = 1
MAX_FILE = 5 * 1024 * 1024
SECTIONS = ("prompts", "examples", "vocab", "banned", "trait_dict", "tags")
SECTION_NAMES = {"prompts": "프롬프트", "examples": "예시 목록", "vocab": "세특 어휘", "banned": "기재 유의어",
                 "trait_dict": "행특 설계 사전", "tags": "태그 프롬프트"}
_SNO = re.compile(r"(?<!\d)[1-3]\d{4}(?!\d)")  # 학번(학년+반 2자리+번호 2자리)처럼 보이는 다섯 자리


# ---------- 담을 수 있는 것 ----------
def _prompt_items():
    lib, _ = prompts.build_library(config.load().get("prompt_lib"), config.load().get("prompts"))
    out = []
    for x in lib:
        if x["builtin"]:
            b = prompts.BUILTIN[x["id"]]
            if x["prompt"].strip() == b["prompt"].strip() and x["example"].strip() == (b["example"] or "").strip():
                continue  # 고치지 않은 기본은 받는 쪽에도 있다
        out.append({"key": x["id"], "name": x["name"], "builtin": x["builtin"], "prompt": x["prompt"], "example": x["example"], "made": x.get("made", "")})
    return out


def _example_items():
    base = {d["id"]: d for d in examples._defaults()}
    out = []
    for e in examples.load():
        if e["builtin"]:
            d = base.get(e["id"])
            if d and all(e[k] == d[k] for k in ("text", "subject", "area", "name", "item")):
                continue
        out.append({"key": e["id"], "name": e["label"], "builtin": e["builtin"],
                    **{k: e[k] for k in ("item", "area", "subject", "name", "text", "source")}})
    return out


def _tag_items(d):
    if d is None:
        return []
    from .tagwork import TagWork
    out = []
    tw = TagWork(d)
    for t in d.q("SELECT id, name FROM tags ORDER BY sort_order, name"):
        w = tw.work_for_tag(t["id"], create=False)
        if w and w["confirmed"] and (w["confirmed"].get("chain") or {}).get("steps"):
            ch = w["confirmed"]["chain"]
            out.append({"key": t["name"], "name": t["name"], "chain": {"src": ch.get("src", "original"), "steps": ch["steps"]}})
    return out


def _texts(sec, x):
    if sec == "prompts":
        return [x["name"], x["prompt"], x["example"]]
    if sec == "examples":
        return [x["name"], x["text"]]
    if sec == "tags":
        return [x["name"]] + [s.get(k, "") for s in x["chain"]["steps"] for k in ("prompt", "example", "request")]
    return []


def scan_personal(texts, names):
    """글 속 학생 이름·학번처럼 보이는 말(겹침 없이, 앞 10개)."""
    hits = []
    blob = "\n".join(t for t in texts if t)
    for n in names:
        if len(n) >= 2 and n in blob and n not in hits:
            hits.append(n)
    for m in _SNO.findall(blob):
        if m not in hits:
            hits.append(m)
    return hits[:10]


def catalog(d=None, names=()):
    """내보내기 화면용: 묶음별 담을 수 있는 것 + 개인 정보처럼 보이는 말."""
    out = {}
    for sec, items in (("prompts", _prompt_items()), ("examples", _example_items()), ("tags", _tag_items(d))):
        out[sec] = [{"key": x["key"], "name": x["name"], "builtin": x.get("builtin", False),
                     "warn": scan_personal(_texts(sec, x), names)} for x in items]
    v = vocab.load()
    out["vocab"] = {"available": not vocab.is_default(), "count": len(v["verbs"]) + len(v["evals"])}
    out["banned"] = {"available": not banned.is_default(), "count": len(banned.load())}
    out["trait_dict"] = {"available": not trait_dict.is_default(), "count": len(trait_dict.load()["types"])}
    return out


def nick_clean(nick):
    """꾸러미 닉네임: 파일 이름에 못 쓰는 글자를 빼고 한글을 NFC(완성형)로 — Mac에서 만든 이름이 Windows에서 자소 분리되지 않게."""
    import unicodedata
    n = unicodedata.normalize("NFC", " ".join(str(nick or "").split()))
    n = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", n).strip(" .")
    return n[:20]


def file_name(nick):
    import unicodedata
    n = nick_clean(nick)
    day = dt.datetime.now().strftime("%y%m%d")
    return unicodedata.normalize("NFC", f"{n}의 꾸러미_{day}.sgbset" if n else f"착즙기 꾸러미_{day}.sgbset")


def build(sel, d=None, nick=""):
    """sel: {prompts:[key], examples:[key], tags:[key], vocab:bool, banned:bool, trait_dict:bool} → 꾸러미(dict)."""
    sel = sel or {}
    items = {}
    want = lambda sec: set(str(k) for k in (sel.get(sec) or []))
    p = [{k: x[k] for k in ("key", "name", "builtin", "prompt", "example", "made")} for x in _prompt_items() if x["key"] in want("prompts")]
    if p:
        items["prompts"] = p
    e = [{k: x[k] for k in ("key", "name", "builtin", "item", "area", "subject", "text", "source")} for x in _example_items() if x["key"] in want("examples")]
    if e:
        items["examples"] = e
    t = [{"name": x["name"], "chain": x["chain"]} for x in _tag_items(d) if x["key"] in want("tags")]
    if t:
        items["tags"] = t
    if sel.get("vocab"):
        v = vocab.load()
        items["vocab"] = {"verbs": v["verbs"], "evals": v["evals"]}
    if sel.get("banned"):
        items["banned"] = banned.load()
    if sel.get("trait_dict"):
        items["trait_dict"] = trait_dict.load()
    if not items:
        raise DbError("담을 항목을 하나 이상 고르세요.")
    return {"format": FORMAT, "format_version": FORMAT_VER, "app_version": VERSION, "author": nick_clean(nick),
            "made_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "items": items}


# ---------- 가져오기 ----------
def read(path):
    try:
        raw = open(path, "rb").read(MAX_FILE + 1)
    except OSError:
        raise DbError("파일을 열지 못했습니다.")
    if len(raw) > MAX_FILE:
        raise DbError("파일이 너무 큽니다(설정 꾸러미가 아닌 것 같습니다).")
    try:
        pkg = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise DbError("설정 꾸러미 파일이 아닙니다(.sgbset 파일을 골라 주세요).")
    if not isinstance(pkg, dict) or pkg.get("format") != FORMAT or not isinstance(pkg.get("items"), dict):
        raise DbError("설정 꾸러미 파일이 아닙니다(.sgbset 파일을 골라 주세요).")
    if int(pkg.get("format_version") or 0) > FORMAT_VER:
        raise DbError("더 새 버전의 착즙기에서 만든 꾸러미입니다. 착즙기를 업데이트한 뒤 가져와 주세요.")
    return pkg


def _clean_prompt(x):
    return {"key": str(x.get("key") or "")[:40], "name": " ".join(str(x.get("name") or "이름 없음").split())[:60],
            "builtin": bool(x.get("builtin")) and str(x.get("key")) in prompts.BUILTIN,
            "prompt": str(x.get("prompt") or "")[:20000], "example": str(x.get("example") or "")[:20000], "made": str(x.get("made") or "")[:10]}


def preview(pkg, d=None):
    """가져오기 화면용: 꾸러미 안 항목과 겹침(같은 이름·같은 기본 항목이 이미 있는지)."""
    it = pkg["items"]
    out = {"app_version": str(pkg.get("app_version") or ""), "made_at": str(pkg.get("made_at") or ""), "author": nick_clean(pkg.get("author"))}
    if isinstance(it.get("prompts"), list):
        mine, _ = prompts.build_library(config.load().get("prompt_lib"), config.load().get("prompts"))
        names = {x["name"] for x in mine if not x["builtin"]}
        out["prompts"] = [{"i": i, "name": p["name"], "builtin": p["builtin"], "exists": p["builtin"] or p["name"] in names}
                          for i, p in enumerate(_clean_prompt(x) for x in it["prompts"] if isinstance(x, dict))]
    if isinstance(it.get("examples"), list):
        mine = examples.load()
        ids, labels = {e["id"] for e in mine}, {e["label"] for e in mine}
        out["examples"] = [{"i": i, "name": str(x.get("name") or "")[:80] or examples.first_phrase(x.get("text")), "builtin": bool(x.get("builtin")),
                            "exists": (bool(x.get("builtin")) and str(x.get("key")) in ids) or str(x.get("name") or "") in labels}
                           for i, x in enumerate(y for y in it["examples"] if isinstance(y, dict))]
    if isinstance(it.get("tags"), list):
        have = {}
        if d is not None:
            from .tagwork import TagWork
            tw = TagWork(d)
            for t in d.q("SELECT id, name FROM tags"):
                w = tw.work_for_tag(t["id"], create=False)
                have[t["name"]] = bool(w and w["confirmed"])
        out["tags"] = [{"i": i, "name": str(x.get("name") or "")[:40], "exists": str(x.get("name") or "") in have,
                        "has_conf": have.get(str(x.get("name") or ""), False)}
                       for i, x in enumerate(y for y in it["tags"] if isinstance(y, dict))]
        out["tags_need_year"] = d is None
    if isinstance(it.get("vocab"), dict):
        out["vocab"] = {"count": len(it["vocab"].get("verbs") or []) + len(it["vocab"].get("evals") or [])}
    if isinstance(it.get("banned"), list):
        out["banned"] = {"count": len(it["banned"])}
    if isinstance(it.get("trait_dict"), dict):
        out["trait_dict"] = {"count": len(it["trait_dict"].get("types") or [])}
    return out


def _new_name(name, taken, suffix=" (가져옴)"):
    n = (name + suffix)[:60]
    k = 2
    while n in taken:
        n = f"{name}{suffix[:-1]} {k})"[:60]
        k += 1
    return n


def backup_config(data_dir):
    """가져오기 직전 설정 파일 복사본(되돌리기용). → 파일 이름"""
    src = config.config_path()
    if not src.exists():
        return ""
    name = f"설정_가져오기전_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    dst = data_dir / "backups"
    dst.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst / name)
    return name


def apply(pkg, choice, d=None):
    """choice: {prompts:{i: skip|overwrite|new}, examples:{...}, tags:{i: skip|overwrite}, vocab/banned/trait_dict: skip|merge|replace}
    → 바뀐 수 요약."""
    it, ch, done = pkg["items"], choice or {}, {}
    pick = lambda sec, i: str((ch.get(sec) or {}).get(str(i)) or "skip")
    # 프롬프트
    if isinstance(it.get("prompts"), list):
        cfg = config.load()
        lib, _ = prompts.build_library(cfg.get("prompt_lib"), cfg.get("prompts"))
        n = 0
        for i, p in enumerate(_clean_prompt(x) for x in it["prompts"] if isinstance(x, dict)):
            how = pick("prompts", i)
            if how == "skip" or not p["prompt"].strip():
                continue
            taken = {x["name"] for x in lib}
            if p["builtin"] and how == "overwrite":
                for x in lib:
                    if x["id"] == p["key"]:
                        x["prompt"], x["example"] = p["prompt"], p["example"]
            else:
                same = next((x for x in lib if not x["builtin"] and x["name"] == p["name"]), None)
                if how == "overwrite" and same:
                    same.update(prompt=p["prompt"], example=p["example"])
                else:
                    name = p["name"] if p["name"] not in taken else _new_name(p["name"], taken)
                    lib.append({"id": "p" + __import__("uuid").uuid4().hex[:10], "name": name, "prompt": p["prompt"], "example": p["example"],
                                "builtin": False, "made": p["made"], "tags": []})
            n += 1
        if n:
            config.save({"prompt_lib": lib})
            done["prompts"] = n
    # 예시
    if isinstance(it.get("examples"), list):
        n = 0
        for i, x in enumerate(y for y in it["examples"] if isinstance(y, dict)):
            how = pick("examples", i)
            if how == "skip" or not str(x.get("text") or "").strip():
                continue
            mine = examples.load()
            e = {k: x.get(k) for k in ("item", "area", "subject", "name", "text", "source")}
            tgt = None
            if how == "overwrite":
                tgt = next((m for m in mine if (x.get("builtin") and m["id"] == str(x.get("key"))) or (x.get("name") and m["label"] == x.get("name"))), None)
            if tgt:
                examples.save({**e, "id": tgt["id"]})
            else:
                labels = {m["label"] for m in mine}
                if e.get("name") and e["name"] in labels:
                    e["name"] = _new_name(e["name"], labels)
                examples.save({**e, "id": ""})
            n += 1
        if n:
            done["examples"] = n
    # 세특 어휘
    how = str(ch.get("vocab") or "skip")
    if isinstance(it.get("vocab"), dict) and how in ("merge", "replace"):
        cur = vocab.load()
        new = {"on": cur["on"], "verbs": list(it["vocab"].get("verbs") or []), "evals": list(it["vocab"].get("evals") or [])}
        if how == "merge":
            new["verbs"], new["evals"] = cur["verbs"] + new["verbs"], cur["evals"] + new["evals"]
        vocab.save(new)
        done["vocab"] = how
    # 기재 유의어
    how = str(ch.get("banned") or "skip")
    if isinstance(it.get("banned"), list) and how in ("merge", "replace"):
        inc = banned.normalize(it["banned"])
        if how == "merge":
            cur = banned.load()
            have = {t for e in cur for t in e["terms"]}
            inc = cur + [e for e in inc if not (set(e["terms"]) & have)]
        banned.save(inc)
        done["banned"] = how
    # 행특 설계 사전
    how = str(ch.get("trait_dict") or "skip")
    if isinstance(it.get("trait_dict"), dict) and how in ("merge", "replace"):
        inc = trait_dict.normalize(it["trait_dict"])
        if how == "merge":
            cur = copy.deepcopy(trait_dict.load())
            tn = {t["name"] for t in cur["types"]}
            cur["types"] += [t for t in inc["types"] if t["name"] not in tn]
            for a in trait_dict.AREAS:
                kws = {e["kw"] for e in cur["areas"][a]}
                cur["areas"][a] += [e for e in inc["areas"][a] if e["kw"] not in kws]
            inc = cur
        trait_dict.save(inc)
        done["trait_dict"] = how
    # 태그 프롬프트(지금 학년도)
    if isinstance(it.get("tags"), list) and d is not None:
        from .records import Records
        from .tagwork import TagWork, norm_chain
        rec, tw, n = Records(d), TagWork(d), 0
        for i, x in enumerate(y for y in it["tags"] if isinstance(y, dict)):
            how = pick("tags", i)
            name = " ".join(str(x.get("name") or "").split())[:40]
            if how == "skip" or not name:
                continue
            row = d.q("SELECT id FROM tags WHERE name=?", (name,))
            tid = row[0]["id"] if row else rec.add_tag(name)
            w = tw.work_for_tag(tid)
            if w["confirmed"] and how != "overwrite":
                continue
            conf = {"cand_id": None, "record_id": None, "chain": norm_chain(x.get("chain")), "ver_no": None,
                    "edit": {"by": "가져오기", "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}}
            with d.tx() as c:
                c.execute("UPDATE tag_works SET confirmed=?, updated_at=datetime('now','localtime') WHERE id=?",
                          (json.dumps(conf, ensure_ascii=False), w["id"]))
            n += 1
        if n:
            done["tags"] = n
    return done
