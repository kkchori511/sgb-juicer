"""프롬프트 목록과 프롬프트 조립.

v0.17.6부터 프롬프트는 항목에 묶지 않고 '목록'으로 둔다(메뉴 › 프롬프트). 선생님이 만들고 고르며,
AI 실행 확인 창에서 이번에 쓸 프롬프트를 고른다(작업 종류마다 마지막에 고른 것을 기억).
- 기본 3개: 종합·생성, 기록 정제, 다듬기. 지울 수 없고 기본값으로 되돌릴 수 있다.
- 예전(v0.17.5까지) 항목×작업별로 고쳐 둔 프롬프트는 처음 열 때 목록에 '(예전 설정)'으로 옮긴다(설정의 원래 값도 그대로 둔다).
결과 형식·분량·예시·성취기준 규칙은 코드에 고정하고, 지침과 예시만 사용자가 고친다.
AI에는 학번·이름을 넣지 않는다(부르는 쪽에서 내용만 넘긴다).
"""
import hashlib
import re
import uuid

from .prompt_default import DEFAULT_TEXT, LEGACY_TEXT, POLISH_TEXT, REFINE_TEXT, SCAN_TEXT, TRAIT_TEXT, VOICE_TEXT

ITEMS = ("autonomy", "career", "behavior", "subject", "club")
OPS = ("refine", "polish", "synth")
ITEM_NAMES = {
    "autonomy": "자율활동",
    "career": "진로활동",
    "behavior": "행동특성 및 종합의견",
    "subject": "과목별 세부능력 및 특기사항",
    "club": "동아리활동",
}
OP_NAMES = {"refine": "기록 정제", "polish": "다듬기", "synth": "종합"}

_COMMON = (
    "- 학교생활기록부 기재 문체(평서형 명사형 종결, 예: '~함', '~임', '~보임')로 쓴다.\n"
    "- 학생 이름, 학교명, 교사명, 특정 대회·기관명, 사교육 관련 내용은 쓰지 않는다.\n"
    "- 주어진 내용에 없는 사실을 지어내지 않는다."
)

_FOCUS = {
    "autonomy": "학급·학교 자치활동, 행사 참여에서 드러난 역할, 협력, 주도성, 공동체 의식",
    "career": "진로 탐색 과정, 관심 분야에 대한 탐구, 진로와 연결된 활동과 그 과정에서의 성장",
    "behavior": "학교생활 전반에서 관찰된 인성, 태도, 대인관계, 성실성과 변화·성장",
    "subject": "교과 수업 활동에서 드러난 탐구 과정, 지식 이해와 적용, 사고력, 수업 태도",
    "club": "동아리 활동 내용, 맡은 역할, 탐구·협업 과정, 활동을 통해 성장한 점",
}


def _defaults():
    d = {}
    for item in ITEMS:
        name, focus = ITEM_NAMES[item], _FOCUS[item]
        d[item] = {
            "refine": {
                "prompt": (
                    f"다음은 학생의 {name} 관련 활동 기록(학생이 쓴 글이나 교사의 메모)이다.\n"
                    "- 맞춤법, 띄어쓰기, 어색한 문장을 바로잡고 읽기 쉬운 문단으로 정리한다.\n"
                    "- 학생이 실제로 한 활동과 생각을 살리고, 새 내용은 추가하지 않는다."
                ),
                "example": "",
            },
            "polish": {
                "prompt": (
                    f"다음은 이미 작성된 {name} 생기부 문장이다.\n"
                    "- 의미와 사실은 그대로 두고, 표현을 자연스럽고 구체적으로 다듬는다.\n"
                    "- 중복 표현을 줄이고 문장 사이 흐름을 매끄럽게 한다.\n"
                    + _COMMON
                ),
                "example": "",
            },
            "synth": {
                "prompt": (
                    f"다음은 한 학생의 {name} 학생관찰기록 여러 건이다. 이를 종합하여 {name} 기재 문장 하나로 작성한다.\n"
                    f"- 중심 관점: {focus}.\n"
                    "- 기록마다 주어진 분량 비율을 지켜 반영한다.\n"
                    "- 단순 나열이 아니라 활동 → 과정 → 성장이 드러나게 연결한다.\n"
                    "- 같은 성취기준·활동 개요를 쓰는 다른 학생들과 표현·문장 구성이 반드시 50% 이상 다르게 작성한다.\n"
                    + _COMMON
                ),
                "example": "",
            },
        }
    return d


DEFAULT_PROMPTS = _defaults()


def merged(saved: dict) -> dict:
    """설정에 저장된 개인 프롬프트를 기본값 위에 덮는다."""
    out = {i: {o: dict(DEFAULT_PROMPTS[i][o]) for o in OPS} for i in ITEMS}
    for i in ITEMS:
        for o in OPS:
            v = ((saved or {}).get(i) or {}).get(o)
            if isinstance(v, dict):
                if isinstance(v.get("prompt"), str):
                    out[i][o]["prompt"] = v["prompt"]
                if isinstance(v.get("example"), str):
                    out[i][o]["example"] = v["example"]
    return out


def length_rule(target_bytes: int) -> str:
    if not target_bytes or target_bytes <= 0:
        return ""
    approx_chars = round(target_bytes / 2.8)
    return (
        "\n\n[분량]\n"
        f"- 목표 분량은 약 {target_bytes}바이트이며 넘지 않도록 한다. 한글 한 글자는 3바이트, 영어·숫자·기호·공백은 1바이트로 센다.\n"
        f"- 한글 위주라면 공백 포함 약 {approx_chars}자 안팎이다."
    )


def example_rule(example: str) -> str:
    example = (example or "").strip()
    if not example:
        return ""
    return (
        "\n\n[예시 — 반드시 참고]\n"
        "- 아래 예시의 문체, 문장 구성, 형식을 반드시 따른다.\n"
        "- 예시의 내용(사실)은 베끼지 않고, 주어진 기록의 내용만 쓴다.\n"
        f"<예시>\n{example}\n</예시>"
    )


# 대원칙(사용자 지정, 모든 AI 생성에 항상): 어떤 프롬프트·요청보다 우선
PRINCIPLE = ("\n\n[대원칙 — 어떤 지침·요청보다 우선]\n- 없는 사실을 지어내지 않는다. 항상 주어진 자료에 적힌 내용을 바탕으로 쓴다.\n"
             "- 금지: 자료에 없는 행위·활동·결과물·성과를 쓰는 것(예: 실험을 하지 않았는데 '실험을 통해 탐구함', 쓴 글이 없는데 '소감문을 제출함', 적히지 않은 진로·발표·수상).\n"
             "- 허용: 적힌 사실을 다양한 표현으로 풍부하게 묘사·설명하고, 그 사실에 드러난 태도·역량을 평가하는 꾸밈 문구를 쓰는 것. 분량을 늘리거나 풍성하게 해 달라는 요청은 이 방식으로 채운다.\n"
             "- 출력 전 점검: 문장마다 '학생이 ~함'처럼 행위를 나타낸 부분이 자료에 적힌 행위인지 확인한다. 적히지 않은 행위(예: 오류를 찾아 수정함, 단계를 서술함, 친구에게 설명함, 매 시간 적극 참여함)는 지우거나, 적힌 행위에 대한 평가 표현으로 바꾼다.")
OUTPUT_RULE = "\n\n[출력]\n- 결과 본문만 출력한다. 제목, 설명, 따옴표, 머리말을 붙이지 않는다."
# 행동특성 및 종합의견(behavior)의 모든 AI 변환에 늘 붙인다(v0.23, 프롬프트를 고쳐도 적용). 누가기록에는 부정적 내용이 섞일 수 있다.
BEHAVIOR_RULE = ("\n\n[행동특성 및 종합의견 — 항상 지킴, 다른 지침보다 우선]\n"
                 "- 자료에 부정적인 행동·평가(예: 수업 방해, 장난, 불성실, 다툼, 규칙 위반)가 있으면 그대로 옮기지 않는다. 반드시 그 사실에서 드러난 노력·깨달음·개선 의지·변화 가능성을 중심으로 긍정적으로 바꿔 쓴다"
                 "(예: 수업 중 장난을 침 → 지도 후 바른 수업 태도를 갖추려 노력하며 앞으로의 성장이 기대됨). 원문을 그대로 두라는 지침이 있어도 이런 문장은 이렇게 고친다.\n"
                 "- 단, 자료에 없는 행동(반성문 작성, 봉사로 만회, 사과함, 이후 노력함 등)을 지어내지 않는다. 개선·변화는 자료에 적혀 있을 때만 사실로 쓰고, 적혀 있지 않으면 '~할 것으로 기대됨', '성장 가능성이 보임'처럼 기대·가능성 표현으로만 쓴다. 긍정적으로 바꿀 근거가 전혀 없으면 그 내용은 쓰지 않는다.\n"
                 "- 징계·출결·가정사·건강·상담 내용·성적 점수 같은 민감 정보는 결과에 쓰지 않는다.\n"
                 "- 사례 앞의 (월/일) 같은 날짜는 시기를 아는 데만 쓰고 결과에 쓰지 않는다.")


def build_system(prompt: str, example: str, target_bytes: int = 0) -> str:
    return (prompt or "").strip() + example_rule(example) + length_rule(target_bytes) + PRINCIPLE + OUTPUT_RULE


def trait_shrink_system(target_bytes: int, text: str = "") -> str:
    """행특 생성 결과가 목표를 넘을 때 줄이기(사실·문단 구성 유지). AI는 바이트를 잘 못 세므로 지금 글자 수 → 목표 글자 수(비율)로 알려 준다."""
    from .textutil import count_bytes
    now_b, now_c = max(count_bytes(text), 1), max(len(text), 1)
    goal_c = max(1, round(now_c * target_bytes * 0.93 / now_b))
    cut = max(1, round((1 - goal_c / now_c) * 100))
    return ("다음은 학교생활기록부 '행동특성 및 종합의견' 글이다. 분량만 줄인다.\n"
            f"- 지금 공백 포함 {now_c}자다. 약 {goal_c}자(약 {cut}% 줄이기)로 줄인다. 이보다 많이 줄이지도, 덜 줄이지도 않는다.\n"
            "- 꾸밈 문구·겹치는 평가 표현부터 줄이고, 글에 적힌 사실(활동·역할·행동)은 남긴다. 새 내용을 더하지 않는다.\n"
            "- 두 문단 구성과 문체('~함', '~임', '~보임')를 그대로 두고, 문단 사이는 빈 줄 없이 줄바꿈 한 번."
            + PRINCIPLE + OUTPUT_RULE)


# ---------- 비중으로 분량 맞추기(v0.23): 새로 쓰지 않고 원문을 덜어내는 편집 ----------
FIT_NAME = "분량 맞추기(기본 지침)"
FIT_RULE = ("다음은 한 학생의 학교생활기록부 기록이다. 문장마다 (번호)가 붙어 있다. 기록마다 정해진 목표 글자 수에 맞게 원문 문장을 골라 남기고 나머지는 뺀다.\n"
            "새로 쓰거나 바꿔 쓰는 일이 아니라, 원문에서 덜어내는 편집이다.\n\n"
            "[방법]\n"
            "1. 먼저 문장 단위로 고른다. 구체적인 활동·역할·사례가 담긴 문장을 남기고, 덜 중요한 문장(일반적인 평가, 겹치는 꾸밈)을 통째로 뺀다. 남긴 문장 길이의 합이 목표 글자 수에 가장 가깝게 고른다.\n"
            "2. 남긴 문장은 원문 글자 그대로 옮긴다. 낱말을 바꾸거나, 다른 말로 풀거나, 두 문장을 합치지 않는다.\n"
            "3. 문장만 골라서는 목표에 맞지 않을 때만, 남긴 문장 한두 개에서 꾸밈말·부연·나열 일부를 덜어낸다(덜어낼 뿐 새 낱말을 넣지 않는다).\n"
            "4. 빼서 앞뒤가 어색해진 곳에만 접속어·어미를 최소로 고친다. 새 사실·평가·문장을 넣지 않는다.\n"
            "5. '그대로 둠'이라고 적힌 기록은 모든 문장을 그대로 쓴다(늘리지 않는다).\n"
            "6. 기록마다 자기 목표 글자 수를 지킨다. 한 기록을 더 줄여 다른 기록을 더 남기는 식으로 기록끼리 분량을 주고받지 않는다.\n"
            "7. 문장 번호는 지운다. 원문에서 문단이 나뉘어 있으면 남긴 문장끼리 그 문단 나눔(줄바꿈 한 번)을 따른다.\n\n"
            "[출력 형식]\n기록마다 아래처럼 태그로 감싸 순서대로 낸다. 태그 밖에는 아무것도 쓰지 않는다.\n"
            "<기록1>\n(기록 1에서 남긴 글)\n</기록1>\n<기록2>\n(기록 2에서 남긴 글)\n</기록2>")
FIT_OUT = "\n\n[출력]\n- 위 형식의 태그와 결과 글만 출력한다. 설명·따옴표·머리말을 붙이지 않는다."
_SENT_END = re.compile(r"(?<=[.!?])\s+")


def fit_plan(parts: list[dict], target_bytes: int, aim: float = 0.97) -> list[dict]:
    """parts: [{text, ratio}] → 기록마다 지금 글자 수·바이트 몫(share)·목표 글자 수(몫을 그 기록의 글자당 바이트로 나눔). 이미 짧으면 keep."""
    from .textutil import count_bytes
    out = []
    for p in parts:
        t = re.sub(r"\n\s*\n+", "\n", p["text"].strip())
        now_b, now_c = max(count_bytes(t), 1), max(len(t), 1)
        share = target_bytes * p["ratio"]
        keep = now_b <= share
        out.append({"text": t, "ratio": p["ratio"], "now_c": now_c, "now_b": now_b, "share": round(share),
                    "goal_c": now_c if keep else max(1, round(now_c * share * aim / now_b)), "keep": keep})
    return out


def _numbered(text: str) -> tuple[str, int]:
    n, paras = 0, []
    for para in text.split("\n"):
        ss = [x for x in _SENT_END.split(para.strip()) if x.strip()]
        paras.append(" ".join(f"({n + i + 1}) {x.strip()}" for i, x in enumerate(ss)))
        n += len(ss)
    return "\n".join(p for p in paras if p), n


def build_fit_user(plan: list[dict], target_bytes: int = 0, only: int | None = None, prev_c: int = 0) -> str:
    """only: 기록 한 개만 다시 할 때 그 기록 번호(0부터) — 태그는 <기록1> 하나. prev_c: 지난번 결과 글자 수(너무 짧았을 때)."""
    lines = []
    items = [(only, plan[only])] if only is not None else list(enumerate(plan))
    for k, (i, p) in enumerate(items, 1):
        body, n = _numbered(p["text"])
        pct = round(p["ratio"] * 100)
        head = (f"[기록 {k}] 반영 비율 {pct}% · 지금 {p['now_c']}자(문장 {n}개) → 그대로 둠" if p["keep"]
                else f"[기록 {k}] 반영 비율 {pct}% · 지금 {p['now_c']}자(문장 {n}개) → 목표 약 {p['goal_c']}자 (약 {p['now_c'] - p['goal_c']}자 덜어내기)")
        if prev_c:
            head += f"\n※ 지난번에 {prev_c}자로 너무 많이 뺐다. 이번에는 문장을 더 남겨 목표 약 {p['goal_c']}자에 맞춘다."
        lines.append(f"{head}\n{body}")
    if target_bytes and only is None:
        lines.append(f"[전체 분량] 다 합쳐 {target_bytes}바이트(한글 1자 3바이트, 공백·숫자 1바이트)를 넘지 않게.")
    return "\n\n".join(lines)


def fit_parse(text: str, n: int) -> list[str] | None:
    """<기록k>…(</기록k>) n개를 읽는다. 여는 태그(<기록1>, <기록 1>, [기록1] 등)로 나누고 닫는 태그는 지운다. 모양이 다르면 None."""
    bits = re.split(r"[<\[]\s*기록\s*(\d+)\s*[>\]]", text or "")
    nums = [int(x) for x in bits[1::2]]
    if nums != list(range(1, n + 1)):
        return None
    out = [fit_clean(x) for x in bits[2::2]]
    return out if all(out) else None


def fit_clean(t: str) -> str:
    t = re.sub(r"</\s*기록\s*\d*\s*>|<\s*기록\s*\d*\s*>", "", t or "")
    t = re.sub(r"(?:(?<=^)|(?<=\s))\(\d{1,2}\)\s*", "", t, flags=re.M)  # 남은 문장 번호
    return re.sub(r"\n\s*\n+", "\n", t.strip())


def fit_system() -> str:
    return FIT_RULE + PRINCIPLE + FIT_OUT


def fit_shrink_system(target_bytes: int, text: str) -> str:
    """분량 맞추기 결과(기록 하나 또는 전체)가 몫을 넘을 때: 같은 방식(문장·꾸밈말 덜어내기)으로 지금 글자 수 → 목표 글자 수."""
    from .textutil import count_bytes
    now_b, now_c = max(count_bytes(text), 1), max(len(text), 1)
    goal_c = max(1, round(now_c * target_bytes * 0.95 / now_b))
    return ("다음 학교생활기록부 글의 분량만 줄인다. 새로 쓰지 않고 원문을 덜어내는 편집이다.\n"
            f"- 지금 공백 포함 {now_c}자다. 약 {goal_c}자(약 {now_c - goal_c}자 덜어내기)로 줄인다. 이보다 많이 줄이지 않는다.\n"
            "- 덜 중요한 문장을 통째로 빼는 것을 먼저 하고, 그래도 길 때만 문장 안의 꾸밈말·부연을 덜어낸다. 남는 문장은 원문 글자 그대로 둔다.\n"
            "- 뺀 자리 때문에 어색한 곳만 접속어·어미를 조금 고친다. 새 내용을 넣지 않는다. 줄바꿈 구성과 문체는 그대로 둔다."
            + PRINCIPLE + OUTPUT_RULE)


def build_synth_user(parts: list[dict], target_bytes: int) -> str:
    """parts: [{text, ratio(0~1)}] — 학번·이름 없이 내용과 비율만."""
    lines = []
    for i, p in enumerate(parts, 1):
        pct = round(p["ratio"] * 100)
        approx = round(target_bytes * p["ratio"]) if target_bytes else 0
        head = f"[기록 {i}] 반영 비율 {pct}%" + (f"(약 {approx}바이트)" if approx else "")
        lines.append(f"{head}\n{p['text'].strip()}")
    return "\n\n".join(lines)


# ---------- 프롬프트 목록(v0.17.6) ----------
KINDS = ("synth", "refine", "polish", "trait")  # 종합·생성 / 기록 정제 / 다듬기 / 행특 생성(v0.22)
KIND_NAMES = {"synth": "종합·생성", "refine": "기록 정제", "polish": "다듬기", "trait": "행특 생성"}
BUILTIN = {
    "default": {"name": "종합·생성", "prompt": DEFAULT_TEXT, "example": ""},
    "refine": {"name": "기록 정제", "prompt": REFINE_TEXT, "example": ""},
    "polish": {"name": "다듬기", "prompt": POLISH_TEXT, "example": ""},
    # v0.17.9: 기록 정제 작업에서 고를 수 있는 특수 정리(스캔 PDF 묶음은 처음 값이 스캔 내용 정리)
    "scan": {"name": "스캔 내용 정리", "prompt": SCAN_TEXT, "example": ""},
    "voice": {"name": "음성 스크립트 정리", "prompt": VOICE_TEXT, "example": ""},
    "trait": {"name": "행특 생성", "prompt": TRAIT_TEXT, "example": ""},  # v0.22 행특 설계 카드
}
# v0.17.6~0.17.7의 정제·다듬기 기본(고치지 않고 쓰던 사람은 새 기본으로 바꿔 준다)
LEGACY_BUILTIN = {
    "refine": (
        "다음은 학생의 활동 기록(학생이 쓴 글이나 교사의 메모)이다.\n"
        "- 맞춤법, 띄어쓰기, 어색한 문장을 바로잡고 읽기 쉬운 문단으로 정리한다.\n"
        "- 학생이 실제로 한 활동과 생각을 살리고, 새 내용은 추가하지 않는다."),
    "polish": (
        "다음은 이미 작성된 생기부 문장이다.\n"
        "- 의미와 사실은 그대로 두고, 표현을 자연스럽고 구체적으로 다듬는다.\n"
        "- 중복 표현을 줄이고 문장 사이 흐름을 매끄럽게 한다.\n" + _COMMON),
    "default": LEGACY_TEXT,
}
# 고치지 않고 쓰던 예전 기본 글의 SHA-256(글 전체를 두지 않고 지문만) — 새 기본으로 바꿔 준다
LEGACY_HASH = {
    "default": {"59e066f633ef8bb082fc48ba910b1adf0c07a19d8d9ea3ef60889f13b20f6ad2"},  # v0.17.7~0.18.2(본문 + 빈 줄 + 교사 의견)
}
KIND_DEFAULT = {"synth": "default", "refine": "refine", "polish": "polish", "trait": "trait"}
# 여러 학생에게 같은 자료로 쓰는 일이 많아 종합·생성에는 늘 붙인다(프롬프트를 바꿔도 유지)
SYNTH_RULE = "\n\n[다른 학생과 겹치지 않기]\n- 같은 성취기준·활동 개요를 쓰는 다른 학생들과 표현·문장 구성이 반드시 50% 이상 다르게 작성한다."


def _builtin(pid):
    b = BUILTIN[pid]
    return {"id": pid, "name": b["name"], "prompt": b["prompt"], "example": b["example"], "builtin": True}


def build_library(saved_lib, old_prompts):
    """저장된 목록을 정리한다. 목록이 없으면(처음) 기본 3개 + 예전에 고친 항목별 프롬프트를 옮겨 만든다.
    → (목록, 바뀌었는지)"""
    changed = False
    if not isinstance(saved_lib, list):
        lib = [_builtin(k) for k in BUILTIN]
        for item in ITEMS:
            for op in OPS:
                v = ((old_prompts or {}).get(item) or {}).get(op)
                if not isinstance(v, dict):
                    continue
                pr, ex = str(v.get("prompt") or ""), str(v.get("example") or "")
                d = DEFAULT_PROMPTS[item][op]
                if (pr.strip() and pr.strip() != d["prompt"].strip()) or ex.strip():
                    lib.append({"id": "p" + uuid.uuid4().hex[:10], "name": f"{ITEM_NAMES[item]}·{OP_NAMES[op]} (예전 설정)",
                                "prompt": pr or d["prompt"], "example": ex, "builtin": False})
        return lib, True
    lib, seen = [], set()
    for x in saved_lib:
        if not isinstance(x, dict) or not x.get("id") or x["id"] in seen:
            changed = True
            continue
        seen.add(x["id"])
        e = {"id": str(x["id"]), "name": str(x.get("name") or "이름 없음")[:60], "prompt": str(x.get("prompt") or ""),
             "example": str(x.get("example") or ""), "builtin": x["id"] in BUILTIN,
             # 프롬프트 마법사로 만든 방식(대화/양식)과 이 프롬프트를 쓴 태그 이름
             "made": str(x.get("made") or "")[:10],
             "tags": [str(t)[:40] for t in (x.get("tags") or []) if str(t).strip()][:30] if isinstance(x.get("tags"), list) else []}
        if ((e["id"] in LEGACY_BUILTIN and e["prompt"].strip() == LEGACY_BUILTIN[e["id"]].strip())
                or hashlib.sha256(e["prompt"].strip().encode("utf-8")).hexdigest() in LEGACY_HASH.get(e["id"], ())):  # 고치지 않고 쓰던 예전 기본 → 새 기본
            e["prompt"] = BUILTIN[e["id"]]["prompt"]
            changed = True
        if e["builtin"]:
            e["name"] = BUILTIN[e["id"]]["name"]
        lib.append(e)
    for k in BUILTIN:  # 기본은 늘 있어야 한다
        if k not in seen:
            lib.insert(list(BUILTIN).index(k), _builtin(k))
            changed = True
    return lib, changed


def pick(lib, picks, kind, chosen=None):
    """이번에 쓸 프롬프트: 고른 것 → 이 작업에서 마지막에 고른 것 → 작업별 기본."""
    by = {x["id"]: x for x in lib}
    for pid in (chosen, (picks or {}).get(kind), KIND_DEFAULT.get(kind, "default")):
        if pid and pid in by:
            return by[pid]
    return by.get("default") or _builtin("default")
