"""OpenRouter 호출: 모델 단가, 채팅, 잔액."""
import json
import re
import threading
import time

import requests

BASE = "https://openrouter.ai/api/v1"
MODELS_PAGE = "https://openrouter.ai/models"

_models_cache = {"at": 0.0, "data": None}
_models_lock = threading.Lock()


class LlmError(Exception):
    pass


def normalize_model_id(text: str) -> str:
    """붙여넣은 값이 URL이어도 모델 ID만 남긴다."""
    t = (text or "").strip()
    t = re.sub(r"^https?://(www\.)?openrouter\.ai/", "", t)
    t = t.split("?")[0].split("#")[0].strip("/")
    for suffix in ("/api", "/providers", "/apps", "/activity", "/uptime", "/parameters"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    return t


def _headers(key: str) -> dict:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "SGB Juicer",  # 헤더는 ASCII만 허용
    }


def _models() -> list:
    with _models_lock:
        if _models_cache["data"] is None or time.time() - _models_cache["at"] > 600:
            try:
                res = requests.get(f"{BASE}/models", timeout=30)
                res.raise_for_status()
                _models_cache["data"] = res.json().get("data", [])
                _models_cache["at"] = time.time()
            except (requests.RequestException, ValueError) as e:
                raise LlmError("OpenRouter 모델 목록을 가져오지 못했습니다.") from e
        return _models_cache["data"]


def model_info(model_id: str) -> dict:
    mid = normalize_model_id(model_id)
    if not mid:
        raise LlmError("모델 ID가 비어 있습니다.")
    for m in _models():
        if m.get("id") == mid or m.get("canonical_slug") == mid:
            p = m.get("pricing") or {}

            def per_m(v):
                try:
                    return float(v) * 1_000_000
                except (TypeError, ValueError):
                    return None

            return {
                "id": m["id"],
                "name": m.get("name", m["id"]),
                "prompt_per_m": per_m(p.get("prompt")),
                "completion_per_m": per_m(p.get("completion")),
            }
    raise LlmError(f"OpenRouter에 '{mid}' 모델이 없습니다. 모델 ID를 확인해 주세요.")


PRIVACY_PROVIDER = {"data_collection": "deny", "zdr": True}


def build_payload(model: str, system: str, user: str, privacy_block: bool) -> dict:
    payload = {
        "model": normalize_model_id(model),
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "usage": {"include": True},
    }
    if privacy_block:
        payload["provider"] = dict(PRIVACY_PROVIDER)
    return payload


def _explain(status: int, msg: str, privacy_block: bool) -> str:
    """오류를 원인별로 나눈다: 제공자 없음 / 속도 제한 / 키·잔액."""
    low = (msg or "").lower()
    if status == 401:
        kind = "키 문제: API 키를 확인해 주세요."
    elif status == 402:
        kind = "잔액 문제: 크레딧이 부족합니다."
    elif status == 429:
        kind = "속도 제한: 잠시 뒤 다시 시도하거나 다른 모델을 고르세요(무료 모델은 제한이 큽니다)."
    elif status == 404 or "no endpoints" in low or "no allowed providers" in low:
        kind = "제공자 없음: 이 모델을 처리할 수 있는 제공자가 없습니다."
        if privacy_block:
            kind += " 학습 차단을 켜 두어 쓸 수 있는 제공자가 없을 수 있습니다. 다른 모델을 고르거나 설정에서 학습 차단을 확인하세요."
    else:
        kind = f"OpenRouter 오류(HTTP {status})"
    return f"{kind} {('- ' + msg) if msg else ''}".strip()


def chat(key: str, model: str, system: str, user: str, privacy_block: bool = False) -> tuple[str, float]:
    """(응답 텍스트, 비용 크레딧). 학번·이름은 부르는 쪽에서 미리 빼고 내용만 넘긴다."""
    if not key:
        raise LlmError("OpenRouter API 키를 입력해 주세요.")
    payload = build_payload(model, system, user, privacy_block)
    last = None
    for attempt in range(3):
        try:
            res = requests.post(
                f"{BASE}/chat/completions", headers=_headers(key), json=payload, timeout=300
            )
        except requests.RequestException as e:
            last = LlmError(f"OpenRouter에 연결하지 못했습니다: {e.__class__.__name__}")
            time.sleep(2 * (attempt + 1))
            continue
        if res.status_code in (429, 502, 503) and attempt < 2:
            last = LlmError(f"OpenRouter HTTP {res.status_code}")
            time.sleep(3 * (attempt + 1))
            continue
        try:
            body = res.json()
        except ValueError:
            body = {}
        if not res.ok or "error" in body:
            err = body.get("error") if isinstance(body, dict) else None
            msg = err.get("message") if isinstance(err, dict) else ""
            raise LlmError(_explain(res.status_code, msg, privacy_block))
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LlmError("OpenRouter 응답 형식이 올바르지 않습니다.") from e
        cost = float((body.get("usage") or {}).get("cost") or 0)
        return text.strip(), cost
    raise last or LlmError("OpenRouter 호출에 실패했습니다.")


def balance(key: str):
    """남은 크레딧. 알 수 없으면 None."""
    if not key:
        return None
    try:
        res = requests.get(f"{BASE}/credits", headers=_headers(key), timeout=20)
        if res.ok:
            d = res.json().get("data") or {}
            return float(d.get("total_credits", 0)) - float(d.get("total_usage", 0))
        res = requests.get(f"{BASE}/key", headers=_headers(key), timeout=20)
        if res.ok:
            d = res.json().get("data") or {}
            if d.get("limit_remaining") is not None:
                return float(d["limit_remaining"])
    except (requests.RequestException, ValueError, TypeError):
        pass
    return None


def check_key(key: str) -> dict:
    """[연결 확인]: 키가 맞는지와 잔액. {'ok', 'error', 'balance'}"""
    if not (key or "").strip():
        return {"ok": False, "error": "OpenRouter API 키를 입력해 주세요."}
    try:
        res = requests.get(f"{BASE}/key", headers=_headers(key.strip()), timeout=20)
    except requests.RequestException:
        return {"ok": False, "error": "OpenRouter에 연결하지 못했습니다. 인터넷 연결을 확인해 주세요."}
    if res.status_code == 401:
        return {"ok": False, "error": "키가 올바르지 않습니다. 다시 복사해 붙여넣어 주세요."}
    if not res.ok:
        return {"ok": False, "error": f"확인하지 못했습니다(HTTP {res.status_code})."}
    return {"ok": True, "balance": balance(key.strip())}


def parse_json_object(text: str) -> dict:
    """모델이 코드블록이나 설명을 붙여도 첫 JSON 객체를 꺼낸다."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        v = json.loads(t)
        if isinstance(v, dict):
            return v
    except ValueError:
        pass
    start = t.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        v = json.loads(t[start : i + 1])
                        if isinstance(v, dict):
                            return v
                    except ValueError:
                        pass
                    break
        start = t.find("{", start + 1)
    raise LlmError("정제 결과에서 JSON을 찾지 못했습니다.")
