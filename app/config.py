"""설정 파일(평문 JSON). 키·모델·화면 상태처럼 학년도와 무관한 값만 둔다.

학년도별 자료(역할, 담당, 명렬, 일정)는 db.py의 SQLite에 둔다.
"""
import json
import os
import threading

from .paths import data_dir

CONFIG_NAME = "생기부착즙기_설정.json"
KEY_FIELDS = ("openrouter_key", "clova_url", "clova_secret")
FREE_MODEL = "google/gemma-4-31b-it:free"

DEFAULTS = {
    "openrouter_key": "",
    "clova_url": "",
    "clova_secret": "",
    "ocr_lang": "ko",
    # 모델 4칸. 1번은 무료 모델을 미리 넣어 둔다.
    "models": [FREE_MODEL, "", "", ""],
    "default_model": 0,
    # OpenRouter 학습 차단(data_collection=deny, zdr=true). 기본 꺼짐.
    "privacy_block": False,
    "setup_done": False,
    "current_year": 0,
    "menu_collapsed": False,
    "window": {},  # {x, y, width, height}
    "last_backup": "",
    # 항목×작업별 개인 프롬프트 {item: {op: {prompt, example}}} — 비어 있으면 기본값
    "prompts": {},
    # v0.17.6 프롬프트 목록 [{id, name, prompt, example}] — None이면 처음(기본 3개 + 예전 항목별 프롬프트로 만든다)
    "prompt_lib": None,
    # 작업 종류(synth/refine/polish)마다 마지막에 고른 프롬프트 id
    "prompt_pick": {},
    # 종합 비중 합계 100% 검사(기본 꺼짐)
    "weight_sum_check": False,
}

_lock = threading.Lock()


def config_path():
    return data_dir() / CONFIG_NAME


def _fresh() -> dict:
    return json.loads(json.dumps(DEFAULTS))


def _normalize(cfg: dict) -> dict:
    models = cfg.get("models")
    if not isinstance(models, list):
        models = []
    models = [str(m or "").strip() for m in models][:4]
    models += [""] * (4 - len(models))
    cfg["models"] = models
    if not isinstance(cfg.get("default_model"), int) or not 0 <= cfg["default_model"] < 4:
        cfg["default_model"] = 0
    if not isinstance(cfg.get("window"), dict):
        cfg["window"] = {}
    if not isinstance(cfg.get("prompts"), dict):
        cfg["prompts"] = {}
    if not isinstance(cfg.get("prompt_lib"), list):
        cfg["prompt_lib"] = None
    if not isinstance(cfg.get("prompt_pick"), dict):
        cfg["prompt_pick"] = {}
    for k in ("privacy_block", "setup_done", "menu_collapsed", "weight_sum_check"):
        cfg[k] = bool(cfg.get(k))
    try:
        cfg["current_year"] = int(cfg.get("current_year") or 0)
    except (TypeError, ValueError):
        cfg["current_year"] = 0
    return cfg


def load() -> dict:
    cfg = _fresh()
    try:
        with open(config_path(), encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return _normalize(cfg)


def save(patch: dict) -> dict:
    """patch에 있는 알려진 키만 덮어쓴다. 쓰기 도중 꺼져도 깨지지 않게 임시 파일 후 교체."""
    with _lock:
        merged = load()
        merged.update({k: v for k, v in (patch or {}).items() if k in DEFAULTS})
        merged = _normalize(merged)
        path = config_path()
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return merged


def reset_keys() -> dict:
    return save({k: "" for k in KEY_FIELDS})
