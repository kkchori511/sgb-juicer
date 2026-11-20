"""예시 목록(v0.31): 프롬프트 메뉴의 '예시' 목록. AI 실행 확인 창에서 하나를 골라 이번 실행의 예시로 쓴다.

- 설정(config.json)의 example_lib = [{id, item, area, subject, name, text, source, builtin}]. 없으면 기본 예시(examples_default).
- 기본 예시도 고치고 지울 수 있다(고치면 목록 전체가 설정에 저장). [기본 예시로 되돌리기]는 기본 예시만 처음 모양으로 되돌리고 직접 만든 예시는 남긴다.
- 이름은 '[과목] 첫 구절'(이름을 비우면 자동).
"""
import copy
import time

from . import config, examples_default
from .db import DbError

ITEMS = ("subject", "autonomy", "career", "club", "behavior")
MAX_TEXT = 3000


def first_phrase(text, n=22):
    t = " ".join(str(text or "").split())
    for sep in (". ", "임.", "함.", "음.", "."):
        i = t.find(sep)
        if 0 < i <= n:
            return t[: i + len(sep)].strip()
    return t[:n] + ("…" if len(t) > n else "")


def auto_name(e):
    return f"[{e['subject']}] {first_phrase(e['text'])}" if e.get("subject") else first_phrase(e["text"])


def _defaults():
    return [{"id": x["id"], "item": "subject", "area": x["area"], "subject": x["subject"], "name": "", "text": x["text"],
             "source": f"{examples_default.SOURCE} {x['page']}쪽" if x.get("page") else examples_default.SOURCE, "builtin": True}
            for x in examples_default.EXAMPLES]


def _norm(e):
    if not isinstance(e, dict):
        raise DbError("예시 형식이 아닙니다.")
    text = str(e.get("text") or "").strip()[:MAX_TEXT]
    if not text:
        raise DbError("예시 글이 비어 있습니다.")
    item = e.get("item") if e.get("item") in ITEMS else "subject"
    out = {"id": str(e.get("id") or "").strip()[:40], "item": item, "area": " ".join(str(e.get("area") or "").split())[:30],
           "subject": " ".join(str(e.get("subject") or "").split())[:40], "name": " ".join(str(e.get("name") or "").split())[:80],
           "text": text, "source": " ".join(str(e.get("source") or "").split())[:200], "builtin": bool(e.get("builtin"))}
    return out


def load():
    lib = config.load().get("example_lib")
    if not isinstance(lib, list):
        lib = _defaults()
    out = []
    for e in lib:
        try:
            x = _norm(e)
        except DbError:
            continue
        if x["id"]:
            x["label"] = x["name"] or auto_name(x)
            out.append(x)
    return out


def _store(lib):
    config.save({"example_lib": [{k: v for k, v in e.items() if k != "label"} for e in lib]})


def get(eid):
    return next((e for e in load() if e["id"] == str(eid)), None)


def save(e):
    """id가 있으면 고치고, 없으면 새로 더한다. 저장한 예시를 돌려준다."""
    x = _norm(e)
    lib = load()
    if x["id"]:
        old = next((i for i, y in enumerate(lib) if y["id"] == x["id"]), None)
        if old is None:
            raise DbError("고칠 예시를 찾지 못했습니다(지워졌을 수 있음).")
        x["builtin"] = lib[old]["builtin"]
        lib[old] = x
    else:
        x["id"] = f"my_{int(time.time() * 1000)}"
        x["builtin"] = False
        lib.append(x)
    _store(lib)
    return next(y for y in load() if y["id"] == x["id"])


def delete(eid):
    lib = load()
    keep = [e for e in lib if e["id"] != str(eid)]
    if len(keep) == len(lib):
        raise DbError("지울 예시를 찾지 못했습니다.")
    _store(keep)
    return len(keep)


def reset_builtin():
    """기본 예시를 처음 모양으로(지운 것도 되살림). 직접 만든 예시는 그대로."""
    mine = [e for e in load() if not e["builtin"]]
    _store(_defaults() + mine)
    return load()
