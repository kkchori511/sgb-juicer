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
    """code: 'service_down'(연결 실패·시간 초과·서버 오류 — OpenRouter 장애일 수 있음), 'rate_limited'(속도 제한이 계속됨).
    화면은 이 둘이면 남은 건을 보내지 않고 멈춘 뒤 안내 창을 띄운다."""

    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


DOWN = (500, 502, 503, 504, 520, 521, 522, 523, 524)


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


# 바로 중지: cancel()은 진행 중인 요청 연결을 모두 닫고, 끝나기 전까지 새 요청·결과를 막는다(reset()으로 풀림).
_cancel = threading.Event()
_active = set()
_active_lock = threading.Lock()


class Cancelled(LlmError):
    def __init__(self):
        super().__init__("중지했습니다. 이 건은 저장하지 않았습니다.", "cancelled")


def cancel():
    _cancel.set()
    with _active_lock:
        live = list(_active)
    for r in live:
        try:
            r.close()
        except Exception:
            pass


def reset():
    _cancel.clear()


def cancelled() -> bool:
    return _cancel.is_set()


def _check():
    if _cancel.is_set():
        raise Cancelled()


def _sleep(sec):
    """재시도 기다림도 중지하면 바로 끝낸다."""
    if _cancel.wait(sec):
        raise Cancelled()


def _read_stream(res):
    """SSE 응답을 조각조각 읽는다. 중지하면 연결을 닫아 남은 생성을 멈춘다(제공자에 따라 그만큼 비용이 덜 나감)."""
    parts, cost = [], 0.0
    for raw in res.iter_lines(decode_unicode=False):
        _check()
        if not raw:
            continue
        line = raw.decode("utf-8", "replace")
        if line.startswith(":") or not line.startswith("data:"):
            continue  # ': OPENROUTER PROCESSING' 같은 대기 신호
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except ValueError:
            continue
        if isinstance(chunk.get("error"), dict):
            raise LlmError(_explain(0, chunk["error"].get("message") or "", False))
        for ch in chunk.get("choices") or []:
            d = ch.get("delta") or ch.get("message") or {}
            if d.get("content"):
                parts.append(d["content"])
            if ch.get("finish_reason") == "error":
                raise LlmError("AI가 답을 만들다 오류로 멈췄습니다. 다시 시도하거나 다른 모델을 고르세요.")
        if chunk.get("usage"):
            cost = float(chunk["usage"].get("cost") or 0)
    _check()
    return "".join(parts).strip(), cost


def chat(key: str, model: str, system: str, user: str, privacy_block: bool = False) -> tuple[str, float]:
    """(응답 텍스트, 비용 크레딧). 학번·이름은 부르는 쪽에서 미리 빼고 내용만 넘긴다.
    응답은 스트리밍으로 받아 [바로 중지] 때 연결을 끊을 수 있게 한다."""
    if not key:
        raise LlmError("OpenRouter API 키를 입력해 주세요.")
    payload = {**build_payload(model, system, user, privacy_block), "stream": True}
    last = None
    for attempt in range(3):
        _check()
        try:
            res = requests.post(
                f"{BASE}/chat/completions", headers=_headers(key), json=payload, timeout=(20, 300), stream=True
            )
        except requests.RequestException as e:
            _check()
            last = LlmError(f"OpenRouter에 연결하지 못했습니다({e.__class__.__name__}). 인터넷 연결이나 OpenRouter 상태를 확인해 주세요.", "service_down")
            _sleep(2 * (attempt + 1))
            continue
        with _active_lock:
            _active.add(res)
        try:
            if res.status_code == 429 or res.status_code in DOWN:
                if attempt < 2:
                    _sleep(3 * (attempt + 1))
                    continue
                if res.status_code == 429:
                    raise LlmError("속도 제한이 계속됩니다(HTTP 429). 잠시 뒤 다시 시도하거나 다른 모델을 고르세요(무료 모델은 제한이 큽니다).", "rate_limited")
                raise LlmError(f"OpenRouter 서버가 응답하지 않습니다(HTTP {res.status_code}). 잠시 뒤 다시 시도하거나 OpenRouter 상태를 확인해 주세요.", "service_down")
            ctype = str((getattr(res, "headers", None) or {}).get("Content-Type") or "")
            if res.ok and "event-stream" in ctype:
                try:
                    return _read_stream(res)
                except LlmError:
                    raise
                except Exception as e:  # 읽는 중 끊김(중지로 닫은 경우 포함)
                    _check()
                    last = LlmError(f"AI 응답을 받다 연결이 끊겼습니다({e.__class__.__name__}). 다시 시도해 주세요.", "service_down")
                    _sleep(2 * (attempt + 1))
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
            _check()
            cost = float((body.get("usage") or {}).get("cost") or 0)
            return text.strip(), cost
        finally:
            with _active_lock:
                _active.discard(res)
            try:
                res.close()
            except Exception:
                pass
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
