"""CSV 읽기(사용자 지정 2026-11-24): 표 한 장을 읽는 곳은 xlsx와 csv 모두. UTF-8(BOM)·CP949, 쉼표·탭, 셀 안 줄바꿈."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import api as api_mod, banned, roster, trait, trait_dict, vocab  # noqa: E402
from app.db import DbError  # noqa: E402


def w(name, text, enc="utf-8-sig"):
    p = os.path.join(DATA, name)
    with open(p, "w", encoding=enc, newline="") as f:
        f.write(text)
    return p


def test_all():
    # 인코딩·셀 안 줄바꿈·빈 줄
    want = [["학번", "이름", "내용"], ["10101", "김가나", "첫 줄\n둘째, 줄"], ["10102", "이다라", "글"]]
    body = "학번,이름,내용\r\n10101,김가나,\"첫 줄\n둘째, 줄\"\r\n\r\n10102,이다라,글\r\n"
    assert roster.parse_csv(w("cp.csv", body, "cp949")) == want
    assert roster.parse_csv(w("u8.csv", body)) == want
    assert roster.parse_csv(w("tab.csv", body.replace(",", "\t").replace("둘째\t 줄", "둘째, 줄"))) == want
    assert roster.is_csv("A.CSV") and not roster.is_csv("a.xlsx")
    # 줄 자리 그대로(행특 설계 오류 줄 번호가 엑셀과 같게)
    assert roster.table_rows(w("r.csv", "a,b\n\n1,2\n")) == [["a", "b"], [], ["1", "2"]]
    # 기재 유의어·세특 어휘·행특 설계·사전
    assert banned.from_xlsx(w("b.csv", "기재 유의어,한글·다른 표기,대체 표현\nNotion,노션,협업 도구\n")) == [{"terms": ["Notion", "노션"], "repl": "협업 도구", "except": []}]
    v = vocab.from_xlsx(w("v.csv", "활동 동사,평가 표현\n탐구함,우수함\n", "cp949"))
    assert v["verbs"] == ["탐구함"] and v["evals"] == ["우수함"]
    try:
        trait.read_xlsx(w("t.csv", "x,y\n"))
        raise AssertionError("모양 검사")
    except DbError as e:
        assert "행특 설계 엑셀 모양" in str(e)
    try:
        trait_dict.from_xlsx(w("td.csv", "x\n"))
        raise AssertionError("모양 검사")
    except DbError as e:
        assert "사전 엑셀 모양" in str(e)
    # 엑셀 자료 읽기(이미 쓴 생기부·Inbox 자료): csv는 시트 고르기 없이 바로
    a = api_mod.Api()
    a._xlsx_paths = getattr(a, "_xlsx_paths", {})
    a._xlsx_paths["tok"] = w("e.csv", body, "cp949")
    rows, pick = a._read_xlsx("tok", None)
    assert rows == want and pick is None
    # 파일 창 종류
    assert "*.csv" in api_mod.TABLE_TYPES[0]


if __name__ == "__main__":
    test_all()
    print("CSV OK")
