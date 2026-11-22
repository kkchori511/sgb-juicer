# 12(4-4). 창 크기: 1366×768, 좁은 가로(1100 → [📝 기록 / 📄 최종안] 탭), 세로 화면(최종안 위·기록 아래). CDP 화면 흉내로 확인
S = "12"
nav(page, "records", "career"); page.wait_for_timeout(800)
cdp = page.context.new_cdp_session(page)
CLIP = """() => [...document.querySelectorAll('section.panel.active button')].filter(b=>b.getClientRects().length && (b.getBoundingClientRect().right > innerWidth+1 || b.scrollWidth > b.clientWidth+2)).map(b=>b.innerText.trim().slice(0,18))"""
TABS = "() => [...document.querySelectorAll('button')].filter(b=>b.getClientRects().length && /📝 기록|📄 최종안/.test(b.innerText)).length"
for name, w, h, s, want_tabs in (("1366x768", 1366, 768, 1, 0), ("narrow1100", 1100, 760, 1.25, 2), ("portrait", 1080, 1700, 1, 0)):
    cdp.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": s, "mobile": False}); page.wait_for_timeout(1000)
    shot(page, f"s12_{name}")
    clip, tabs = page.evaluate(CLIP), page.evaluate(TABS)
    note(S, f"{name}: 버튼 잘림 없음 / 탭 {want_tabs}개", "통과" if not clip and tabs == want_tabs else "문제", f"잘림 {clip} 탭 {tabs}")
if True:
    fin_top = page.evaluate("() => { const f=document.querySelector('#recFinal'), r=document.querySelector('#recRecords'); return f && r ? f.getBoundingClientRect().top < r.getBoundingClientRect().top : null }")
    note(S, "세로 화면: 최종안이 기록 위", "통과" if fin_top else "문제", str(fin_top))
cdp.send("Emulation.setDeviceMetricsOverride", {"width": 1536, "height": 794, "deviceScaleFactor": 1.25, "mobile": False})  # 시험 기본 크기로 되돌림
