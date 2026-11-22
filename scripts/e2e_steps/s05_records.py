# 5. 항목별 기록(진로 20301, 세특 공통수학2): AI 변환 → 확정 → 이어 붙이기 → 최종안, 기재 유의어, 분량 맞추기 창, 마감/해제, Alt+↓, 1·2학기 합산 안내
# [🔍 맞춤법 검사]는 누르지 않는다(바깥 사이트로 글이 감).
S = "5"
P = "section.panel.active"
nav(page, "records", "career"); page.wait_for_timeout(800)
page.locator(f"{P} button:visible:has-text('AI 변환'):not(:has-text('선택'))").first.click(); page.wait_for_timeout(600)
page.click("#modalOk"); page.wait_for_timeout(6000)
page.locator(f"{P} button:visible:has-text('✔ 이걸로 확정')").first.click(); page.wait_for_timeout(1200)
note(S, "AI 변환 → [✔ 이걸로 확정]", "통과" if "확정 기록 2건" in page.locator(P).inner_text() else "문제")
page.get_by_role("button", name="이어 붙이기 → 최종안").click(); page.wait_for_timeout(1000)
shot(page, "s05_join")
page.locator("#sheetBox button:has-text('최종안으로 넣기')").click(); page.wait_for_timeout(1000)
fin = page.locator(f"{P} textarea").last
note(S, "이어 붙이기 → 최종안", "통과" if fin.input_value().strip() else "문제")
fin.click(); page.keyboard.press("Control+End"); page.keyboard.type(" Zoom으로 발표하고 유튜브에 올림.")
page.locator(P).first.click(position={"x": 5, "y": 5}); page.wait_for_timeout(1200)
shot(page, "s05_banned")
note(S, "기재 유의어 경고·형광펜", "통과" if "기재 유의어 2개" in page.locator(P).inner_text() else "문제")
t = page.locator(P).inner_text()
note(S, "확정 기록 묶음 요약 '최신'", "문제" if "최신: 📄 원문" in t or "최신: 원문" in t else "통과", "확정된 기록은 원문이 맨 앞이라 '최신: 원문'으로 보임")
page.get_by_role("button", name="비중으로 분량 맞추기").click(); page.wait_for_timeout(800)
note(S, "[비중으로 분량 맞추기] 창·제목 체크", "통과" if "기록 제목을 넣어 시작" in page.locator("#sheetBox").inner_text() else "문제")
shot(page, "s05_ratio"); close_all(page)
page.locator(f"{P} button:visible:has-text('■ 마감')").last.click(); page.wait_for_timeout(1000)
lock = page.evaluate("() => [...document.querySelectorAll('section.panel.active textarea')].every(t=>t.readOnly||t.disabled)")
note(S, "[■ 마감] → 편집 잠김", "통과" if lock else "문제"); shot(page, "s05_closed")
page.get_by_role("button", name="마감 해제").click(); page.wait_for_timeout(800)
note(S, "[마감 해제]", "통과" if page.get_by_role("button", name="마감 해제").count() == 0 else "문제")
n0 = page.locator(P).inner_text().split("\n")[0]
page.locator("body").click(position={"x": 700, "y": 130}); page.keyboard.press("Alt+ArrowDown"); page.wait_for_timeout(1000)
n1 = page.locator(P).inner_text().split("\n")[0]
note(S, "Alt+↓ 다음 학생", "통과" if n0 != n1 else "문제", f"{n0} → {n1}")
nav(page, "records", "subject"); page.wait_for_timeout(1000)
shot(page, "s05_subject")
note(S, "세특 1·2학기 합산 안내", "통과" if "이번 학기 남은" in page.locator(P).inner_text() else "문제")
