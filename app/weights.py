"""종합할 때 기록별 분량 비율(J14).

- 고른 기록만 계산한다.
- 기본: 기록 길이(바이트)에 비례.
- 일부만 지정하면 남은 비율을 비운 기록끼리 길이 비례로 나눈다.
- 합계 검사 ON: 지정값과 자동 배분의 합이 정확히 100%여야 한다.
- 합계 검사 OFF: 비율대로 정규화해 쓴다(실제 적용 비율을 돌려준다).
"""


class WeightError(Exception):
    pass


def _num(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise WeightError("비중은 숫자로 입력해 주세요.")
    if x < 0:
        raise WeightError("비중은 0 이상이어야 합니다.")
    return x


def compute(items: list[dict], sum_check: bool) -> list[float]:
    """items: [{bytes, weight(None 또는 %)}] → 각 기록의 비율(0~1, 합 1)."""
    if not items:
        raise WeightError("종합할 기록을 고르세요.")
    ws = [_num(it.get("weight")) for it in items]
    bs = [max(1, int(it.get("bytes") or 0)) for it in items]
    given = sum(w for w in ws if w is not None)
    free = [i for i, w in enumerate(ws) if w is None]
    free_bytes = sum(bs[i] for i in free)
    raw = list(ws)
    if sum_check:
        if given > 100 + 1e-9:
            raise WeightError(f"지정한 비중의 합이 {given:g}%로 100%를 넘습니다.")
        rest = 100 - given
        if free:
            if rest <= 1e-9:
                raise WeightError("비워 둔 기록에 나눠 줄 비율이 남지 않았습니다. 지정한 비중을 줄이거나 칸을 채워 주세요.")
            for i in free:
                raw[i] = rest * bs[i] / free_bytes
        elif abs(given - 100) > 1e-6:
            raise WeightError(f"비중의 합이 {given:g}%입니다. 100%가 되도록 맞춰 주세요.")
    else:
        if free:
            rest = 100 - given
            if rest <= 0:
                # 남은 비율이 없으면 비운 기록은 지정 기록 평균만큼 길이 비례로 둔다.
                base = (given / (len(ws) - len(free))) * len(free)
            else:
                base = rest
            for i in free:
                raw[i] = base * bs[i] / free_bytes
    total = sum(raw)
    if total <= 0:
        raise WeightError("비중이 모두 0입니다.")
    return [r / total for r in raw]
