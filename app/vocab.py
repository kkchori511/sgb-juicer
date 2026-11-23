"""세특 어휘(v0.31): 과목별 세특 AI 변환 때 '골라 쓸 만한 표현' 목록을 지침에 붙인다.

- 설정(config.json)의 subject_vocab = {"on": bool, "verbs": [...], "evals": [...]}. 없으면 기본 목록(사용자 제공 '세특어휘.xlsx', 2026-11-20).
- 기본 목록은 겹치는 단어를 하나로 합치고, 오타('나물라데 없다' → '나무랄 데 없다')를 고치고,
  대원칙(지어내지 않기)과 헷갈리는 '지어내다'는 뺐다.
- 엑셀: 머리글에 '동사' / '평가'가 있으면 그 열로, 머리글이 없으면 1·2열 = 활동 동사, 3열 = 평가·정도 표현(원본 파일 모양).
"""
import copy

from . import config
from .db import DbError

DEFAULT_VERBS = [
    "가려내다", "기술하다", "약술하다", "열거하다", "정의하다", "진술하다", "짝짓다", "찾아내다", "구별하다", "부인하다",
    "설명하다", "예시하다", "예측하다", "의역하다", "일반화하다", "전환하다", "추론하다", "추정하다", "계산하다", "관계 짓다",
    "발견하다", "변용하다", "변환하다", "예증하다", "재구조화시키다", "조종하다", "준비하다", "풀어내다", "개발하다", "고안하다",
    "구체화하다", "도출하다", "병합하다", "분류하다", "생산하다", "설계하다", "세분하다", "도식하다", "변별하다", "구분하다",
    "식별하다", "분리하다", "환원시키다", "창조하다", "편집하다", "형성하다", "간추리다", "감지하다", "결론짓다", "고려하다",
    "비교하다", "서술하다", "요약하다", "입증하다", "주장하다", "총평하다", "타당화하다", "토론하다", "판단하다", "평가하다",
    "표준화하다", "해석하다", "수정하다", "재정리하다", "조직하다",
]
DEFAULT_EVALS = [
    "우월하다", "우수하다", "탁월하다", "뛰어나다", "빼어나다", "두드러지다", "도드라지다", "드러나다", "뚜렷하다", "우뚝하다",
    "돋보이다", "남다르다", "특출나다", "출중하다", "걸출하다", "훌륭하다", "칭찬할 만하다", "나무랄 데 없다", "완벽하다", "아름답다",
    "위대하다", "매우", "대단히", "퍽", "무척", "굉장히", "상당히", "꽤", "몹시", "많이", "지나치게", "더없이", "더할 수 없이",
    "더할 나위 없이", "아주", "한없이", "자못", "적잖게", "제법", "극히", "참으로", "적절히", "잘", "효과적으로", "탁월하게",
    "우수하게", "뛰어나게", "뚜렷하게", "돋보이게",
]
DEFAULT = {"on": True, "verbs": DEFAULT_VERBS, "evals": DEFAULT_EVALS}
MAX_WORDS = 300


def _clean(words):
    out, seen = [], set()
    for w in words or []:
        w = " ".join(str(w or "").split())[:30]
        if w and w not in seen:
            seen.add(w)
            out.append(w)
    return out[:MAX_WORDS]


def normalize(d):
    if not isinstance(d, dict):
        raise DbError("세특 어휘 형식이 아닙니다.")
    return {"on": bool(d.get("on", True)), "verbs": _clean(d.get("verbs")), "evals": _clean(d.get("evals"))}


def load():
    d = config.load().get("subject_vocab")
    try:
        return normalize(d) if d else copy.deepcopy(DEFAULT)
    except DbError:
        return copy.deepcopy(DEFAULT)


def is_default():
    return not config.load().get("subject_vocab")


def save(d):
    new = normalize(d)
    config.save({"subject_vocab": new})
    return new


def reset():
    config.save({"subject_vocab": None})
    return load()


def rule():
    """세특(subject) AI 지침에 붙일 글. 꺼져 있거나 비어 있으면 빈 글."""
    v = load()
    if not v["on"] or not (v["verbs"] or v["evals"]):
        return ""
    parts = ["\n\n[세특 어휘 — 교사가 정한 표현 목록, 자연스러울 때만 골라 씀]",
             "- 아래 표현은 세특 문장에 쓸 만한 어휘다. 문맥에 맞을 때만 골라 쓰고, 억지로 넣거나 같은 표현을 되풀이하지 않는다.",
             "- 활동 동사는 자료에 적힌 행위를 나타낼 때만 쓴다. 이 동사로 자료에 없는 행위를 지어내지 않는다(대원칙 우선).",
             "- 평가·정도 표현은 자료에 드러난 수준에 맞게 쓰고, 사실보다 부풀리지 않는다."]
    if v["verbs"]:
        parts.append("<활동 동사>\n" + ", ".join(v["verbs"]) + "\n</활동 동사>")
    if v["evals"]:
        parts.append("<평가·정도 표현>\n" + ", ".join(v["evals"]) + "\n</평가·정도 표현>")
    return "\n".join(parts)


def from_xlsx(path):
    from . import roster
    try:
        rows = [[("" if c is None else str(c).strip()) for c in r] for r in roster.table_rows(path)]
    except Exception:
        raise DbError("파일을 열지 못했습니다. xlsx 또는 csv 파일인지 확인해 주세요.")
    rows = [r for r in rows if any(r)]
    if not rows:
        raise DbError("엑셀에 단어가 없습니다.")
    head = rows[0]
    vcols = [i for i, h in enumerate(head) if "동사" in h]
    ecols = [i for i, h in enumerate(head) if "평가" in h or "정도" in h]
    if vcols or ecols:
        body = rows[1:]
    else:  # 머리글 없음: 1·2열 = 활동 동사, 3열 = 평가·정도 표현(원본 '세특어휘.xlsx' 모양). 1열뿐이면 모두 동사
        body = rows
        width = max(len(r) for r in rows)
        vcols, ecols = ([0, 1], [2]) if width >= 3 else ([0], [1] if width == 2 else [])
    pick = lambda cols: [r[i] for r in body for i in cols if i < len(r) and r[i]]
    new = {"on": True, "verbs": _clean(pick(vcols)), "evals": _clean(pick(ecols))}
    if not (new["verbs"] or new["evals"]):
        raise DbError("엑셀에서 단어를 찾지 못했습니다.")
    return new


def to_xlsx(d, path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "세특 어휘"
    ws.append(["활동 동사", "평가·정도 표현"])
    for i in range(max(len(d["verbs"]), len(d["evals"]))):
        ws.append([d["verbs"][i] if i < len(d["verbs"]) else None, d["evals"][i] if i < len(d["evals"]) else None])
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 20
    wb.save(path)
