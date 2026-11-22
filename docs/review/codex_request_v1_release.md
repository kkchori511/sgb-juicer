# Codex 요청: v1.0.0 정식 릴리스 (v0.36.0 다음)

Claude 사용량이 다 되어 여기서부터 Codex가 이어 합니다. 먼저 `AGENTS.md`, `docs/HANDOFF.md`('이어서 할 수 있는 일' 맨 위), `docs/review/codex_v1_final.md` §6, `docs/WINDOWS_TEST.md` §7을 읽어 주세요.

## 지금 상태

- 저장소 `D:\data\projects\sgb-juicer`, 브랜치 `feature/v0.19`, 최신 릴리스 **v0.36.0**(1.0 후보, exe·SHA-256 붙음, 커밋 118c8a0).
- Codex 최종 확인 1~5번은 v0.36.0에서 고침. 백엔드 `tests/run_all.py` 50/50(시험 중 인터넷 막힘), 화면 `scripts/e2e_windows.py` 81/81.
- 사용자가 v0.36.0 exe를 직접 확인 중(옛 버전 → [지금 업데이트], 스캔 'CLOVA만 이용(기본)', 기록 → 마감 → 내보내기). **결과를 듣기 전에는 v1.0.0 태그를 만들지 마세요.**

## 할 일

1. **'베타' 표시 지우기**(`git grep -n -i "베타\|beta"`로 다시 확인):
   - `README.md` 1줄 제목 '(베타)', 6줄 근처 1.0 미만 설명
   - `app/main.py` 15줄(인트로 버전), 123줄(창 제목)
   - `app/web/app.js` 607줄 근처 앱 정보 창
   - `app/web/index.html` 15줄 상단 '베타' 칩, 525~526줄 앱 정보
   - `.github/workflows/build-windows.yml` 108줄 근처 자동 릴리스 제목
   - `app/web/style.css` `.beta` 규칙(121줄 근처)은 칩을 지우면 정리
   - **건드리지 말 것**: `app.js` 2949줄 근처 모델 ID의 `beta` 처리, `.nav-badge`(1331줄, 다른 용도), `docs/review` 옛 기록
2. **지원 범위와 수동 복구 안내**를 README와 사용 안내(index.html 도움말)에 짧게:
   - 지원: Windows exe(자동 업데이트), Mac은 소스 실행. Qwen만 읽기는 시험 기능.
   - 업데이트 실패 때: 자료 폴더(`생기부착즙기_데이터`)는 그대로 두고, 릴리스 페이지에서 exe를 다시 내려받아 바꿔 끼움. 자료가 이상하면 설정 › 백업·자료에서 '업데이트전' 백업으로 복원.
3. **버전 1.0.0**: `app/__init__.py` VERSION = "1.0.0", README 변경 기록 맨 위에 1.0.0 줄.
4. **시험**: `.\.venv\Scripts\python tests\run_all.py`(50개 모두 통과해야 함), `node --check app/web/app.js`.
5. **데모를 사용자에게 보여 주고 확인받기**(AGENTS.md 규칙):
   `$env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS="--remote-debugging-port=9222"; .\.venv\Scripts\python scripts\demo_mac.py` — 상단에 '베타' 칩이 없는지, 앱 정보 창, 창 제목.
6. **사용자가 '진행'이라고 하면** 커밋 → push → 태그 → 릴리스:
   ```
   git push origin feature/v0.19
   git tag v1.0.0; git push origin v1.0.0
   & "C:\Program Files\GitHub CLI\gh.exe" release create v1.0.0 --title "v1.0.0" --notes-file <노트 파일> --verify-tag
   ```
   - 태그 push **바로 뒤** release create(늦으면 workflow가 노트 없는 릴리스를 먼저 만듦). Git Bash에는 `gh`가 PATH에 없으니 위 전체 경로를 쓰세요.
   - 빌드 확인: `gh.exe run list --limit 3`, 끝나면 `gh.exe api repos/kkchori511/sgb-juicer/releases/tags/v1.0.0 --jq '.assets[].digest'`로 exe와 sha256이 붙었는지.
   - 커밋 끝줄 규칙은 git log의 앞 커밋을 따르세요.
7. **HANDOFF 갱신**: 최신 릴리스 v1.0.0, 남은 것(Mac 소스 확인, 실제 CLOVA·Qwen 시험은 사용자가 직접, 다음 버전 '마감 ■ 크게')을 적고 커밋·push.

## 지켜 주세요

- 한국어로 짧게. 커밋·push·태그·릴리스는 **사용자가 말할 때만**.
- 진짜 학생 자료·실제 자료 폴더 금지(시험은 `SGB_DATA_DIR` 임시 폴더). 바깥으로 보내는 것(텔레그램·웹 폼·맞춤법 사이트)은 매번 먼저 묻기. API 키를 화면·기록·커밋에 남기지 않기.
- 자료 형식(DB 표·열)은 바꾸지 않습니다(이번 일에는 필요 없음).
- 그림·아이콘은 그리지 않습니다.
