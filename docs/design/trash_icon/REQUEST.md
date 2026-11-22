# 요청: 휴지통 픽토그램 아이콘 (Codex)

배경: 생기부 착즙기 스캔 PDF 페이지 묶기 화면의 [🗑 페이지 빼기] 버튼(흰 바탕, 붉은 테두리·글자 `#ba1734`, 글자 13px). 지금은 이모지 🗑를 쓰는데, 더 **픽토그램다운 붉은 휴지통 아이콘**으로 바꾸려 한다.

## 만들 것

- `app/web/icons/trash.svg` — 단색 `#ba1734`, viewBox `0 0 24 24`, 뚜껑(손잡이 포함)과 몸통, 몸통 안 세로줄 2~3개. 선 굵기 일정(약 2), 둥근 끝. 13~16px로 작게 써도 또렷하게. 바탕 투명, 글자·그라데이션 없음.
- 같은 폴더의 다른 아이콘(`xlsx.svg`, `pdf.svg`, `wizard_hat.svg`)처럼 작은 SVG 파일 하나.
- 참고용 미리보기 `docs/design/trash_icon/preview.png`(흰 바탕에 16px·32px·64px).

## 지킬 것

- 앱 코드(app.js, style.css, index.html)는 고치지 않기 — 연결은 Claude가 한다.
- Chrome 실행 금지, 외부 전송 금지.
- 끝나면 `docs/design/trash_icon/RESULT.md`에 만든 파일과 확인 방법을 적기.
