# 요청: OCR 하이브리드 고친 부분 재검토 (Codex)

- 앞 검토: `docs/review/codex_ocr_hybrid.md` (H1~H3, M1~M11, L1~L3)
- 고친 커밋: `20452df` — `git show 20452df`, 전체는 `git diff feature/v0.19..feature/ocr-hybrid`
- 사용자 결정: H2 = 가림 0%는 하이브리드·Qwen만 모두 '전송 동의'가 있어야 허용 / M11 = 보낸 뒤 응답이 끊기면 자동 재전송하지 않음(연결 전 실패·429·5xx만 한 번 더)
- 새 시험: `tests/test_ocr_hybrid_review.py`, 전체 `.venv/bin/python tests/run_all.py`

## 볼 것

1. 앞 검토 17개가 **실제로** 고쳐졌는지 항목마다 '고침 / 일부 / 안 고침'과 근거.
2. 고치면서 **새로 생긴 문제**(회귀): 특히 CLOVA 묶음별 저장(`ocr_pdf_pages` on_chunk, `scan_store` dict 합치기, `scan_engines_done`), `scan_set_mode`의 `_scan_refresh`, 스캔 meta 잠금(`_scan_locked`), `compare`의 `_widen`·`a_ws/ai_ws`, `redact`·`fix_user`, 화면의 queue/gen/shown(showDiffReview), 원본 보기 그림 설명.
3. 앞 검토에서 못 본 남은 문제.

## 지킬 것

- **코드를 고치지 말고** 검토만. 결과는 `docs/review/codex_ocr_hybrid_2.md`에 심각도(높음/중간/낮음), 파일:줄, 재현·근거, 고칠 방향. 맨 위 첫 줄은 '검토 끝'.
- 실제 API(OpenRouter·CLOVA) 호출 금지, Chrome 실행 금지, 외부 전송 금지. 시험 실행은 해도 됨.
