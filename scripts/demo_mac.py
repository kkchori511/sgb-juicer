"""Mac 확인용 데모: 임시 폴더에 더미 자료를 넣고 앱 창을 띄운다.

- 실제 자료 폴더는 건드리지 않는다(SGB_DATA_DIR을 새 임시 폴더로).
- AI는 시험용 가짜 응답을 쓴다(키·크레딧 쓰지 않음, 결과에 '(시험용 AI 결과)' 표시).
- 실행: .venv/bin/python scripts/demo_mac.py
- Windows exe가 아니라 같은 소스를 Mac에서 돌리는 확인용이다. 업데이트 교체 등 Windows 전용 동작은 다를 수 있다.
"""
import json
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = tempfile.mkdtemp(prefix="sgb-demo-")
os.environ["SGB_DATA_DIR"] = DATA
os.chdir(ROOT)
sys.path.insert(0, ROOT)

from app import openrouter  # noqa: E402


_JUDGE = [0]
def _fake_chat(key, model, system, user, privacy_block=False, history=None):
    # 3초 걸리는 척: 여러 건 동시 처리와 [바로 중지]를 볼 수 있게(중지하면 바로 끊김)
    if openrouter._cancel.wait(3):
        raise openrouter.Cancelled()
    if "[유사도 채점]" in system:  # 스킬화 검증 채점: 첫 시도는 못 넘고 다음부터 통과하는 척
        _JUDGE[0] += 1
        return ("{\"내용\": 80, \"문체\": 85, \"차이\": \"마지막 평가 문장이 빠짐\"}" if _JUDGE[0] <= 2 else "{\"내용\": 97, \"문체\": 95, \"차이\": \"\"}"), 0.0001
    if "[목표]" in user and "<목표 결과>" in user:
        return ("<요청 분석>\n- 요청: 더 짧게 | 분류: 반영 | 규칙: 약 150자, 3문장 안팎\n"
                "- 요청: 원문의 발표 내용도 넣어 | 분류: 일반화 | 규칙: 원문에 발표·토론 활동이 있으면 빠뜨리지 않고 넣는다\n"
                "- 요청: 세 번째 문장 빼 | 분류: 제외 | 규칙: 이 학생 글의 특정 문장을 가리켜 다른 학생에게 옮길 수 없음\n</요청 분석>\n"
                "<프롬프트>\n# 역할\n(시험용 스킬화 프롬프트) 학생 활동 자료를 관찰자 시점으로 3문장 안팎 한 문단에 씁니다.\n</프롬프트>"), 0.0003
    if "OCR 결과를 합치는 도우미" in system:  # [두 결과 조합하기]: CLOVA 글에 Qwen 쪽 끝 줄을 더하고 없는 낱말 하나를 섞음(⚠ 표시 확인용)
        import re as _re
        a = _re.search(r"\[CLOVA\]\n(.*?)\n\n\[Qwen\]", user, _re.S)
        text = (a.group(1) if a else "") + "\n(시험용) 선생님 확인 도장"
        return json.dumps({"text": text}, ensure_ascii=False), 0.0009
    if "그림을 볼 수 없습니다" in system:  # OCR 보정 제안: 차이마다 번갈아 CLOVA/AI 쪽
        import re as _re
        ids = _re.findall(r"^\[(d\d+)\]", user, _re.M)
        return json.dumps({"items": [{"id": d, "pick": "clova" if i % 2 == 0 else "ai", "reason": "(시험용) 문맥상 자연스러움"} for i, d in enumerate(ids)]}, ensure_ascii=False), 0.0001
    if history:  # 대화 누적(이어 고치기): 앞 결과를 조금 고친 척
        prev = history[-1][1].replace("(시험용 AI 결과) ", "")
        return f"(시험용 AI 결과·{len(history) + 1}단계) " + prev[: max(30, len(prev) - 15)], 0.0006
    return "(시험용 AI 결과) 수업 활동에 적극적으로 참여하며 탐구 과정을 꼼꼼히 기록함. " + user.replace("\n", " ")[:100], 0.0004


openrouter.chat = _fake_chat
openrouter.balance = lambda key: 4.25

from app.api import Api  # noqa: E402


def ok(r, what=""):
    if not r.get("ok"):
        raise SystemExit(f"더미 자료 넣기 실패({what}): {r.get('error')}")
    return r


# v0.35 하이브리드 OCR: 더미 학습지(tests/fixtures/ocr_dummy)의 실제 응답을 돌려주는 가짜 CLOVA·AI(호출·비용 없음)
_FX = os.path.join(ROOT, "tests", "fixtures", "ocr_dummy")


def _fake_ocr():
    from app import ocr, ocr_vision
    clova = json.load(open(os.path.join(_FX, "clova_raw.json"), encoding="utf-8"))
    qwen = [json.load(open(os.path.join(_FX, f"qwen_p{i}.json"), encoding="utf-8"))["result"] for i in (1, 2)]
    ocr.call_once = lambda url, secret, data, name, lang: (time.sleep(2), clova)[1]
    real_render = ocr_vision.render_png
    which = {}

    def render(pdf, page, mask=0.0, width=ocr_vision.RENDER_WIDTH):
        png = real_render(pdf, page, mask, width)
        which[png] = page
        return png

    def read(key, model, png, post=None):
        time.sleep(3)
        q = qwen[which.get(png, 0) % 2]
        return {"lines": q["lines"], "figures": q["figures"], "cost": 0.0015, "provider": "(시험용)", "model": model}
    ocr_vision.render_png = render
    ocr_vision.read_page = read


_fake_ocr()


def seed():
    api = Api()
    ok(api.save_config({"openrouter_key": "sk-demo-not-real", "setup_done": True, "clova_url": "https://demo.invalid/general", "clova_secret": "demo-not-real"}), "설정")
    year = time.localtime().tm_year if time.localtime().tm_mon >= 3 else time.localtime().tm_year - 1
    ok(api.create_year(year, "homeroom"), "학년도")
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}), "담임반")["id"]
    math = ok(api.add_group({"kind": "subject", "name": "공통수학1", "semester": 1}), "과목")["id"]
    sci = ok(api.add_group({"kind": "subject", "name": "통합과학", "semester": 1}), "과목")["id"]
    club = ok(api.add_group({"kind": "club", "name": "과학탐구반"}), "동아리")["id"]
    names = ["김철수", "이영희", "박민수", "최가람", "정다은", "한별", "윤서준", "강하늘"]
    mine = [{"student_no": f"203{i + 1:02d}", "name": n} for i, n in enumerate(names)]
    others = [{"student_no": "20401", "name": "오민지"}, {"student_no": "20402", "name": "장하준"}, {"student_no": "20403", "name": "서지우"}]
    ok(api.roster_apply(hr, mine, "add"), "명렬")
    ok(api.roster_apply(math, mine[:5] + others, "add"), "명렬")
    ok(api.roster_apply(sci, mine[3:] + others[:2], "add"), "명렬")
    ok(api.roster_apply(club, mine[:3] + others[1:], "add"), "명렬")
    ok(api.set_section(math, ["20301", "20302", "20303", "20401"], "A반"), "수업")
    ok(api.set_section(math, ["20304", "20305", "20402", "20403"], "B반"), "수업")
    ok(api.finish_setup(), "설정 끝")
    tag = {}
    for t in ("독서", "탐구", "발표", "협업", "봉사"):
        tag[t] = ok(api.add_tag(t), "태그")["id"]

    def rec(g, item, sno, content, title="", date="", tags=(), kind=None):
        data = {"content": content, "title": title, "date": date, "tag_ids": [tag[t] for t in tags]}
        if kind:
            data["kind"] = kind
        return ok(api.add_record(g, item, sno, data), "기록")["id"]

    c1 = rec(hr, "career", "20301", "『나는 왜 과학자가 되었나』를 읽고 연구자의 끈기에 감명받았다는 감상문을 씀.", "진로 독서", f"{year}-03-15", ["독서"])
    c2 = rec(hr, "career", "20301", "생명공학 연구원의 하루를 조사해 발표함. 유전자 편집 윤리 문제를 스스로 제기함.", "직업 탐색 발표", f"{year}-05-02", ["발표"])
    c3 = rec(hr, "career", "20302", "진로 체험 보고서를 제출하고 관심 학과의 교육과정을 정리함.", "진로 체험", "", ["탐구"])
    # v0.19 결과 묶음·기록 확정: 20301 진로 — 1회는 변환 결과로 확정, 2회는 결과 2개(미확정), 20302는 원문 그대로 확정
    ok(api.ai_record(c1), "AI 변환")
    ok(api.apply_candidate([x for x in ok(api.student_view(hr, "career", "20301"), "보기")["records"] if x["id"] == c1][0]["candidates"][0]["id"]), "확정")
    ok(api.ai_record(c2), "AI 변환"); ok(api.ai_record(c2), "AI 변환")
    ok(api.confirm_record(c3, "진로 체험 보고서를 제출하고 관심 학과의 교육과정을 정리함."), "확정")
    rec(hr, "career", "20303", "진로 독서 감상문을 쓰고 친구들과 나눔.", "진로 독서", "", ["독서"])
    rec(hr, "career", "20304", "진로 캠프에 참가해 팀 과제를 이끎.", "진로 캠프", "", ["협업"])
    rec(hr, "autonomy", "20301", "학급 회장으로서 학급 회의를 주도하고 의견을 조율함.", kind="existing")
    rec(hr, "autonomy", "20305", "학급 환경 정리 봉사에 꾸준히 참여함.", "환경 정리", "", ["봉사"])
    rec(hr, "behavior", "20306", "친구의 어려움을 먼저 살피고 돕는 모습을 보임.", tags=["협업"])
    for sno in ("20301", "20302", "20303", "20304", "20401", "20402"):
        rec(math, "subject", sno, f"수학 교양서를 읽고 함수의 활용 사례를 정리해 발표함({sno}).", "수학 독서", "", ["독서"])
    rec(math, "subject", "20305", "이차함수 그래프 탐구 보고서를 작성함.", "탐구 보고서", "", ["탐구"])
    rec(sci, "subject", "20304", "물질의 규칙성 실험을 설계하고 결과를 분석함.", "실험 설계", "", ["탐구"])
    rec(sci, "subject", "20401", "과학 기사 읽기 활동에서 핵심 개념을 정리함.", "과학 기사", "", ["독서"])
    rec(club, "club", "20302", "동아리 탐구 주제를 정하고 역할을 나눔.", "주제 정하기", "", ["협업"])
    rec(club, "club", "20403", "실험 장비 정리를 맡아 성실히 수행함.")
    # 태그 AI 변환 확인용: '봉사' 태그가 자율활동에만 여러 명(시험 → 확정 → 나머지 변환 → 검토·반영)
    for sno, txt in (("20301", "학교 주변 쓰레기 줍기 봉사에 참여하고 분리배출 안내문을 만들었다."),
                     ("20302", "도서관 책 정리 봉사를 하면서 분류 번호 붙이는 방법을 배웠다."),
                     ("20303", "급식실 배식 도우미를 하며 질서 지키기 캠페인을 같이 했다."),
                     ("20304", "복도 게시판 정리 봉사를 맡아 친구들과 역할을 나누어 했다."),
                     ("20306", "교실 화분 가꾸기 봉사를 하며 물 주는 당번표를 만들었다.")):
        rec(hr, "autonomy", sno, txt, "교내 봉사", "", ["봉사"])
    # 최종안·마감: 완료(초록)·마감(파랑)·입력 중(노랑)이 섞여 보이게
    ok(api.edit_final(hr, "career", "20303", "진로 독서 감상문을 쓰고 친구들과 생각을 나누며 관심 분야를 넓힘."), "최종안")
    ok(api.set_closed(hr, "career", "20303", True), "마감")
    ok(api.edit_final(hr, "career", "20304", "진로 캠프에서 팀 과제를 이끌며 협업 능력을 보임."), "최종안")
    ok(api.edit_final(math, "subject", "20302", "수학 교양서를 읽고 함수의 활용 사례를 발표함."), "최종안")
    ok(api.set_closed(math, "subject", "20302", True), "마감")
    ok(api.set_active(sci, ["20402"], False), "비활성")
    # 1·2학기 합산 과목(공통수학1 + 공통수학2, 1500바이트 함께 씀): 검토·내보내기 '1·2학기 합쳐 보기' 확인용
    math2 = ok(api.add_group({"kind": "subject", "name": "공통수학2", "semester": 2}), "과목")["id"]
    ok(api.roster_apply(math2, mine[:5] + others, "add"), "명렬")
    ok(api.update_group(math2, {"pair_id": math, "pair_total": 1500}), "합산 연결")
    ok(api.edit_final(math, "subject", "20301", "다항식의 연산 원리를 친구에게 설명하며 개념을 정리함."), "최종안")
    ok(api.edit_final(math2, "subject", "20301", "경우의 수 단원에서 문제를 스스로 만들어 풀이를 발표함."), "최종안")
    # 활동 개요(자율·진로)와 성취기준(공통수학1): 기록 없는 학생 '기준 자료로 생성' 확인용
    ok(api.outline_save(hr, "autonomy", "3월 학급 자치회 구성 — 학급 규칙 정하기, 1인 1역할 정하기\n4월 과학의 날 행사 — 탐구 포스터 제작, 발표\n6월 학교 축제 — 학급 부스 기획·운영\n9월 학교폭력 예방 캠페인 — 표어 만들기, 캠페인 활동", "붙여넣기"), "활동 개요")
    ok(api.outline_save(hr, "career", "3월 진로 검사 — 흥미·적성 검사 후 결과 해석\n5월 진로 체험의 날 — 관심 직업 탐색 보고서 작성\n10월 학과 탐색 — 관심 학과 교육과정 조사·발표", "붙여넣기"), "활동 개요")
    ok(api.standards_save(math, "[10공수1-01-01] 다항식의 사칙연산을 할 수 있다.\n[10공수1-01-02] 항등식의 성질과 나머지정리를 이해한다.\n성취수준 A: 다항식의 연산을 능숙하게 하고 원리를 설명한다.\n성취수준 C: 간단한 다항식의 연산을 할 수 있다.", "붙여넣기"), "성취기준")
    # 자료 Inbox 묶음 하나(보내기 전)
    bid = ok(api.inbox_create("과학의 날 행사", hr, "autonomy"), "Inbox")["id"]
    src = ok(api.inbox_source_text(bid, "학번\t이름\t내용\n20301\t김철수\t과학의 날 포스터 제작에 참여함.\n20306\t한별\t과학 퀴즈 진행을 도움."), "Inbox")
    ok(api.inbox_import(bid, {"structure": "multi", **src["opts"]}), "Inbox")
    ok(api.inbox_create("공통수학1 세특(나이스 파일)", math, "subject"), "Inbox")
    # 한 문서 → 여러 학생: 학번 없는 모둠 보고서를 3명에게(역할 메모), ② 매칭 단계에서 보임
    sb = ok(api.inbox_create("", hr, "autonomy"), "Inbox")["id"]
    ok(api.inbox_shared(sb, {"text": "기후 위기 대응 방안을 조사한 모둠 보고서. 우리 지역의 탄소 배출 통계를 분석하고 학교에서 실천할 수 있는 방안 세 가지를 제안하였다.",
                             "label": "기후 위기 모둠 보고서", "date": f"{year}-05-10",
                             "picks": [{"student_no": "20301", "role": "자료 조사"}, {"student_no": "20302", "role": "통계 분석"}, {"student_no": "20303", "role": "발표"}]}), "공동 문서")
    # 보낸 묶음도 그대로 남아 [+ 자료 더 넣기]로 이어 보낼 수 있음(1회 보냄 상태)
    ok(api.inbox_stage(sb, "review"), "공동 문서")
    ok(api.inbox_send(sb), "공동 문서")
    # 프롬프트 목록: 이름이 긴 프롬프트도 칸 안에서 줄바꿈되는지(마법사 태그가 밀려나지 않는지) 확인용
    ok(api.prompt_save({"name": "2학년 3반 진로활동 세특 — 학생 관심 분야와 탐구 과정 중심으로 길게 정리하는 프롬프트", "prompt": "학생의 관심 분야와 탐구 과정을 중심으로 정리하세요.", "example": "", "made": "대화", "tags": ["탐구", "발표"]}), "프롬프트")
    ok(api.prompt_save({"name": "동아리 짧게", "prompt": "동아리 활동을 짧게 정리하세요.", "example": "", "made": "양식"}), "프롬프트")
    _demo_xlsx(year, names)
    _demo_scan(api, hr, year)
    return year


def _demo_scan(api, hr, year):
    """하이브리드로 이미 읽은 예시 묶음(더미 학습지 2쪽) — 차이 검토 화면을 바로 볼 수 있게."""
    from app import db, ocr
    from app.inbox import Inbox
    bid = ok(api.inbox_create("과학 활동지(하이브리드 OCR 예시)", hr, "career"), "Inbox")["id"]
    ib = Inbox(db.open_year(year))
    ib.scan_set(bid, os.path.join(_FX, "dummy.pdf"), "더미학습지.pdf")
    ib.scan_set_mode(bid, "hybrid", 1, 0.14, "qwen/qwen3-vl-235b-a22b-instruct")
    clova = json.load(open(os.path.join(_FX, "clova_raw.json"), encoding="utf-8"))
    ib.scan_store(bid, "clova", pages=[ocr.image_lines(im) for im in clova["images"]])
    for i in (0, 1):
        q = json.load(open(os.path.join(_FX, f"qwen_p{i + 1}.json"), encoding="utf-8"))["result"]
        ib.scan_store(bid, "ai", ai_page=(i, {"lines": q["lines"], "figures": q["figures"], "cost": 0.0015, "provider": "(시험용)", "model": "qwen/qwen3-vl-235b-a22b-instruct"}))
    # 두 결과가 크게 다른 쪽(통째로 검토 → [두 결과 조합하기])을 볼 수 있는 묶음
    b3 = ok(api.inbox_create("표가 많은 활동지(통째로 검토 예시)", hr, "career"), "Inbox")["id"]
    ib.scan_set(b3, os.path.join(_FX, "dummy.pdf"), "표많은학습지.pdf")
    ib.scan_set_mode(b3, "hybrid", 1, 0.14, "qwen/qwen3-vl-235b-a22b-instruct")
    big_clova = "학번: 10399 이름: 가나다\n탐구 주제 | 빛의 세기와 광합성\n가설 | 빛이 셀수록 기포가 많다\n결과 | 1단계 3개 2단계 7개 3단계 12개\n결론 | 빛이 셀수록 광합성이 활발함"
    big_qwen = "탐구 주제 빛 세기 광합성\n결과 표\n단계 기포\n1 3\n2 7\n3 12\n느낀 점 실험이 재미있었다"
    lines = lambda t: {"lines": [{"text": x, "box": None} for x in t.split("\n")]}
    # 두 쪽 모두 통째로 검토: [통째로 검토 쪽 한꺼번에 조합하기 (2쪽)]를 볼 수 있게
    big_clova2 = "실험 과정 | 수조에 수초를 넣고 전등 거리를 바꿈\n측정 | 1분 동안 기포 수\n자료 해석 | 거리가 가까울수록 기포 증가\n더 알고 싶은 점 | 빛의 색에 따른 차이"
    big_qwen2 = "실험 과정 수초 전등\n거리 기포\n10cm 12\n20cm 7\n30cm 3\n궁금한 점 빛 색깔"
    qline = lambda t: {"lines": [{"text": x, "unreadable": False} for x in t.split("\n")], "figures": [], "cost": 0.0015, "provider": "(시험용)", "model": "qwen/qwen3-vl-235b-a22b-instruct"}
    ib.scan_store(b3, "clova", pages=[lines(big_clova), lines(big_clova2)])
    ib.scan_store(b3, "ai", ai_page=(0, qline(big_qwen)))
    ib.scan_store(b3, "ai", ai_page=(1, qline(big_qwen2)))
    # 아직 읽지 않은 스캔 PDF 묶음: 파일 창 없이 '읽는 방식' 화면과 [OCR 시작](가짜 응답)을 볼 수 있게
    b2 = ok(api.inbox_create("스캔 PDF(읽기 전 예시)", hr, "career"), "Inbox")["id"]
    ib.scan_set(b2, os.path.join(_FX, "dummy.pdf"), "스캔_더미학습지_2쪽.pdf")


def _demo_xlsx(year, names):
    """시험용 엑셀(가짜 학생): 나이스 내려받기 형식 세특(시트 3개)과 반별 명렬(시트 2개). 자료 폴더 안 '시험용 엑셀'에 만든다."""
    from openpyxl import Workbook

    out = os.path.join(DATA, "시험용 엑셀")
    os.makedirs(out, exist_ok=True)
    wb = Workbook()
    wb.active.title = "안내"
    wb.active.append(["시험용 가짜 파일입니다."])
    ws = wb.create_sheet("과목별세부능력및특기사항")
    ws.append(["학년도", "학기", "학년", "학생개인번호", "과목", "과목코드", "반/번호", "성명", "학적변동_x000D_\n구분", "세부능력 및 특기사항", "영재·발명교육 기록사항"])
    for i, n in enumerate(names[:5]):
        ws.append([str(year), "1", "2", f"{year}0001{i:02d}", "공통수학1", "0003000012", f"3/{i + 1}", n,
                   "자퇴" if i == 2 else "재학", f"다항식의 연산 단원에서 {n} 학생이 스스로 질문을 만들어 풀이함.", ""])
    wb.create_sheet("빈 시트")
    wb.save(os.path.join(out, "나이스_세특_시험용.xlsx"))
    wb = Workbook()
    wb.active.title = "1반"
    for r in (["학번", "이름"], ["20101", "가나다"], ["20102", "라마바"]):
        wb.active.append(r)
    ws = wb.create_sheet("2반")
    for r in (["학번", "이름"], ["20201", "사아자"], ["20202", "차카타"]):
        ws.append(r)
    wb.save(os.path.join(out, "반별_명렬_시험용.xlsx"))
    import shutil
    shutil.copyfile(os.path.join(_FX, "dummy.pdf"), os.path.join(out, "스캔_더미학습지_2쪽.pdf"))


if __name__ == "__main__":
    y = seed()
    print(f"데모 자료: {DATA} ({y}학년도)", flush=True)
    print(f"시험용 엑셀: {os.path.join(DATA, '시험용 엑셀')}", flush=True)
    from app.main import main

    sys.argv = [os.path.join(ROOT, "run.py")]  # pywebview는 실행 파일 폴더를 앱 루트로 본다(app/web/index.html 찾기)
    main()
