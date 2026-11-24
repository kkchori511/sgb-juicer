"""파일 끌어 놓기(사용자 지정 2026-11-24): 놓은 경로를 맡아 두고(drop_take → token) 불러오기 함수가 drop으로 받는다."""
import os
import sys
import tempfile

DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import api as api_mod  # noqa: E402


class FakeEvents:
    def __iadd__(self, f):
        return self


class FakeWindow:
    class events:
        loaded = FakeEvents()

    def create_file_dialog(self, *a, **k):
        raise AssertionError("끌어 놓으면 파일 창을 열지 않음")


def w(name, text):
    p = os.path.join(DATA, name)
    with open(p, "w", encoding="utf-8-sig") as f:
        f.write(text)
    return p


def drop(a, *paths):
    a._on_drop({"dataTransfer": {"files": [{"name": os.path.basename(x), "pywebviewFullPath": x} for x in paths]}})
    r = a.drop_take()
    assert r["ok"] and r["token"] and r["names"] == [os.path.basename(x) for x in paths], r
    return r["token"]


def test_all():
    a = api_mod.Api()
    a.attach(FakeWindow())
    assert a.drop_take()["token"] is None  # 아직 놓지 않음
    # 기재 유의어: csv를 놓으면 바로 읽음
    b = w("b.csv", "기재 유의어,한글·다른 표기,대체 표현\nNotion,노션,협업 도구\n")
    r = a.banned_import(drop=drop(a, b))
    assert r.get("ok") is not False and r["lib"][0]["terms"] == ["Notion", "노션"], r
    # 같은 표는 한 번만
    t = drop(a, b)
    assert a.banned_import(drop=t)["name"] == "b.csv"
    assert "다시 찾지 못했습니다" in a.banned_import(drop=t)["error"]
    # 종류가 다르면 안내
    pdf = w("x.pdf", "x")
    assert "파일만 놓을 수 있습니다" in a.banned_import(drop=drop(a, pdf))["error"]
    # 하나만 받는 곳에 여러 개
    assert "하나만" in a.banned_import(drop=drop(a, b, b))["error"]
    # 명렬은 여러 개 받음
    r1 = w("r1.csv", "학번,이름\n10101,김가나\n")
    r2 = w("r2.csv", "학번,이름\n10102,이다라\n")
    res = a.roster_from_xlsx(drop=drop(a, r1, r2))
    assert len(res["files"]) == 2, res
    # 엑셀 백업 복구는 xlsx만
    assert "파일만 놓을 수 있습니다" in a.xlsx_restore_check(drop=drop(a, r1))["error"]


if __name__ == "__main__":
    test_all()
    print("DROP OK")
