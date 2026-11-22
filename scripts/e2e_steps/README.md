# 화면 점검(e2e)과 더미 자료 — 다른 컴퓨터에서 꺼내 쓰기

화면을 넘기며 모든 부분을 점검하는 로직과 더미 자료는 모두 이 저장소에 있다. 진짜 학생 자료는 쓰지 않는다.

## 들어 있는 것

| 무엇 | 어디 |
| --- | --- |
| 더미 자료 만들기(가짜 학생·명렬·기록·태그·Inbox 묶음·성취기준·시험용 엑셀·스캔 OCR 예시) + 가짜 AI·가짜 OCR로 앱 켜기 | `scripts/demo_mac.py` (켤 때마다 임시 폴더에 새로 만듦, 실제 자료 폴더는 안 건드림) |
| 스캔 OCR 더미(가짜 손글씨 학습지 PDF, 저장해 둔 CLOVA·Qwen 응답, 정답 글) | `tests/fixtures/ocr_dummy/` |
| 백엔드 시험용 자료(옛 형식 sqlite, 스캔 예시 PDF) | `tests/fixtures/` |
| 화면 점검 실행기(데모 창에 붙어 조작·캡처, 'null' 글자·콘솔 오류 찾기, 1536×794 화면 흉내) | `scripts/e2e_windows.py` |
| 화면별 점검 단계 12개(현황판·명렬·Inbox·태그별·항목별·프롬프트·내보내기·설정·유의 사항·OCR·사용 안내·창 크기) | `scripts/e2e_steps/s01~s12` |
| 버튼·표시 모양 점검(고치지 않고 모으기만) | `scripts/e2e_tools/shape_audit.py` |

캡처와 결과(`e2e/`)는 커밋하지 않는다. 돌릴 때마다 새로 생긴다.

## Windows에서 돌리기

```powershell
git pull
py -3.12 -m venv .venv                       # 처음 한 번
.\.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
# 1) 데모를 원격 조종 포트와 함께 켜 둔다(창이 뜸, 따로 둔 PowerShell 또는 백그라운드)
$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS = "--remote-debugging-port=9222"
.\.venv\Scripts\python scripts\demo_mac.py
# 2) 다른 창에서 전체 점검(새로 켠 데모에서, 약 4분)
.\.venv\Scripts\python scripts\e2e_windows.py            # 전부(1~12)
.\.venv\Scripts\python scripts\e2e_windows.py 10 12      # 몇 단계만
.\.venv\Scripts\python scripts\e2e_windows.py exec scripts\e2e_tools\shape_audit.py
```

- 결과: 화면에 `요약: {'통과': 81, '문제': 0, '건너뜀': 4, '실패': 0}`. 자세히는 `e2e/results.tsv`, 콘솔 오류 `e2e/console.log`, 'null' 글자 `e2e/bad_text.log`, 캡처 `e2e/*.png`.
- 건너뜀 4개는 운영체제 파일 창(저장·열기)이라 자동으로 못 누르는 것과 데모에 없는 자료다.
- 점검이 데모 자료를 바꾸므로 **다시 돌릴 때는 데모를 껐다 켠다**. 점검 스크립트에서 데모의 sqlite를 직접 열지 않는다(Windows 파일 잠김).
- 새 기능을 넣으면 `demo_mac.py`에 그 기능용 더미 자료를, `e2e_steps/`에 점검 단계를 더한다.
- 백엔드 시험: `.\.venv\Scripts\python tests\run_all.py`(50개, 인터넷 막고 실행).

## Mac에서

`python3 scripts/demo_mac.py`로 같은 더미 자료가 든 창을 띄워 손으로 확인한다. `e2e_windows.py`는 WebView2(Windows) 원격 조종 포트를 쓰므로 Windows 전용이다.
