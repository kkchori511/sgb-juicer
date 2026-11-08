# Codex 재검토 요청 (v0.8.0)

- 저장소: /Users/kc/projects/sgb-juicer (브랜치 feature/v0.8, 릴리스 v0.8.0)
- 1차 검토: docs/review/codex_final_review.md
- 반영 기록: docs/review/fixes_v0.8.md, 회귀 시험: tests/test_review_fixes.py
- 추가 수정: 업데이트 때 실행 잠금 넘겨주기(app/single.py, app/main.py, app/updater.py, app/api.py update_apply)

## 해 주세요
1. 1차 검토의 H01–H13, M01–M10, L02, 결정 27이 실제로 고쳐졌는지 같은 재현 방법으로 다시 확인
2. 이번 수정으로 새로 생긴 문제(회귀) 찾기: 특히 최종안 자동 저장(flushFinal)과 채택·마감·학생 전환의 순서, 백업·복원 준비/교체, 되돌리기 검사, 실행 잠금과 업데이트, 보관 학년도 쓰기 차단 범위
3. 남은 L01·L03 외에 1.0 전에 꼭 고칠 것이 있는지

## 결과
- /Users/kc/projects/sgb-juicer/docs/review/codex_recheck.md (한국어)
- 항목마다: 판정(해결/부분/미해결/새 문제), 우선순위, 위치(파일:줄), 근거, 고치는 방안
- 맨 앞에 요약, 맨 끝에 확인하지 못한 범위

## 지켜 주세요
- 코드·다른 파일은 고치지 마세요(결과 파일만).
- Chrome 실행, 외부 전송(텔레그램 등), git push는 하지 마세요.
