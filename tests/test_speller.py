"""맞춤법 검사 열기: 로컬 페이지가 검사기 주소(원문 칸 채움)로 넘기고, 길면 앞부분만, 빈 글은 거절."""
import os
import re
import sys
import tempfile
import urllib.parse
import webbrowser
from pathlib import Path

os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OPENED = []
webbrowser.open = lambda u: OPENED.append(u)
from app.api import Api  # noqa: E402


def test_all():
    a = Api()
    r = a.open_speller("안녕하세여 반갑습니다")
    assert r["ok"] and not r["cut"]
    page = Path(urllib.parse.urlparse(OPENED[-1]).path)
    url = re.search(r'location\.replace\("(.*?)"\)', page.read_text(encoding="utf-8")).group(1)
    assert url.startswith("https://nara-speller.co.kr/speller/?")
    assert urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["speller-text"] == ["안녕하세여 반갑습니다"]
    r = a.open_speller("가" * 3500)
    assert r["cut"] and r["chars"] == 3000
    assert not page.exists()  # 새로 열 때 지난번 페이지는 지움
    assert not a.open_speller("  ")["ok"]
    Path(urllib.parse.urlparse(OPENED[-1]).path).unlink()


if __name__ == "__main__":
    test_all()
    print("SPELLER OK")
