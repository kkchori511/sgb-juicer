# Codex 최종 검토 요청 (v0.7.0 → 1.0 전)

## 대상
- 저장소: /Users/kc/projects/sgb-juicer (브랜치 feature/v0.7, 릴리스 v0.7.0)
- 요구사항: docs/REQUIREMENTS.md (A~J절), 화면 구성: docs/design/LAYOUT.md, 이전 UX 검토: docs/design/codex_ux_review.md
- 코드: app/*.py (api.py가 화면↔파이썬 경계), app/web/app.js·index.html·style.css, tests/*.py, .github/workflows/build-windows.yml
- 사용자: 고등학교 교사(초보 포함), Windows exe(pywebview), 자료는 exe 옆 폴더에 평문 저장(사용자가 결정한 사항)

## 검토해 주세요
1. **요구사항 대비 구현**: REQUIREMENTS.md의 항목(특히 J절 확정 규칙)이 빠졌거나 다르게 구현된 곳
2. **개인정보·보안**: AI(OpenRouter)에 학번·이름이 가는 경로가 있는지(인박스 OCR·붙여넣기, 기록, 종합, 성취기준, 다듬기 등 모든 AI 호출), 키가 로그·오류·화면에 새는 곳, 업데이트 내려받기 검증(SHA-256, URL 제한), 외부 링크 열기
3. **자료 손실·무결성**: SQLite 트랜잭션 누락, 마감 잠금 우회, 명렬 다시 넣기·담당 삭제·학년도 삭제·복원·이동·되돌리기·인박스 보내기에서 자료가 사라지거나 중복될 수 있는 경우, 동시 실행(두 창) 위험
4. **버그**: 예외 처리, 경계 조건(빈 값, 큰 파일, 한글 경로), JS 상태 꼬임(화면 전환, 학년도 전환, 보관 학년도 편집 막기)
5. **초보 교사 사용성**: 순차 흐름에서 막히는 곳, 헷갈리는 문구·용어 불일치, 오류 문구가 다음 행동을 알려 주는지
6. **1.0 전에 꼭 고칠 것 / 나중에 해도 될 것** 구분

## 결과 형식
- 파일: /Users/kc/projects/sgb-juicer/docs/review/codex_final_review.md (한국어)
- 항목마다: 우선순위(높음/중간/낮음), 분류(요구사항/보안/자료/버그/사용성), 위치(파일:줄), 문제, 재현·근거, 고치는 방안
- 맨 앞에 요약(1.0 전에 고칠 것 목록), 맨 끝에 확인하지 못한 범위

## 지켜 주세요
- 코드와 다른 파일은 고치지 마세요(결과 파일만 작성).
- Chrome 실행, 외부 전송(텔레그램 등), git push는 하지 마세요.
- 필요하면 `.venv/bin/python tests/test_*.py`로 테스트를 돌려도 됩니다(자료는 임시 폴더에 생김).
