"""스캔 PDF 머리글 학번·이름 읽기(scan.extract_ids) — Windows 시험 W1.
'이름:' 다음 줄에 이름이 따로 있는 손글씨 학습지에서 라벨 낱말 '이름'을 이름으로 읽던 문제."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import scan  # noqa: E402

MEM = [{"student_no": "20301", "name": "김철수"}, {"student_no": "20302", "name": "이영희"}]


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
    # 라벨 없이 학번 뒤 이름(예비 규칙)은 그대로 됨
    assert scan.extract_ids("10399 가나다\n본문", []) == ("10399", "가나다")
    # 명렬 이름이 머리글에 있으면 그 이름
    assert scan.extract_ids("학번 20301\n이름:\n김철수\n본문", MEM) == ("20301", "김철수")
    assert scan.extract_ids("2학년 3반 2번 이영희\n본문", MEM) == ("20302", "이영희")
    print("SCAN IDS OK")


if __name__ == "__main__":
    test()
