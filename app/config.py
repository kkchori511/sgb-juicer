"""설정 파일(평문 JSON). 키·모델·화면 상태처럼 학년도와 무관한 값만 둔다.

학년도별 자료(역할, 담당, 명렬, 일정)는 db.py의 SQLite에 둔다.
"""
import json
import os
import threading
import time

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


class ConfigError(Exception):
    """설정 파일이 있는데 읽지 못함(다른 프로그램이 잡고 있음 등): 기본값으로 덮어쓰지 않으려고 저장을 막는다."""


# 마지막 읽기 결과: error(읽지 못한 까닭) / broken(깨진 파일을 옮겨 둔 이름)
_state = {"error": None, "broken": None}


def _read(path, tries=10, wait=0.3):
    """설정 파일 읽기. 잠깐 잠긴 경우(백신 검사·업데이트 직후)를 위해 몇 번 다시 읽는다.
    없으면 None, 깨졌으면 ValueError, 끝내 못 읽으면 OSError."""
    last = None
    for i in range(tries):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except OSError as e:
            last = e
            time.sleep(wait)
    raise last


def _set_aside(path):
    """깨진 설정 파일은 지우지 않고 옆에 이름을 바꿔 둔다(다음부터는 새 설정으로)."""
    name = f"{path.stem}.깨짐_{time.strftime('%Y%m%d_%H%M%S')}{path.suffix}"
    try:
        os.replace(path, path.with_name(name))
        return name
    except OSError:
        return None


def load() -> dict:
    cfg = _fresh()
    path = config_path()
    try:
        saved = _read(path)
        _state["error"] = None
    except ValueError:
        saved = None
        _state["error"] = None
        _state["broken"] = _set_aside(path) or "(옮기지 못함)"
    except OSError as e:
        saved = None
        _state["error"] = f"{e.__class__.__name__}: {getattr(e, 'strerror', '') or e}"
    if isinstance(saved, dict):
        cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    return _normalize(cfg)


def read_problem() -> dict:
    """화면 안내용: 마지막으로 읽을 때 생긴 문제."""
    return {"error": _state["error"], "broken": _state["broken"]}


def save(patch: dict) -> dict:
    """patch에 있는 알려진 키만 덮어쓴다. 쓰기 도중 꺼져도 깨지지 않게 임시 파일 후 교체."""
    with _lock:
        merged = load()
        if _state["error"]:
            raise ConfigError(f"설정 파일을 읽지 못해 저장하지 않았습니다({_state['error']}). 잠시 뒤 다시 시도하거나 앱을 다시 켜 주세요. 백신 프로그램이 파일을 잡고 있을 수 있습니다.")
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
