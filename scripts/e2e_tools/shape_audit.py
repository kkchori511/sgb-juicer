# 버튼·표시 모양 점검(고치지 않음, v0.35.3 모양 일관성 점검에 씀). 화면마다 보이는 요소를
# 누를 수 있음/없음 × 알약/둥근 네모/네모로 모아 e2e/shape_audit.json에 쓴다.
# 실행: .\.venv\Scripts\python scripts\e2e_windows.py exec scripts\e2e_tools\shape_audit.py  (새로 켠 데모)
import json as _j
from collections import defaultdict
P = "section.panel.active"
COLLECT = r"""() => {
  const shape = (e) => { const s = getComputedStyle(e), r = e.getBoundingClientRect();
    const rad = parseFloat(s.borderTopLeftRadius) || 0; const h = r.height;
    if (h < 6) return null;
    return rad >= h / 2 - 1.5 ? 'pill' : rad >= 4 ? 'rounded' : 'square'; };
  const visible = (e) => { const r = e.getBoundingClientRect(); return r.width > 4 && r.height > 4 && getComputedStyle(e).visibility !== 'hidden'; };
  const hasBox = (e) => { const s = getComputedStyle(e); const bg = s.backgroundColor; return parseFloat(s.borderTopWidth) > 0 || (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent'); };
  const sig = (e) => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.trim().split(/\s+/).filter(c => !/^(active|on|open|is-|tc\d|st-)/.test(c)).slice(0, 3).join('.') : '');
  const out = [];
  const clickSel = 'button, summary, [role=button], a.btn, label.ocr-mode';
  document.querySelectorAll(clickSel).forEach((e) => {
    if (!visible(e) || e.closest('.sidebar') && !e.matches('.nav-item')) return;
    if (!hasBox(e)) { out.push({ kind: 'click', sig: sig(e), shape: 'nobox', t: e.innerText.trim().slice(0, 18), dis: !!e.disabled }); return; }
    out.push({ kind: 'click', sig: sig(e), shape: shape(e), t: e.innerText.trim().slice(0, 18), dis: !!e.disabled });
  });
  // 누를 수 없는 표시 상자: 테두리나 바탕이 있는 짧은 글자 칩(span/b/div 중 버튼 안에 있지 않은 것)
  document.querySelectorAll('span, b, div, em, small').forEach((e) => {
    if (!visible(e) || e.closest(clickSel) || e.closest('.sidebar')) return;
    const r = e.getBoundingClientRect();
    if (r.height > 46 || r.width > 420 || !hasBox(e) || !e.innerText || e.innerText.trim().length > 40 || e.children.length > 3) return;
    if (getComputedStyle(e).cursor === 'pointer') { out.push({ kind: 'click-span', sig: sig(e), shape: shape(e), t: e.innerText.trim().slice(0, 18) }); return; }
    out.push({ kind: 'label', sig: sig(e), shape: shape(e), t: e.innerText.trim().slice(0, 18) });
  });
  return out;
}"""
agg = defaultdict(lambda: {"n": 0, "screens": set(), "ex": set()})


def grab(screen):
    page.wait_for_timeout(700)
    for x in page.evaluate(COLLECT):
        k = (x["kind"], x["shape"], x["sig"])
        a = agg[k]; a["n"] += 1; a["screens"].add(screen)
        if len(a["ex"]) < 3 and x.get("t"): a["ex"].add(x["t"])


close_all(page)
nav(page, "dashboard"); grab("현황판")
nav(page, "records", "career"); grab("항목별(진로)")
nav(page, "records", "behavior"); grab("항목별(행특)")
nav(page, "tagrec"); page.locator(f"{P} button:visible:has-text('봉사')").first.click(); page.wait_for_timeout(800); grab("태그별")
nav(page, "inbox"); page.locator(f"{P} button:has-text('과학의 날 행사')").first.click(); grab("Inbox 매칭")
page.locator(f"{P} button:has-text('하이브리드 OCR 예시')").first.click(); grab("Inbox OCR")
page.locator(f"{P} button:has-text('읽기 전 예시')").first.click(); grab("Inbox 읽는 방식")
nav(page, "export"); grab("내보내기")
nav(page, "roster"); grab("명렬")
nav(page, "tags"); grab("태그 관리")
nav(page, "prompts"); grab("프롬프트")
nav(page, "standards"); grab("성취기준")
nav(page, "settings")
for t in ["conn", "year", "sched", "trait", "vocab", "banned", "font", "data", "about", "suggest"]:
    page.click(f"[data-stab={t}]"); grab(f"설정:{t}")
nav(page, "guide"); grab("사용 안내")
nav(page, "notice"); grab("유의 사항")
rows = [{"kind": k[0], "shape": k[1], "sig": k[2], "n": v["n"], "screens": sorted(v["screens"]), "ex": sorted(v["ex"])} for k, v in agg.items()]
open(os.path.join(OUT, "shape_audit.json"), "w", encoding="utf-8").write(_j.dumps(rows, ensure_ascii=False, indent=0))
print("모은 종류:", len(rows))
