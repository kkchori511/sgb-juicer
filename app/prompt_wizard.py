"""프롬프트 생성 마법사: 큰 틀(역할·입력 자료·시점과 문체·내용·쓰지 않는 것·틀린/옳은 예시·출력 형태·마지막 점검)을
골라 채우면 프롬프트 글을 만든다. 기본 프롬프트도 이 코드로 만든다(마법사를 기본값 그대로 두면 기본 프롬프트와 같은 글).

spec(모두 선택 사항, 빠지면 기본값):
- school, subject, item: 역할(학교급·과목·항목 이름)
- material: 학생 활동 자료가 무엇인지(괄호 안 설명)
- style, content, banned_extra, extra: [{text, on}] 줄 목록(on이 거짓이면 뺌)
- banned_personal, no_preface: 참/거짓
- banned_words: 쓰지 않을 단어(쉼표로 구분)
- pairs: [{wrong, right}] 틀린/옳은 예시, pair_note: 예시 뒤 설명 줄
- output: 'opinion'(본문 + 빈 줄 + 교사 의견) / 'single'(본문 한 문단만), opinion_n: 교사 의견 문장 수
- recheck, compare: 마지막 점검 단계 넣기
"""
import copy
import re

COMMA_LINE = "쉼표(,)는 꼭 필요한 경우가 아니면 사용하지 않습니다."

DEFAULT_SPEC = {
    "school": "고등학교",
    "subject": "",
    "item": "",
    "material": "수행평가 자료 및 교사 의견",
    "style": [
        "반드시 활동을 관찰한 관찰자 시점으로 작성합니다.",
        "\"학생은\", \"이 학생은\", \"누구는\" 같은 문장의 주어는 모두 생략합니다.",
        "반드시 ~함, ~음 같은 명사형 종결어미를 사용합니다.",
        "과거형으로 쓰지 말고 현재형으로 작성합니다.",
        "서술어로 탁월함, 뛰어남, 확장함, 성장함, 분석함, 추론함, 토론함, 발휘함, 인상적임, 돋보임, 우수함, 제시함, 기여함, 이끌어냄, 설명함, 공유함, 발표함 같은 서술어를 위주로 사용합니다.",
        "한 문장이 너무 짧지 않게 하고, 문장이 자연스럽게 이어지는 줄글로 작성합니다.",
        "같은 문장을 반복해서 사용하지 않습니다.",
        COMMA_LINE,
    ],
    "content": [
        "탐구 결과보다 탐구 과정에 중점을 두어 작성합니다.",
        "잘못한 부분은 언급하지 말고 긍정적인 내용만 서술합니다.",
        "학생의 활동과 개개인의 특징이 드러난 내용은 반드시 포함합니다.",
        "수학 기호나 식, 문장에 오류가 있으면 바르게 고쳐서 씁니다.",
        "LaTeX 문법은 절대 사용하지 않고, 수식은 바로 복사해 붙여 넣을 수 있는 형태로 씁니다.",
    ],
    "banned_personal": True,
    "banned_words": "수행평가, 생활기록부, 정성평가, 이학생, 학생은",
    "banned_extra": [],
    "no_preface": True,
    "extra": [],
    "pairs": [
        {"wrong": "자율주행 차량의 경로 계획의 설계함.",
         "right": "자율주행 차량의 경로 계획에 대해 탐구함. 또는 자율주행 차량 경로 계획에 대해 조사함. 또는 자율주행 차량 경로 계획을 주제로 서술함."},
        {"wrong": "포물선 경로는 곡률이 일정하여 장애물 회피 시 안전하고 부드러운 전환을 가능하게 함.",
         "right": "포물선 경로는 곡률이 일정하여 장애물 회피 시 안전하고 부드러운 전환이 가능하다고 설명함. 또는 가능하다고 서술함. 또는 가능하다고 알려줌."},
        {"wrong": "구조 엔지니어들이 건축물의 안정성을 평가하거나 하중을 예측할 때 구의 방정식을 활용함.",
         "right": "구조 엔지니어들이 건축물의 안정성을 평가하거나 하중을 예측할 때 구의 방정식을 활용함을 알려줌. 또는 활용한다고 서술함. 또는 활용함을 깨달음."},
        {"wrong": "세종대왕에 대해 탐구하였으며 ~~~ 힘든 과정 끝에 한글을 창제함.",
         "right": "세종대왕에 대해 탐구하였으며 ~~~ 힘든 과정 끝에 한글을 창제했음을 알려줌. 또는 창제했다고 서술함. 또는 창제했다고 서술한 점이 인상적임."},
    ],
    "pair_note": True,
    "output": "opinion",
    "opinion_n": "2~3",
    "recheck": True,
    "compare": True,
}
# 줄 목록은 화면에서 켜고 끄며 고칠 수 있게 {text, on}으로
for _k in ("style", "content"):
    DEFAULT_SPEC[_k] = [{"text": t, "on": True} for t in DEFAULT_SPEC[_k]]

STEPS_NOTE = ("분량·예시·성취기준(활동 개요)·다른 학생과 겹치지 않기·이번 추가 요구 사항·출력 형식 규칙은 "
              "실행할 때 앱이 이 프롬프트 뒤에 자동으로 붙입니다.")


def default_spec():
    return copy.deepcopy(DEFAULT_SPEC)


def _lines(items):
    out = []
    for x in items or []:
        if isinstance(x, str):
            t, on = x, True
        else:
            t, on = str((x or {}).get("text") or ""), (x or {}).get("on", True)
        t = t.strip()
        if on and t:
            out.append(t if t.startswith("- ") else "- " + t)
    return out


def _words(s):
    return [w.strip().strip("'\"") for w in re.split(r"[,，、\n]", s or "") if w.strip().strip("'\"")]


def build(spec=None) -> str:
    s = default_spec()
    for k, v in (spec or {}).items():
        if k in s:
            s[k] = v
    school = (s["school"] or "고등학교").strip()
    subject = (s["subject"] or "").strip()
    item = (s["item"] or "").strip()
    material = (s["material"] or "").strip()
    who = f"{school} {subject} 교사" if subject else f"{school} 교사"
    what = f"생활기록부({item})" if item else "생활기록부"
    out = [
        "# 역할",
        f"당신은 대한민국의 유능한 {who}입니다. 주어진 학생 활동 자료{f'({material})' if material else ''}를 참고하여, 아래 작성 지침에 맞게 한글로 관찰자 시점의 {what}를 작성합니다. 작성 지침은 반드시 지켜야 합니다.",
        "학교에서 많이 쓰는 문구를 사용하고, 실제 교사가 쓴 것처럼 자연스럽게 작성합니다. 짧은 문장과 긴 문장을 섞어 자연스러운 글이 되도록 모든 힘을 쏟습니다. 모든 과정은 아래 업무 절차에 따라 단계별로(step by step) 진행합니다.",
        "",
        "# 입력 자료",
        "- 학생 활동 자료: [기록 1], [기록 2]처럼 주어지는 글. 학생이 한 활동 내용이며, 이 내용 자체를 평가하지 말고 그 활동을 진행한 학생을 관찰한 입장에서 평가합니다.",
        "- 예시: [예시] 칸이 주어지면 문체와 글의 분위기만 참고합니다(내용·어휘·문장은 쓰지 않음).",
        "- 분량: [분량] 칸에 주어진 분량을 반드시 지킵니다.",
        "- 추가 작성 지침: [이번 추가 요구 사항]이나 '추가 생활기록부 작성 지침'이 주어지면 이를 가장 먼저 반영합니다.",
        "",
        "# 생활기록부 작성 지침",
    ]
    style = _lines(s["style"])
    if style:
        out += ["## 시점과 문체", *style, ""]
    content = _lines(s["content"])
    if content:
        out += ["## 내용", *content, ""]
    words = _words(s["banned_words"])
    banned = (["- 학생의 이름, 번호 등 개인정보"] if s["banned_personal"] else []) + \
             ([f"- {', '.join(repr_q(w) for w in words)} 같은 단어"] if words else []) + _lines(s["banned_extra"]) + \
             (["- 글 앞뒤의 머리말, 설명, 인사말 등 생활기록부 본문이 아닌 어떤 문구도 쓰지 않습니다."] if s["no_preface"] else [])
    if banned:
        out += ["## 쓰지 않는 것", *banned, ""]
    extra = _lines(s["extra"])
    if extra:
        out += ["## 그 밖의 지침", *extra, ""]

    steps = [
        ("예시 분석", "예시가 주어지면 어휘와 내용은 절대 참고하지 말고 글 형식, 문체, 글의 분위기만 분석합니다. 예시의 어떤 문장도 똑같이 쓰지 않고, 같은 사람이 쓴 것 같은 분위기의 새로운 생활기록부를 작성합니다."),
        ("분량", "주어진 분량을 한글 기준으로 반드시 지킵니다."),
    ]
    write = "작성 지침을 모두 지키며 생활기록부를 작성합니다. 추가 작성 지침이 있으면 가장 먼저 지킵니다. 학생 활동 자료의 내용을 참고하되, 자료의 문장을 그대로 옮기지 말고 관찰자 시점으로 바꿔 씁니다."
    pairs = [p for p in (s["pairs"] or []) if (p.get("wrong") or "").strip() or (p.get("right") or "").strip()]
    for p in pairs:
        if (p.get("wrong") or "").strip():
            write += f"\n    [틀린예시] : {p['wrong'].strip()}"
        if (p.get("right") or "").strip():
            write += f"\n    [옳은예시] : {p['right'].strip()}"
    if pairs and s["pair_note"]:
        write += "\n    위 예시처럼 학생이 한 일(탐구함, 설명함, 서술함, 알려줌, 깨달음)로 끝나게 써서, 자료 속 사실을 학생이 직접 한 일처럼 단정하지 않습니다."
    steps.append(("작성", write))
    steps.append(("첨삭", "작성한 글을 다시 검토하여 틀린 내용이나 매끄럽지 않은 문장을 고치고, 실제 사람이 쓴 것처럼 자연스러운 어휘와 문장으로 다듬습니다. 예시가 있으면 예시와 같은 문체와 형식을 쓰되, 예시의 내용은 절대 참고하지 않습니다."))
    body_no = len(steps)
    final = "앞뒤에 어떤 문구도 없이 다음 순서로만 출력합니다." + f"\n    - {body_no}단계 생활기록부 한 문단(줄바꿈 없음)"
    if s["output"] == "opinion":
        n = (s["opinion_n"] or "2~3").strip()
        steps.append(("교사 의견 덧붙이기", f"{body_no}단계의 글을 바탕으로 교사의 주관적인 의견이 들어간 평가 {n}문장을 작성합니다. 이 문장들은 {body_no}단계 문단 뒤에 한 줄을 비우고 씁니다."))
        final += f"\n    - 빈 줄 1줄\n    - {len(steps)}단계 교사 의견 한 문단(줄바꿈 없음)"
    wq = ", ".join(repr_q(w) for w in words)
    comma = any(COMMA_LINE in l for l in style)
    if words and comma:
        final += f"\n    {wq} 같은 단어는 일체 쓰지 않고, 쉼표(,)는 꼭 필요한 경우가 아니면 쓰지 않습니다."
    elif words:
        final += f"\n    {wq} 같은 단어는 일체 쓰지 않습니다."
    elif comma:
        final += "\n    쉼표(,)는 꼭 필요한 경우가 아니면 쓰지 않습니다."
    steps.append(("최종 출력 형태", final))
    if s["recheck"]:
        steps.append(("최종 재검토", "출력물을 처음부터 끝까지 다시 읽고, 주어와 서술어가 어울리지 않거나 어색한 문장, 작성 지침을 지키지 않은 문장을 고칩니다."))
    if s["compare"]:
        steps.append(("예시와 비교", "예시가 있으면 최종 글과 예시의 문장 구조, 문장 길이, 분위기, 어조를 비교해 같은 사람이 쓴 것 같은지 100점 만점으로 스스로 평가하고, 100점이 될 때까지 고칩니다. 점수와 평가 과정은 출력하지 않습니다."))
    out.append("# 업무 절차")
    for i, (name, text) in enumerate(steps, 1):
        out += [f"{i}. **{name}**: {text}", ""]
    return "\n".join(out).rstrip() + "\n"


def repr_q(w):
    return f"'{w}'"
