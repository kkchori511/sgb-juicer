"""스캔 PDF 머리글 학번·이름 읽기(scan.extract_ids)·지우기(strip_ids/strip_pages) — Windows 시험 W1, Codex v1 F1.
'이름:' 다음 줄에 이름이 따로 있는 손글씨 학습지, 라벨 낱말로 시작하는 성('반'), 본문 낱말을 이름으로 잡아 본문을 지우던 문제."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import scan  # noqa: E402

MEM = [{"student_no": "20301", "name": "김철수"}, {"student_no": "20302", "name": "이영희"},
       {"student_no": "10399", "name": "반유진"}]


def test():
    # W1: '이름:' 줄 끝, 다음 줄에 이름만(더미 학습지 1쪽 CLOVA 모양)
    t1 = "과학 탐구 활동지\n학번: 10399\n이름:\n가나다\n탐구 주제: 물의 끓는점 실험\n맑은 날, 물 200mL를 준비했다."
    assert scan.extract_ids(t1, []) == ("10399", "가나다"), scan.extract_ids(t1, [])
    s1 = scan.strip_ids(t1, "10399", "가나다")
    assert "가나다" not in s1 and "10399" not in s1 and "이름" not in s1 and "탐구 주제" in s1, s1
    # 같은 줄(2쪽 모양)은 그대로
    assert scan.extract_ids("과학 탐구 활동지\n학번: 10399\n이름: 가나다\n본문", []) == ("10399", "가나다")
    # 이름 칸이 비었고 다음 줄이 본문이면 이름을 지어내지 않음(본문 낱말·라벨 낱말을 잡지 않음)
    for t in ("학번: 10399\n이름:\n탐구 주제: 물의 끓는점", "학번: 10399\n이름:\n날짜: 11월 10일", "10399 이름\n본문 글"):
        assert scan.extract_ids(t, []) == ("10399", ""), (t, scan.extract_ids(t, []))
    # 명렬 이름이 머리글에 있으면 그 이름
    assert scan.extract_ids("학번 20301\n이름:\n김철수\n본문", MEM) == ("20301", "김철수")
    assert scan.extract_ids("2학년 3반 2번 이영희\n본문", MEM) == ("20302", "이영희")

    # F1-1 라벨 낱말로 시작하는 성: '반유진'의 '반'을 라벨로 보지 않음(명렬 있음·없음)
    t = "학번: 10399\n이름: 반유진\n탐구를 진행하였다."
    assert scan.extract_ids(t, []) == ("10399", "반유진"), scan.extract_ids(t, [])
    assert scan.extract_ids(t, MEM) == ("10399", "반유진")
    s = scan.strip_pages([t], "10399", "반유진", MEM)
    assert s == "탐구를 진행하였다.", s
    # F1-2 '이름.' 뒤 다음 줄 이름(구분 기호 모두 허용)
    t = "학번: 20301\n이름.\n김철수\n실험을 진행하였다."
    assert scan.extract_ids(t, MEM) == ("20301", "김철수")
    assert scan.strip_pages([t], "20301", "김철수", MEM) == "실험을 진행하였다."
    assert scan.extract_ids("학번: 10399\n이름 ：\n가나다\n본문", []) == ("10399", "가나다")
    # F1-3 라벨 없는 '학번 뒤 한글'은 이름이 아님 → 본문을 지우지 않음
    t = "10399\n탐구를 진행하였다."
    assert scan.extract_ids(t, []) == ("10399", "")
    assert scan.strip_pages([t], "10399", "", []) == "탐구를 진행하였다."
    assert scan.extract_ids("10399 탐구를 진행하였다.", MEM) == ("10399", "")
    assert scan.strip_pages(["10399 탐구를 진행하였다."], "10399", "", MEM) == "탐구를 진행하였다."
    # F1-4 빈 이름 칸 뒤 제목은 이름이 아님(명렬 없음: 4글자 이상, 명렬 있음: 명렬에 없는 낱말)
    t = "학번: 10399\n이름:\n탐구활동\n실험을 진행하였다."
    assert scan.extract_ids(t, []) == ("10399", "")
    s = scan.strip_pages([t], "10399", "", [])
    assert "탐구활동" in s and "실험을 진행하였다." in s, s
    t = "학번: 20301\n이름:\n탐구활동\n실험을 진행하였다."
    assert scan.extract_ids(t, MEM) == ("20301", "")
    assert "탐구활동\n실험을" in scan.strip_pages([t], "20301", "", MEM)
    # 명렬이 있어도 '이름:' 다음 줄의 명렬 밖 이름(2~3글자)은 지움(매칭 이름으로는 안 씀) — 데모 학습지 모양
    t = "과학 탐구 활동지\n학번: 10399\n이름:\n가나다\n탐구 주제: 물의 끓는점"
    assert scan.extract_ids(t, MEM) == ("10399", "")
    assert scan.strip_pages([t], "10399", "", MEM) == "과학 탐구 활동지\n탐구 주제: 물의 끓는점", scan.strip_pages([t], "10399", "", MEM)
    # F1-5 반복 라벨: 첫 라벨이 비어도 다음 라벨을 본다
    t = "이름: 학번\n학번: 20302\n이름: 이영희\n본문입니다."
    assert scan.extract_ids(t, MEM) == ("20302", "이영희"), scan.extract_ids(t, MEM)
    assert scan.strip_pages([t], "20302", "이영희", MEM) == "본문입니다."
    # F1-6 8번째 줄 '이름:' 다음 9번째 줄 이름도 지움
    t = "\n".join(["머리"] * 7 + ["이름:", "김철수", "본문입니다."])
    assert scan.extract_ids(t, MEM)[1] == "김철수"
    assert "김철수" not in scan.strip_pages([t], "", "김철수", MEM)
    # F1-7 여러 쪽: 둘째 쪽에 잘못 읽힌 이름(명렬 밖)도 라벨 자리면 지움
    p1 = "학번: 20301\n이름: 김철수\n첫 쪽 본문"
    p2 = "학번: 20301\n이름: 김철슈\n둘째 쪽 본문"
    s = scan.strip_pages([p1, p2], "20301", "김철수", MEM)
    assert s == "첫 쪽 본문\n\n둘째 쪽 본문", s
    # F1-8 빈 명렬: 라벨 이름은 읽고 지움, 본문 속 '이름을' 같은 낱말은 남김
    t = "학번: 10399 이름: 홍길동\n이름을 붙여 분류하였다."
    assert scan.extract_ids(t, []) == ("10399", "홍길동")
    assert scan.strip_pages([t], "10399", "홍길동", []) == "이름을 붙여 분류하였다."
    # 명렬이 있으면 명렬 밖 이름은 매칭에 쓰지 않음(지우기는 함)
    t = "학번: 20301\n이름: 홍길동\n본문"
    assert scan.extract_ids(t, MEM) == ("20301", "")
    assert scan.strip_pages([t], "20301", "", MEM) == "본문"
    # 본문 낱말 속 명렬 이름은 이름으로 잡지 않음('이영희망' 같은 붙은 글)
    assert scan.extract_ids("학번 20302\n이영희망을 품었다", MEM) == ("20302", "")
    # 라벨 없는 '학번 이름'에서 명렬 학생 이름을 한 글자 잘못 읽은 값도 지움(본문 낱말은 남김)
    assert scan.strip_pages(["20301 김철슈\n본문"], "20301", "", MEM) == "본문"
    assert scan.strip_pages(["20301 탐구를\n본문"], "20301", "", MEM) == "탐구를\n본문"
    print("SCAN IDS OK")


if __name__ == "__main__":
    test()
