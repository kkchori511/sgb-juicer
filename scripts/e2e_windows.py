"""Windows 화면 시험(단계 B): 데모 앱(scripts/demo_mac.py)에 원격 조종 포트로 붙어 조작·캡처한다.

준비(PowerShell):
  $env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9222"
  .\\.venv\\Scripts\\python scripts\\demo_mac.py        # 백그라운드로 켜 둠
실행:
  .\\.venv\\Scripts\\python scripts\\e2e_windows.py [단계 번호 ...]   # 없으면 전부(1~12)
  .\\.venv\\Scripts\\python scripts\\e2e_windows.py eval "자바스크립트"  # 한 줄 실행(탐색용)

- 캡처는 e2e/ 폴더(커밋 안 함). 콘솔 오류는 e2e/console.log에 모은다.
- 바깥으로 글이 나가는 버튼([🔍 맞춤법 검사])은 누르지 않는다.
- 운영체제 파일 창이 뜨는 버튼은 누르지 않고 API로 대신한다.
"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "e2e")
os.makedirs(OUT, exist_ok=True)
ERRORS = []
RESULTS = []  # (단계, 항목, 결과, 메모)


def note(step, item, res, memo=""):
    RESULTS.append((step, item, res, memo))
    print(f"[{step}] {res:4} {item} {memo}", flush=True)


BAD_TEXT = []  # 화면에 보이는 'null'·'undefined' 같은 글자(DOM append에 빈 값이 들어간 흔적)


def shot(page, name, full=False):
    page.wait_for_timeout(300)
    page.screenshot(path=os.path.join(OUT, f"{name}.png"), full_page=full)
    bad = page.evaluate("""() => { const out=[]; const w=document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      while (w.nextNode()) { const t=w.currentNode.nodeValue.trim(); const p=w.currentNode.parentElement;
        if (/^(null|undefined|NaN|\\[object Object\\])$/.test(t) && p && p.getClientRects().length && !p.closest('textarea,script,style,code')) out.push(t+' @ '+p.tagName+'.'+p.className) } return out }""")
    for b in bad:
        BAD_TEXT.append(f"{name}: {b}")
        print(f"[!] 화면에 '{b}' 글자 — {name}", flush=True)


def nav(page, panel, item=None):
    sel = f"button.nav[data-panel='{panel}']" + (f"[data-item='{item}']" if item else "")
    page.click(sel)
    page.wait_for_timeout(500)


def visible_buttons(page, scope="#main, main, body"):
    return page.evaluate("""(scope) => {
      const root = document.querySelector(scope) || document.body;
      return [...root.querySelectorAll('button')].filter(b => b.offsetParent && !b.closest('nav, .side, #side'))
        .map(b => (b.id ? '#' + b.id + ' ' : '') + b.innerText.trim().replace(/\\s+/g, ' ')).filter(Boolean);
    }""", scope)


def modal_open(page):
    return page.evaluate("() => { const m = document.querySelector('#modal'); return !!(m && !m.hidden && m.getClientRects().length > 0) }")


def sheet_open(page):
    return page.evaluate("() => { const m = document.querySelector('#sheet'); return !!(m && !m.hidden && m.getClientRects().length > 0) }")


def close_all(page):
    for _ in range(3):
        if modal_open(page):
            page.click("#modalCancel") if page.locator("#modalCancel:visible").count() else page.click("#modalOk")
            page.wait_for_timeout(200)
        if sheet_open(page):
            d = page.locator("#sheetBox button.btn-dismiss:visible, #sheetBox button:text-is('취소'):visible")
            if d.count():
                d.last.click()
            else:
                page.keyboard.press("Escape")
            page.wait_for_timeout(300)


def connect(p):
    b = p.chromium.connect_over_cdp("http://127.0.0.1:9222")
    page = next(pg for c in b.contexts for pg in c.pages if "index.html" in pg.url)
    page.set_default_timeout(15000)
    page.on("console", lambda m: m.type in ("error",) and ERRORS.append(f"console {m.type}: {m.text}"))
    page.on("pageerror", lambda e: ERRORS.append(f"pageerror: {e}"))
    return b, page


if __name__ == "__main__":
    with sync_playwright() as p:
        b, page = connect(p)
        if len(sys.argv) > 2 and sys.argv[1] == "eval":
            print(json.dumps(page.evaluate(sys.argv[2]), ensure_ascii=False, indent=1))
        elif len(sys.argv) > 2 and sys.argv[1] == "shot":
            shot(page, sys.argv[2])
        elif len(sys.argv) > 2 and sys.argv[1] == "exec":  # 시험 조각 파일 실행(page, 도우미 함수 사용 가능)
            code = open(sys.argv[2], encoding="utf-8").read()
            exec(compile(code, sys.argv[2], "exec"), {**globals(), "page": page})
        else:
            steps = [s for s in sys.argv[1:]] or [str(i) for i in range(1, 13)]
            sdir = os.path.join(ROOT, "scripts", "e2e_steps")
            for s in steps:
                f = next((os.path.join(sdir, n) for n in sorted(os.listdir(sdir)) if n.startswith(f"s{int(s):02d}_")), None)
                if not f:
                    print(f"단계 {s} 파일 없음"); continue
                try:
                    close_all(page)
                    exec(compile(open(f, encoding="utf-8").read(), f, "exec"), {**globals(), "page": page})
                except Exception as e:  # 한 단계가 실패해도 다음 단계로
                    note(s, "단계 실행", "실패", repr(e)[:300])
                    shot(page, f"fail_s{int(s):02d}")
            with open(os.path.join(OUT, "results.tsv"), "w", encoding="utf-8") as fp:
                fp.write("\n".join("\t".join(map(str, r)) for r in RESULTS))
            with open(os.path.join(OUT, "console.log"), "w", encoding="utf-8") as fp:
                fp.write("\n".join(ERRORS))
            c = {k: sum(1 for r in RESULTS if r[2] == k) for k in ("통과", "문제", "건너뜀", "실패")}
            with open(os.path.join(OUT, "bad_text.log"), "w", encoding="utf-8") as fp:
                fp.write("\n".join(BAD_TEXT))
            print(f"\n요약: {c} / 콘솔 오류 {len(ERRORS)}건 / 화면 'null' 글자 {len(BAD_TEXT)}건")
        if ERRORS:
            print("\n".join(ERRORS))
