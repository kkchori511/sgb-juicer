"""Mac 확인용 데모: 임시 폴더에 더미 자료를 넣고 앱 창을 띄운다.

- 실제 자료 폴더는 건드리지 않는다(SGB_DATA_DIR을 새 임시 폴더로).
- AI는 시험용 가짜 응답을 쓴다(키·크레딧 쓰지 않음, 결과에 '(시험용 AI 결과)' 표시).
- 실행: .venv/bin/python scripts/demo_mac.py
- Windows exe가 아니라 같은 소스를 Mac에서 돌리는 확인용이다. 업데이트 교체 등 Windows 전용 동작은 다를 수 있다.
"""
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


def _fake_chat(key, model, system, user, privacy_block=False):
    time.sleep(0.8)
    return "(시험용 AI 결과) 수업 활동에 적극적으로 참여하며 탐구 과정을 꼼꼼히 기록함. " + user.replace("\n", " ")[:100], 0.0004


openrouter.chat = _fake_chat
openrouter.balance = lambda key: 4.25

from app.api import Api  # noqa: E402


def ok(r, what=""):
    if not r.get("ok"):
        raise SystemExit(f"더미 자료 넣기 실패({what}): {r.get('error')}")
    return r


def seed():
    api = Api()
    ok(api.save_config({"openrouter_key": "sk-demo-not-real", "setup_done": True}), "설정")
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

    rec(hr, "career", "20301", "『나는 왜 과학자가 되었나』를 읽고 연구자의 끈기에 감명받았다는 감상문을 씀.", "진로 독서", f"{year}-03-15", ["독서"])
    rec(hr, "career", "20301", "생명공학 연구원의 하루를 조사해 발표함. 유전자 편집 윤리 문제를 스스로 제기함.", "직업 탐색 발표", f"{year}-05-02", ["발표", "탐구"])
    rec(hr, "career", "20302", "진로 체험 보고서를 제출하고 관심 학과의 교육과정을 정리함.", "진로 체험", "", ["탐구"])
    rec(hr, "career", "20303", "진로 독서 감상문을 쓰고 친구들과 나눔.", "진로 독서", "", ["독서"])
    rec(hr, "career", "20304", "진로 캠프에 참가해 팀 과제를 이끎.", "진로 캠프", "", ["협업"])
    rec(hr, "autonomy", "20301", "학급 회장으로서 학급 회의를 주도하고 의견을 조율함.", kind="existing")
    rec(hr, "autonomy", "20305", "학급 환경 정리 봉사에 꾸준히 참여함.", "환경 정리", "", ["봉사"])
    rec(hr, "behavior", "20306", "친구의 어려움을 먼저 살피고 돕는 모습을 보임.", tags=["협업"])
    for sno in ("20301", "20302", "20303", "20304", "20401", "20402"):
        rec(math, "subject", sno, f"수학 교양서를 읽고 함수의 활용 사례를 정리해 발표함({sno}).", "수학 독서", "", ["독서", "발표"])
    rec(math, "subject", "20305", "이차함수 그래프 탐구 보고서를 작성함.", "탐구 보고서", "", ["탐구"])
    rec(sci, "subject", "20304", "물질의 규칙성 실험을 설계하고 결과를 분석함.", "실험 설계", "", ["탐구"])
    rec(sci, "subject", "20401", "과학 기사 읽기 활동에서 핵심 개념을 정리함.", "과학 기사", "", ["독서"])
    rec(club, "club", "20302", "동아리 탐구 주제를 정하고 역할을 나눔.", "주제 정하기", "", ["협업"])
    rec(club, "club", "20403", "실험 장비 정리를 맡아 성실히 수행함.")
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
    # 자료 인박스 묶음 하나(보내기 전)
    bid = ok(api.inbox_create("과학의 날 행사", hr, "autonomy"), "인박스")["id"]
    src = ok(api.inbox_source_text(bid, "학번\t이름\t내용\n20301\t김철수\t과학의 날 포스터 제작에 참여함.\n20306\t한별\t과학 퀴즈 진행을 도움."), "인박스")
    ok(api.inbox_import(bid, {"structure": "multi", **src["opts"]}), "인박스")
    return year


if __name__ == "__main__":
    y = seed()
    print(f"데모 자료: {DATA} ({y}학년도)", flush=True)
    from app.main import main

    sys.argv = [os.path.join(ROOT, "run.py")]  # pywebview는 실행 파일 폴더를 앱 루트로 본다(app/web/index.html 찾기)
    main()
