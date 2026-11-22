# 11. 사용 안내: 목차 12·13장, 🔍 기능 찾기 '꾸러미'
S = "11"
P = "section.panel.active"
nav(page, "guide"); page.wait_for_timeout(800)
t = page.locator(P).inner_text()
note(S, "목차 12. 쓰기 도우미, 13. 설정 꾸러미", "통과" if "12. 쓰기 도우미" in t and "13. 설정 꾸러미" in t else "문제")
page.locator(f"{P} input[type=search], {P} input[type=text]").first.fill("꾸러미"); page.wait_for_timeout(800)
vis = page.evaluate("() => [...document.querySelectorAll('section.panel.active h2, section.panel.active h3')].filter(h=>h.getClientRects().length).map(h=>h.innerText)")
note(S, "기능 찾기 '꾸러미' → 그 말이 든 장만", "통과" if any(v.startswith("13.") for v in vis) and len(vis) <= 3 else "문제", str(vis))
shot(page, "s11_guide_search")
page.locator(f"{P} input[type=search], {P} input[type=text]").first.fill("")
