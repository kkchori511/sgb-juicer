"""Windows 전용 업데이트 교체 시험(CI에서 실행).

실제 v0.1.0 exe를 임시 폴더에 두고, 그 exe인 것처럼 updater를 돌려
v0.1.1 내려받기(SHA-256 확인) → 앱 종료 대기 → 교체 → 재실행이 되는지 본다.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
REPO = "kkchori511/sgb-juicer"
OLD, NEW = sys.argv[1], sys.argv[2]  # 예: v0.1.0 v0.1.1


def file_version(p):
    out = subprocess.run(["powershell", "-NoProfile", "-Command", f"(Get-Item -LiteralPath '{p}').VersionInfo.FileVersion"],
                         capture_output=True, text=True)
    return out.stdout.strip()


def main():
    work = Path(tempfile.mkdtemp())
    exe = work / "생기부착즙기.exe"
    url = f"https://github.com/{REPO}/releases/download/{OLD}/SGB-Juicer.exe"
    exe.write_bytes(requests.get(url, timeout=120).content)
    print("old exe version:", file_version(exe))
    assert file_version(exe) == OLD.lstrip("v"), "옛 exe 버전이 다릅니다"

    # '앱' 역할 자식 프로세스: frozen exe인 것처럼 꾸미고 업데이트 후 종료
    child = f"""
import sys, requests
sys.path.insert(0, {str(ROOT)!r})
sys.frozen = True
sys.executable = {str(exe)!r}
from app import updater
rel = requests.get('https://api.github.com/repos/{REPO}/releases/tags/{NEW}', timeout=30).json()
a = [x for x in rel['assets'] if x['name'].endswith('.exe')][0]
info = {{'url': a['browser_download_url'], 'size': a['size'], 'sha256': a['digest'].split(':', 1)[1]}}
# 잘못된 해시는 거부해야 한다
try:
    updater.download(dict(info, sha256='0' * 64)); print('BAD: wrong hash accepted'); sys.exit(2)
except updater.UpdateError as e:
    print('wrong hash rejected:', e)
path = updater.download(info)
print('downloaded', path)
updater.launch_swap(path)
print('swap launched, exiting')
"""
    r = subprocess.run([sys.executable, "-c", child], capture_output=True, text=True, encoding="utf-8")
    print(r.stdout, r.stderr)
    assert r.returncode == 0, "자식 프로세스 실패"

    deadline = time.time() + 90
    ver = ""
    while time.time() < deadline:
        time.sleep(2)
        if not (work / "생기부착즙기.exe.new").exists():
            ver = file_version(exe)
            if ver == NEW.lstrip("v"):
                break
    print("exe version after swap:", ver)
    assert ver == NEW.lstrip("v"), "exe가 교체되지 않았습니다"

    time.sleep(8)
    ps = subprocess.run(["powershell", "-NoProfile", "-Command",
                         f"Get-Process | Where-Object {{ $_.Path -eq '{exe}' }} | Select-Object -ExpandProperty Id"],
                        capture_output=True, text=True)
    pids = [x for x in ps.stdout.split() if x.strip().isdigit()]
    print("relaunched pids:", pids)
    assert pids, "교체 후 다시 실행되지 않았습니다"
    assert (work / "생기부착즙기_데이터").is_dir(), "새 exe가 데이터 폴더를 만들지 않았습니다"
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    print("UPDATE SWAP OK")


if __name__ == "__main__":
    main()
