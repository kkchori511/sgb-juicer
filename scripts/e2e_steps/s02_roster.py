# 2. 명렬 / 담당 관리: 담당 추가 창 열고 닫기, 학생 표 가운데 정렬, 클립보드에서 추가 창
S = "2"
nav(page, "roster")
P = "section.panel.active"
shot(page, "s02_roster")
page.click("#addGroupBtn"); page.wait_for_timeout(500)
op = sheet_open(page) or modal_open(page)
shot(page, "s02_addgroup")
note(S, "[+ 담당 추가] 창 열림", "통과" if op else "문제")
close_all(page)
note(S, "담당 추가 창 닫힘", "통과" if not (sheet_open(page) or modal_open(page)) else "문제")
tabs = page.locator(f"{P} .gtab")
for i in range(tabs.count()):
    tabs.nth(i).click(); page.wait_for_timeout(300)
shot(page, "s02_last_tab")
tabs.first.click(); page.wait_for_timeout(300)
al = page.evaluate("""() => { const t=document.querySelector('section.panel.active table'); if(!t) return null;
  const th=t.querySelector('th'); const td=t.querySelector('tr:nth-child(2) td:nth-child(2)');
  return [getComputedStyle(th).textAlign, td && getComputedStyle(td).textAlign] }""")
note(S, "학생 표 머리·내용 가운데 정렬", "통과" if al and all(a == "center" for a in al) else "문제", str(al))
page.get_by_role("button", name="📋 클립보드에서 추가").click(); page.wait_for_timeout(600)
op = sheet_open(page) or modal_open(page)
shot(page, "s02_clip")
note(S, "[📋 클립보드에서 추가] 창 열림", "통과" if op else "문제(클립보드 비어 안내만일 수 있음)")
close_all(page)
