"""항목별 기본 프롬프트(임시)와 프롬프트 조립.

기본 프롬프트는 선생님 예시안을 받아 v0.7에서 확정한다. 지금 값은 임시다.
결과 형식·분량·예시 규칙은 코드에 고정하고, 지침과 예시만 사용자가 고친다.
AI에는 학번·이름을 넣지 않는다(부르는 쪽에서 내용만 넘긴다).
"""

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
                    f"다음은 한 학생의 {name} 누가기록 여러 건이다. 이를 종합하여 {name} 기재 문장 하나로 작성한다.\n"
                    f"- 중심 관점: {focus}.\n"
                    "- 기록마다 주어진 분량 비율을 지켜 반영한다.\n"
                    "- 단순 나열이 아니라 활동 → 과정 → 성장이 드러나게 연결한다.\n"
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


OUTPUT_RULE = "\n\n[출력]\n- 결과 본문만 출력한다. 제목, 설명, 따옴표, 머리말을 붙이지 않는다."


def build_system(prompt: str, example: str, target_bytes: int = 0) -> str:
    return (prompt or "").strip() + example_rule(example) + length_rule(target_bytes) + OUTPUT_RULE


def build_synth_user(parts: list[dict], target_bytes: int) -> str:
    """parts: [{text, ratio(0~1)}] — 학번·이름 없이 내용과 비율만."""
    lines = []
    for i, p in enumerate(parts, 1):
        pct = round(p["ratio"] * 100)
        approx = round(target_bytes * p["ratio"]) if target_bytes else 0
        head = f"[기록 {i}] 반영 비율 {pct}%" + (f"(약 {approx}바이트)" if approx else "")
        lines.append(f"{head}\n{p['text'].strip()}")
    return "\n\n".join(lines)
