# 6. 프롬프트: 목록, 📚 예시 탭, [📚 예시 목록에서 불러오기], 마법사 💬 Chat / 📋 Form 열고 닫기
S = "6"
P = "section.panel.active"
nav(page, "prompts"); page.wait_for_timeout(800)
shot(page, "s06_prompts")
page.click("#prExPickBtn"); page.wait_for_timeout(800)
note(S, "[📚 예시 목록에서 불러오기] 창", "통과" if sheet_open(page) else "문제"); shot(page, "s06_expick"); close_all(page)
page.locator("[data-prtab=example]").click(); page.wait_for_timeout(800)
note(S, "📚 예시 탭 목록", "통과" if page.locator("#exNewBtn").is_visible() else "문제"); shot(page, "s06_examples")
note(S, "직접 만든 예시 이름 파란 글씨", "건너뜀", "데모에 직접 만든 예시 없음")
page.locator("button.tab-btn:not([data-prtab=example])").first.click(); page.wait_for_timeout(500)
for which in ("💬 Chat", "📋 Form"):
    page.click("#prWizBtn"); page.wait_for_timeout(600)
    page.locator(f"button:visible:has-text('{which}')").first.click(); page.wait_for_timeout(900)
    tag = "chat" if "Chat" in which else "form"
    shot(page, f"s06_wiz_{tag}")
    border = page.evaluate("() => getComputedStyle(document.querySelector('#sheetBox')).borderColor")
    note(S, f"마법사 {which} 열림·인디고", "통과" if sheet_open(page) and border == "rgb(79, 70, 229)" else "문제", border)
    if tag == "chat":
        r = page.evaluate("""() => { const box=document.querySelector('#sheetBox'); const s=box.querySelector('.cw-body').getBoundingClientRect();
          const b=[...box.querySelectorAll('button')].find(x=>x.innerText.trim()==='보내기').getBoundingClientRect(); return [Math.round(b.bottom), Math.round(s.bottom)] }""")
        note(S, "Chat [보내기] 버튼이 스크롤 없이 보임", "통과" if r[0] <= r[1] else "문제", f"보내기 아래 끝 {r[0]} / 보이는 칸 아래 끝 {r[1]}(창 {page.viewport_size or ''})")
    close_all(page); page.wait_for_timeout(400)
    note(S, f"마법사 {which} 닫힘", "통과" if not sheet_open(page) else "문제")
