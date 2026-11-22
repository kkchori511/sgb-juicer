# 3. 자료 Inbox: 더미 묶음 → 학생 짝 확인 → 정제(가짜 AI) → 보내기 → '이미 보낸 행' 펼침
# 새로 켠 데모에서만 처음부터 끝까지 맞다('과학의 날 행사'가 매칭 대기 상태여야 함).
S = "3"
nav(page, "inbox")
P = "section.panel.active"
page.get_by_role("button", name="과학의 날 행사").first.click(); page.wait_for_timeout(800)
shot(page, "s03_match")
note(S, "학생 매칭 2건 확정", "통과" if "확정 2" in " ".join(page.locator(P).inner_text().split()) else "문제")
page.get_by_role("button", name="다음: AI 정제(선택)").click(); page.wait_for_timeout(800)
page.get_by_role("button", name="정제 안 한 행만 선택 (2)").click(); page.wait_for_timeout(300)
page.get_by_role("button", name="선택 2건 정제").click(); page.wait_for_timeout(800)
shot(page, "s03_refine_confirm")
page.click("#modalOk"); page.wait_for_timeout(9000)
shot(page, "s03_refined")
note(S, "가짜 AI 정제 2건", "통과" if page.locator(P).inner_text().count("(시험용 AI 결과)") >= 2 else "문제")
page.get_by_role("button", name="다음: 보내기 검토").click(); page.wait_for_timeout(800)
page.get_by_role("button", name="2명 2건 보내기").click(); page.wait_for_timeout(800)
if modal_open(page):
    page.click("#modalOk"); page.wait_for_timeout(1200)
shot(page, "s03_sent")
note(S, "보내기 완료", "통과" if "보낸 기록 2명 / 2건" in page.locator(P).inner_text() else "문제")
w = page.evaluate(r"""() => { const ths=[...document.querySelectorAll('section.panel.active th')]; const r={};
  ths.forEach(t=>r[t.innerText.replace(/\s/g,'')]=[Math.round(t.getBoundingClientRect().width), Math.round(t.getBoundingClientRect().height)]); return r }""")
note(S, "이미 보낸 행: 보낸 내용 칸 넓음", "통과" if w.get("보낸내용", [0])[0] > 600 else "문제", str(w))
note(S, "이미 보낸 행: '원본 위치' 머리 한 줄", "통과" if w.get("원본위치", [0, 99])[1] < 50 else "문제", "글자가 세로로 한 자씩 꺾임" if w.get("원본위치", [0, 0])[1] >= 50 else "")
