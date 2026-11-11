"""업데이트 내려받기: 릴리스 파일 서버가 막히면 예비 경로, 끊기면 이어 받기, 검증 실패·모두 실패 처리."""
import hashlib, os, sys, tempfile
from pathlib import Path
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import requests
from app import updater

BODY = os.urandom(300_000)
SHA = hashlib.sha256(BODY).hexdigest()
EXE = Path(tempfile.mkdtemp()) / "생기부착즙기.exe"
updater.current_exe = lambda: EXE
URL = "https://github.com/kkchori511/sgb-juicer/releases/download/v9.9.9/SGB-Juicer.exe"
INFO = {"url": URL, "sha256": SHA, "version": "9.9.9", "size": len(BODY)}


class Res:
    def __init__(self, data, status=200, start=0):
        self.data, self.status_code, self.start = data, status, start
        self.headers = {"Content-Length": str(len(data))}
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self):
        if self.status_code >= 400:
            r = requests.Response(); r.status_code = self.status_code
            raise requests.HTTPError(response=r)
    def iter_content(self, n):
        for i in range(0, len(self.data), n):
            yield self.data[i:i + n]


def run(plan):
    """plan(url, headers, call) → Res 또는 예외. 부른 주소 기록을 돌려준다."""
    calls = []
    def get(url, stream=True, timeout=None, headers=None):
        calls.append((url, dict(headers or {})))
        r = plan(url, headers or {}, len(calls))
        if isinstance(r, Exception):
            raise r
        return r
    updater.requests.get = get
    return calls


def test_mirror_when_blocked():
    calls = run(lambda url, h, n: requests.ConnectionError("reset") if "github.com/" in url and "github.io" not in url else Res(BODY))
    p = updater.download(INFO, tries=3, wait=0)
    assert Path(p).read_bytes() == BODY
    assert [c[0] for c in calls].count(URL) == 3 and calls[-1][0] == "https://kkchori511.github.io/sgb-juicer/SGB-Juicer-9.9.9.exe", calls
    log = (Path(DATA) / "업데이트_기록.txt").read_text(encoding="utf-8")
    assert "예비 경로에서 받음" in log and "sig=" not in log


def test_resume():
    """첫 시도는 절반에서 끊김 → 이어 받기(Range)로 나머지."""
    half = len(BODY) // 2

    class Cut(Res):
        def iter_content(self, n):
            yield self.data[:half]
            raise requests.ConnectionError("cut")

    def plan(url, h, n):
        if n == 1:
            return Cut(BODY)
        assert h.get("Range") == f"bytes={half}-", h
        return Res(BODY[half:], status=206)
    run(plan)
    assert Path(updater.download(INFO, tries=3, wait=0)).read_bytes() == BODY


def test_bad_hash_and_all_fail():
    run(lambda url, h, n: Res(b"x" * 10))  # 둘 다 다른 파일
    try:
        updater.download(INFO, tries=1, wait=0)
        raise AssertionError("검증 실패인데 통과")
    except updater.UpdateError as e:
        assert "핫스폿" in str(e)
    assert not EXE.with_name(EXE.name + ".new").exists()
    run(lambda url, h, n: requests.ConnectionError("x"))
    try:
        updater.download(INFO, tries=2, wait=0)
        raise AssertionError("모두 실패인데 통과")
    except updater.UpdateError:
        pass


if __name__ == "__main__":
    test_mirror_when_blocked()
    test_resume()
    test_bad_hash_and_all_fail()
    print("test_update_download OK")
