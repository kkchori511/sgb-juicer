# 9. 유의 사항: 📋 유의 사항 탭이 먼저, 🛡️ 보안 / 개인정보 탭(빨강·노랑·초록 칸)
S = "9"
nav(page, "notice"); page.wait_for_timeout(600)
tabs = page.evaluate("() => [...document.querySelectorAll('section.panel.active [data-ntab]')].filter(b=>b.getClientRects().length).map(b=>[b.innerText, b.classList.contains('active')])")
note(S, "유의 사항 탭이 먼저", "통과" if tabs and "유의 사항" in tabs[0][0] and tabs[0][1] else "문제", str(tabs))
shot(page, "s09_notice")
page.locator("[data-ntab=security]").first.click(); page.wait_for_timeout(500); shot(page, "s09_security")
bgs = page.evaluate("() => [...document.querySelectorAll('[data-ntab-content=security] *')].map(e=>getComputedStyle(e).backgroundColor)")
note(S, "보안 탭 빨강·노랑·초록 칸", "통과" if {"rgb(253, 236, 234)", "rgb(255, 248, 225)", "rgb(233, 247, 238)"} <= set(bgs) else "문제")
