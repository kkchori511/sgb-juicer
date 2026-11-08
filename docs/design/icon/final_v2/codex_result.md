# 생기부 착즙기 아이콘 v2 — 줄 노트 배경

작성일: 2026-11-08

## 산출물

| 파일 | 규격 | 내용 |
|---|---|---|
| [icon_final_1024.png](icon_final_1024.png) | 1024×1024, sRGB RGBA PNG | 상세본, 하늘색 노트 줄 8개 |
| [icon_small_256.png](icon_small_256.png) | 256×256, sRGB RGBA PNG | 작은 크기용, 굵은 하늘색 노트 줄 4개 |
| [preview_sizes.png](preview_sizes.png) | 1240×1490 PNG | 상세본·작은 크기용을 각각 16·32·48·256px로 표시한 밝은·어두운 배경 비교판 |

두 아이콘은 **흰 종이 타일 안쪽은 불투명, 타일 바깥은 실제 알파 투명**이다. 미리보기의 흰색·짙은 남색은 비교용 배경이며, 아이콘 파일에 포함되지 않는다.

## 변경 내용

기준 파일은 [기존 상세본](../final/icon_final_1024.png), [기존 작은 크기용](../final/icon_small_256.png)이며, [이전 기록](../final/codex_final_result.md)을 확인했다.

- 파랑 타일을 **둥근 사각형 흰색 종이**로 바꿨다.
- 종이에 하늘색 가로 줄을 일정 간격으로 넣었다. 상세본은 8줄, 작은 크기용은 4줄이다.
- 줄은 손·오렌지·맺힌 즙·떨어지는 방울 **뒤에만** 보인다. 그림 위에 줄이 겹치지 않도록 편집했다.
- 손은 크림색에서 **살구·베이지색**으로 조금 진하게 조정하고 따뜻한 갈색 윤곽을 더했다. 네 손가락과 엄지, 손의 방향과 쥐는 구성을 유지했다.
- 즙 방울은 **황금빛 노랑과 주황 윤곽**으로 대비를 높였다. 기존 밝은 하이라이트도 유지했다.
- 타일 둘레에 **연한 회청색 테두리**를 남겨 흰 바탕에서도 종이의 경계를 확인할 수 있게 했다. 바깥 그림자는 추가하지 않았다.
- 손·반쪽 오렌지·과육·즙 방울의 기존 구도를 기준으로 편집했다. 이미지 생성 편집이므로 원본과 픽셀 단위로 동일한 것은 아니다.
- 글자·문구·로고·제본 구멍·펜·접힌 귀 같은 추가 장식은 넣지 않았다.
- 특정 앱의 이미지나 브랜드를 참고 자료로 사용하지 않았다. 일반적인 줄 노트 발상만 반영했다.

### 상세본과 작은 크기용의 차이

상세본은 기존의 8개 과육 구획, 손가락 굽힘과 얕은 음영, 오렌지 아래의 작은 맺힌 즙을 유지했다.

작은 크기용은 기존 단순화 버전의 4개 과육 구획과 손 외곽을 유지했다. 작은 맺힌 방울 대신 기존의 짧은 즙 돌출 형태를 남겼고, 떨어지는 큰 방울과의 간격을 확보했다. 노트 줄은 4개만 남겨 굵게 했다. 상세본을 그대로 축소한 파일이 아니라 작은 크기용 원본을 별도로 편집한 버전이다.

## 투명 배경·파일 확인

시각 편집은 내장 **image_gen** 도구를 사용했다. 투명 출력에서 남은 바깥 흰 잔상은 로컬 PNG 내보내기에서 종이의 둥근 경계로 정리했다. 종이 내부에 미세한 부분 투명이 남지 않도록 흰 종이층에 합성했으며, 그림과 노트 줄은 유지했다. 정확한 크기와 알파 내보내기, 비교판 구성은 macOS CoreGraphics/AppKit을 사용했다.

최종 파일을 다시 읽어 확인한 결과:

| 검사 | 상세본 | 작은 크기용 |
|---|---:|---:|
| 실제 크기 | 1024×1024 | 256×256 |
| 네 모서리 알파 | 모두 0 | 모두 0 |
| 완전 투명 픽셀 수 | 172,956 | 10,354 |
| 가장자리 부분 알파 픽셀 수 | 3,084 | 792 |
| 완전 불투명 픽셀 수 | 872,536 | 54,390 |
| 중앙 영역 최저 알파 | 255 | 255 |
| 캔버스 바깥 테두리의 알파 0 초과 픽셀 수 | 0 | 0 |

중앙 영역은 가로·세로 각각 12.5~87.5%, 바깥 테두리 검사는 각 변의 바깥쪽 약 2.5% 영역을 대상으로 했다. 부분 알파는 둥근 타일 경계의 안티앨리어싱에 해당한다. 밝은 배경과 어두운 배경에서 종이 바깥이 투명하고 종이 안쪽이 뚫리지 않는 것도 육안 확인했다.

## 크기별 확인

[preview_sizes.png](preview_sizes.png)는 열 순서가 **16·32·48·256px**다. 각 크기로 줄인 뒤 1:1로 배치했으므로 100% 배율에서 비교하는 것이 좋다.

행 순서:

1. 상세본 / 흰 배경
2. 작은 크기용 / 흰 배경
3. 상세본 / 어두운 배경
4. 작은 크기용 / 어두운 배경

확인 결과:

- **16px**: 손·오렌지·방울의 색 덩어리가 남는다. 손가락이나 과육의 개별 조각을 세는 크기는 아니다. 연한 종이 테두리는 흰 배경에서 매우 약해지며, 작은 크기용의 굵고 적은 줄이 상세본보다 덜 촘촘하다.
- **32px**: 손 윤곽과 주황 방울 테두리로 흰 종이와 구별된다. 작은 크기용은 4개 과육과 4줄이 비교적 단순하게 읽힌다.
- **48px**: 두 버전 모두 쥐어 짜는 동작과 줄 노트 배경이 구분된다. 줄은 앞쪽 그림을 가리지 않는다.
- **256px**: 상세본의 손가락 음영·속껍질·맺힌 즙·방울 하이라이트를 확인할 수 있다. 작은 크기용의 단순화 차이도 보인다.
- **어두운 배경**: 타일 바깥에 흰 사각형 배경이 나타나지 않고 둥근 종이 외곽만 보인다.
- **흰 배경**: 연한 회청색 테두리가 종이의 경계를 잡고, 살구색 손과 주황 윤곽의 즙 방울이 종이와 구분된다.

검토는 저장한 PNG와 합성 미리보기 기준이다. Windows 앱 적용·ICO 제작·실제 작업 표시줄 테스트는 수행하지 않았다.

## 변경 범위

프로젝트에는 요청한 `final_v2` 폴더의 PNG 3개와 이 문서만 추가했다. `final`의 기존 결과, 다른 시안, assets, 코드와 다른 문서는 수정하지 않았다. Chrome 실행이나 텔레그램 등으로 게시·전송하지 않았다. 요청한 이미지 편집에 필요한 image_gen 호출만 사용했다.

## 사용한 프롬프트

각 기존 버전을 해당 편집의 입력 이미지로 사용했다. 별도 앱 아이콘은 참조하지 않았다.

### 상세본 편집

```text
Use case: precise-object-edit / logo-brand.
Input image: EDIT TARGET, the existing detailed hand-squeezing-orange app icon. Preserve its foreground geometry, placement, proportions and style faithfully. Do not redesign the emblem.
CHANGE THE BACKGROUND ONLY plus the explicitly requested contrast adjustments:
Replace the entire blue rounded-square tile with an OPAQUE WHITE rounded-square sheet of ruled notebook paper. Keep the existing tile size, rounding and margins. Add evenly spaced horizontal light sky-blue notebook rules, about EIGHT rules spaced about 100px at 1024 canvas, modest thickness about 5px. Rule color #a9d4f5 to #7fbff0. Lines run horizontally across the paper, clipped inside its rounded edge, and ONLY BEHIND the hand, orange and juice; no line may be painted over any foreground shape.
Add a very subtle cool blue-gray perimeter stroke around the white tile so its boundary remains visible on a white desktop. Border about 5px at 1024, clean and restrained. No heavy outer shadow. No ring binder, folded corner, red margin line, pen or extra objects. This is a generic ruled sheet idea, NOT a copy of any existing note app icon or brand.
HAND CONTRAST: retain exactly four curled fingers on left and the thumb pressing from above/right, same pose and wrist direction. Change pale cream skin to a slightly warmer light peach-beige, with a darker warm beige thin contour and existing single shallow shading layer. Keep all existing finger creases and subtle overlap shading. Hands must be distinct against white paper.
ORANGE: preserve rind, white pith and EIGHT pulp sections, compressed cut-face shape, same angle and position. Preserve the small bead of juice at the bottom of the orange.
DROP: preserve the large detached drop's shape, exact position and cream-white highlight, but strengthen yellow toward golden amber #ffbd15 with a clean orange-gold contour so it reads on white. 
Keep flat icon style with only one shallow shade layer. NO text, letters, watermark, grid or mockup. Square 1024x1024 PNG master.
TRANSPARENCY: outside the rounded paper tile must be TRUE ALPHA TRANSPARENT, not painted white, not a checkerboard. White paper is a completely OPAQUE foreground sheet; do NOT remove white paper or punch transparent holes into it. Keep the tile interior fully opaque behind rules and artwork. Deliver just one finished icon.
```

### 작은 크기용 편집

```text
Use case: precise-object-edit / logo-brand.
Input image: EDIT TARGET, the existing small-size simplified hand-squeezing-orange app icon. Preserve its foreground geometry, placement, proportions and style faithfully. Do not redesign the emblem.
CHANGE THE BACKGROUND ONLY plus the explicitly requested contrast adjustments:
Replace the entire blue rounded-square tile with an OPAQUE WHITE rounded-square sheet of ruled notebook paper. Keep the existing tile size, rounding and margins. Add exactly FOUR widely and evenly spaced horizontal light sky-blue rules, visibly bold (about 12px thick at 1024), sparse and simple for 16px legibility. Rule color #a9d4f5 to #7fbff0. Lines run horizontally across the paper, clipped inside its rounded edge, and ONLY BEHIND the hand, orange and juice; no line may be painted over any foreground shape.
Add a very subtle cool blue-gray perimeter stroke around the white tile so its boundary remains visible on a white desktop. Border about 12px at 1024, clean and restrained. No heavy outer shadow. No ring binder, folded corner, red margin line, pen or extra objects. This is a generic ruled sheet idea, NOT a copy of any existing note app icon or brand.
HAND CONTRAST: retain exactly four curled fingers on left and the thumb pressing from above/right, same pose and wrist direction. Change pale cream skin to a slightly warmer light peach-beige, with a darker warm beige thin contour and existing single shallow shading layer. Keep finger lobes clear and separate; no new creases. Hands must be distinct against white paper.
ORANGE: preserve rind, white pith and FOUR large pulp sections, compressed cut-face shape, same angle and position. Preserve the short juice neck at bottom.
DROP: preserve the large detached drop's shape, exact position and cream-white highlight, but strengthen yellow toward golden amber #ffbd15 with a clean orange-gold contour so it reads on white. Make contours bold enough for 16 and 32px.
Keep flat icon style with only one shallow shade layer. NO text, letters, watermark, grid or mockup. Square 1024x1024 PNG master.
TRANSPARENCY: outside the rounded paper tile must be TRUE ALPHA TRANSPARENT, not painted white, not a checkerboard. White paper is a completely OPAQUE foreground sheet; do NOT remove white paper or punch transparent holes into it. Keep the tile interior fully opaque behind rules and artwork. Deliver just one finished icon.
```

### 상세본 마무리

```text
Clean final precise-object edit of this EXACT notebook app icon. Preserve ALL existing artwork and colors: peach beige outlined five-digit hand, orange cross section, eight pulp sections and the small collected bead, detached outlined golden drop with highlight, WHITE ruled rounded-square paper, eight thin sky-blue horizontal rules BEHIND artwork only, cool pale blue-gray perimeter border. Do not change art size or hand pose. 
Repair the rounded tile edge to a perfectly smooth clean geometric rounded square and remove ALL disconnected white flecks and jagged white halo OUTSIDE the rounded border. Border remains visible on white. Keep paper interior fully opaque white. Outside the paper sheet is true alpha transparent. No shadow outside, no speckles, no white background beyond tile, no text. Square PNG, one icon.
```

### 작은 크기용 마무리

```text
Clean final precise-object edit of this EXACT notebook app icon. Preserve ALL existing artwork and colors: peach beige outlined five-digit hand, orange cross section, four broad pulp lobes and short bottom juice neck, detached outlined golden drop with highlight, WHITE ruled rounded-square paper, exactly FOUR thick sky-blue horizontal rules BEHIND artwork only, cool pale blue-gray perimeter border. Do not change art size or hand pose. Increase the clear white GAP between orange's bottom juice neck and the detached drop to about 42px at 1024 canvas. Move the drop down slightly only; keep drop inside tile with margin.
Repair the rounded tile edge to a perfectly smooth clean geometric rounded square and remove ALL disconnected white flecks and jagged white halo OUTSIDE the rounded border. Border remains visible on white. Keep paper interior fully opaque white. Outside the paper sheet is true alpha transparent. No shadow outside, no speckles, no white background beyond tile, no text. Square PNG, one icon.
```

