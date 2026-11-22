# 1. 현황판: 일정 줄, 카드, 세특 학기 보기, 카드 누르면 표 바뀜, 표에서 학생 누르면 그 기록으로
S = "1"
nav(page, "dashboard")
P = "section.panel.active"
page.wait_for_selector(f"{P} .gcard")
note(S, "일정 줄 보임", "통과" if page.locator(f"{P} .sched-line").is_visible() else "문제")
seg = page.locator(f"{P} .segmented .seg.active").inner_text()
note(S, "세특 학기 보기 처음 값", "통과" if "2" in seg else "문제", f"처음 '{seg}'")
shot(page, "s01_dashboard")
cards = page.locator(f"{P} .gcard")
n = cards.count()
heads = []
for i in range(n):
    cards.nth(i).click(); page.wait_for_timeout(400)
    heads.append(page.locator(f"{P} .dash-tbl-head").first.inner_text().replace("\n", " ")[:60])
    shot(page, f"s01_card{i}")
note(S, f"카드 {n}개 눌러 표 바뀜", "통과" if len(set(heads)) == n else "문제", " | ".join(heads))
page.locator(f"{P} .segmented .seg").first.click(); page.wait_for_timeout(400)
names = page.locator(f"{P} .gcard .g-name").all_inner_texts()
note(S, "1학기 보기로 바꾸면 카드 바뀜", "통과" if "공통수학1" in " ".join(names) else "문제", ",".join(names))
shot(page, "s01_sem1")
cards.first.click(); page.wait_for_timeout(300)
page.locator(f"{P} tr.clickable").first.click(); page.wait_for_timeout(800)
act = page.evaluate("() => { const a=document.querySelector('section.panel.active'); return (a.id||'')+' '+(document.querySelector('button.nav.active')||{}).innerText }")
note(S, "표에서 학생 누르면 기록 화면으로", "통과" if "현황판" not in act else "문제", act.strip())
shot(page, "s01_to_record")
