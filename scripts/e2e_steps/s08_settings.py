# 8. 설정: 탭마다 열기, 글자 크기 150%(넘침 검사), 설정 꾸러미 만들기(파일 이름)·가져오기(파일 창 대신 경로 주입), 백업 → 복원 → 복원 되돌리기
import json as _j
S = "8"
P = "section.panel.active"
nav(page, "settings")
for t in ["conn", "year", "sched", "trait", "vocab", "banned", "font", "data", "about", "suggest"]:
    page.click(f"[data-stab={t}]"); page.wait_for_timeout(400); shot(page, f"s08_tab_{t}")
note(S, "설정 탭 10개 열기", "통과")
page.click("[data-stab=font]")
for _ in range(10):
    if page.evaluate("() => getComputedStyle(document.documentElement).getPropertyValue('--bs').trim()") == "1.5": break
    page.click("#fsUp"); page.wait_for_timeout(200)
OVER = """() => { const out=[]; document.querySelectorAll('section.panel.active *').forEach(e=>{ if(!e.getClientRects().length) return; const s=getComputedStyle(e);
  if (e.children.length===0 && e.scrollWidth > e.clientWidth+2 && !['auto','scroll'].includes(s.overflowX) && e.clientWidth>0 && !['INPUT','SELECT','TEXTAREA'].includes(e.tagName)) out.push(e.tagName+' '+e.innerText.slice(0,20)) }); return out.slice(0,10) }"""
for panel, item in (("records", "career"), ("tagrec", None), ("export", None)):
    nav(page, panel, item); page.wait_for_timeout(1000); shot(page, f"s08_font150_{panel}")
    o = page.evaluate(OVER)
    note(S, f"글자 150%: {panel} 넘침 없음", "통과" if not o else "문제", str(o))
nav(page, "settings"); page.click("[data-stab=font]"); page.click("#fsReset")
page.click("[data-stab=data]"); page.wait_for_timeout(400)
page.click("#shareExportBtn"); page.wait_for_timeout(800)
page.locator("#sheetBox input[type=text]").first.fill("테스트선생"); page.wait_for_timeout(300)
note(S, "꾸러미 파일 이름 '닉네임의 꾸러미_yymmdd.sgbset'", "통과" if "테스트선생의 꾸러미_" in page.locator("#sheetBox").inner_text() else "문제")
shot(page, "s08_share_export"); close_all(page)
note(S, "꾸러미 [파일로 저장…]", "건너뜀", "운영체제 저장 창 — share.build로 같은 파일을 만들어 대신 확인")
data_dir = page.evaluate("() => window.pywebview.api.load_config()")["data_dir"]
os.environ["SGB_DATA_DIR"] = data_dir.strip()
sys.path.insert(0, ROOT)
from app import share
keys = [p["key"] for p in page.evaluate("() => window.pywebview.api.share_catalog()")["catalog"]["prompts"]]
year = int(page.evaluate("() => window.pywebview.api.share_catalog()")["year"])
path = os.path.join(OUT, share.file_name("테스트선생"))
with open(path, "w", encoding="utf-8") as f:
    # 자료 파일(sqlite)은 열지 않는다 — 이 시험 프로세스가 열어 두면 Windows에서 복원이 파일 잠김(WinError 32)으로 실패
    _j.dump(share.build({"prompts": keys, "banned": True, "vocab": True}, None, "테스트선생"), f, ensure_ascii=False)
page.evaluate("(p) => { const a=window.pywebview.api; a.__o=a.share_open; a.share_open=(x)=>a.__o(x||p); }", path)
n0 = len(keys)
page.click("#shareImportBtn"); page.wait_for_timeout(1200); shot(page, "s08_share_import")
page.locator("#sheetBox button:has-text('가져오기'):not(:has-text('…'))").last.click(); page.wait_for_timeout(1500)
if modal_open(page): page.click("#modalOk")
page.evaluate("() => { const a=window.pywebview.api; a.share_open=a.__o; }")
n1 = len(page.evaluate("() => window.pywebview.api.share_catalog()")["catalog"]["prompts"])
note(S, "꾸러미 가져오기(새 이름으로 추가)", "통과" if n0 and n1 == n0 * 2 else "문제", f"프롬프트 {n0} → {n1}")
names = lambda: [t["name"] for t in page.evaluate("() => window.pywebview.api.tags()")["tags"]]
page.click("#backupNowBtn"); page.wait_for_timeout(1500)
page.evaluate("() => window.pywebview.api.add_tag('복원시험')")
page.locator(f"{P} button:visible:has-text('이 백업으로 복원')").first.click(); page.wait_for_timeout(600)
note(S, "복원 확인 창 문구", "문제" if "'확인'를" in page.locator("#modalMsg").inner_text() else "통과", "'확인'를 → '확인'을")
page.fill("#typedConfInp", "확인"); page.click("#modalOk"); page.wait_for_timeout(2500)
note(S, "[지금 백업] → [이 백업으로 복원]", "통과" if "복원시험" not in names() else "문제")
b = page.locator("button:visible:has-text('복원 되돌리기')")
if b.count():
    b.first.click(); page.wait_for_timeout(600); page.fill("#typedConfInp", "확인"); page.click("#modalOk"); page.wait_for_timeout(2500)
note(S, "[복원 되돌리기]", "통과" if "복원시험" in names() else "문제")
