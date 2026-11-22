# 7. 내보내기: 공통수학2(여러 반) 'xlsx 시트' 선택, 1·2학기 합쳐 보기, 클립보드 복사, xlsx(파일 창 대신 API 행 → export.write_xlsx → openpyxl 확인)
import subprocess
S = "7"
P = "section.panel.active"
nav(page, "export"); page.wait_for_timeout(1000)
note(S, "여러 반 과목에서 'xlsx 시트' 선택 보임", "통과" if page.locator("#expSplit").is_visible() else "문제")
page.click("#expCopyBtn"); page.wait_for_timeout(1000)
clip = subprocess.run(["powershell", "-NoProfile", "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"], capture_output=True, text=True, encoding="utf-8").stdout
note(S, "클립보드 복사(머리글 + 8명)", "통과" if len(clip.strip().splitlines()) == 9 else "문제", f"{len(clip.strip().splitlines())}줄")
sys.path.insert(0, ROOT)
from app import export
from openpyxl import load_workbook
gid = int(page.locator("#expSlot").input_value().split(":")[0])
rows = page.evaluate(f"() => window.pywebview.api.export_preview({gid}, 'subject', false, 'no')")["rows"]
for split in (False, True):
    path = os.path.join(OUT, f"s07_export_split{int(split)}.xlsx")
    export.write_xlsx(path, rows, "full", "공통수학2", split)
    wb = load_workbook(path)
    info = [(ws.title, ws.max_row - 1, any(str(c.fill.fgColor.rgb).endswith("FFF2B3") for r in ws.iter_rows() for c in r if c.fill.fill_type)) for ws in wb.worksheets]
    note(S, f"xlsx {'반별로 나누기' if split else '한 시트'}: 시트 이름·행 수·노란색", "통과" if sum(i[1] for i in info) == 8 and all(i[2] for i in info) else "문제", str(info))
note(S, "xlsx 저장 파일 창", "건너뜀", "운영체제 저장 창은 자동으로 못 누름 — 같은 함수(export.write_xlsx)로 대신 확인")
page.locator(f"{P} label:has-text('1·2학기 합쳐 보기')").click(); page.wait_for_timeout(1000)
shot(page, "s07_combined")
st = page.evaluate("() => ['expCopyBtn','expXlsxBtn'].map(id=>{const b=document.getElementById(id); return [b.disabled, getComputedStyle(b).backgroundColor]})")
note(S, "1·2학기 합쳐 보기(두 학기 최종안·합계)", "통과" if "153/1500" in page.locator(P).inner_text() else "문제")
note(S, "합쳐 보기 때 꺼진 [xlsx 저장]이 꺼진 모양", "통과" if st[1][1] == st[0][1] else "문제", f"복사 {st[0]} / xlsx {st[1]} — xlsx는 꺼져도 초록 그대로")
page.locator(f"{P} label:has-text('1·2학기 합쳐 보기')").click(); page.wait_for_timeout(500)
