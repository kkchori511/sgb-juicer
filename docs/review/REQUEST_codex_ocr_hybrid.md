# 요청: OCR 하이브리드(CLOVA + Qwen) 추가분 검토 (Codex)

## 검토 대상

- 브랜치 `feature/ocr-hybrid`, 비교 기준 `feature/v0.19` — `git diff feature/v0.19..feature/ocr-hybrid` (커밋 4개)
- 계획·결정: `docs/plan/ocr-hybrid.md` (사용자 확정 결정 1~7, 0단계 실제 호출 기록)
- 주요 파일: `app/ocr_vision.py`(Qwen 호출·머리글 가림), `app/ocr_compare.py`(비교·최종 글·보정 제안), `app/ocr.py`(CLOVA 줄 위치), `app/inbox.py`(scan_store·scan_decide 등), `app/api.py`(inbox_scan_ocr 스레드, inbox_scan_suggest), `app/scan.py`(render_crop), `app/web/app.js`(renderScanStart, scanStatusBar, showDiffReview, showOriginal), `app/web/style.css`, `app/web/index.html`(설정 카드·도움말·보안 탭)
- 시험: `tests/test_ocr_hybrid.py`, 전체는 `.venv/bin/python tests/run_all.py`

## 꼭 볼 것

1. **버그·데이터 손실**: 두 엔진 스레드가 같은 묶음 meta를 저장할 때 덮어쓰기(경쟁), 중지·실패·다시 실행 때 상태, 옛 묶음(sc["ocr"]만) 호환, 페이지 수·인덱스 어긋남, 크게 다른 쪽·빈 쪽·실패한 쪽 처리, 고른 것(review)이 OCR 다시 하기 뒤에 남는지.
2. **API 한 번만**(결정 4): 어떤 경로로든 CLOVA나 Qwen을 다시 부르는 곳이 없는지(검토·고르기·다시 묶기·화면 새로 그리기·[Qwen으로도 읽어 비교하기]·실패한 쪽 다시 읽기 범위).
3. **개인정보**(결정 7): Qwen에 보내는 그림의 머리글 가림이 늘 적용되는지(AI만 + 동의 없이 가림 0 차단), 학습 차단·ZDR이 늘 켜지는지, 보정 제안에 이름·학번이 새는 경로(문맥 before/after, 명렬에 없는 이름 등), 로그·오류 문구에 키가 나오는지.
4. **비교 정확성**: `compare`의 원문 위치 계산(EQUIV로 글자 수가 바뀌는 ℃), 묶기(MERGE_GAP), 가린 줄 제외, 그림 속 글자 판정, 그림 설명 위치, `resolve`에서 겹치는 바꾸기, `_apply`의 공백 정리.
5. **대원칙(지어내지 않기)**: Qwen 프롬프트·보정 제안 프롬프트가 없는 글자를 만들 여지, ⚠ 판정(`parse_fix` new)이 맞는지.
6. **화면**: escHtml 누락(XSS — 모델 답·OCR 글이 innerHTML로 들어가는 곳), 버튼 상태, 좁은 창, 키보드(1·2·↑↓), 페이지 빼기 상태가 원본 보기 창과 목록에서 맞는지.
7. **문구**: 그림 읽는 쪽은 'Qwen', 글 AI 보정은 'AI 제안'으로 구분되어 있는지(사용자 지시), 보안 탭·도움말이 실제 동작과 맞는지.

## 지킬 것

- **코드를 고치지 말고** 검토만. 결과는 `docs/review/codex_ocr_hybrid.md`에: 심각도(높음/중간/낮음), 파일:줄, 재현 방법 또는 근거, 고칠 방향. 확인하지 못한 것도 적기.
- 시험 실행(`tests/run_all.py`)은 해도 됨. **실제 API(OpenRouter·CLOVA) 호출 금지**, Chrome 실행 금지, 텔레그램 등 외부 전송 금지.
- 끝나면 결과 파일 맨 위에 '검토 끝' 한 줄.
