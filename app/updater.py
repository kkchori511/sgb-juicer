"""GitHub Release 자동 업데이트.

- 실행할 때 최신 Release를 확인하고 화면에 알린다(작업 중 교체하지 않음).
- [지금 업데이트]: 백업 → 새 exe 내려받기(SHA-256 확인) → 앱 종료 후 교체 → 다시 실행.
- Windows exe(frozen)에서만 교체한다. 개발 실행에서는 확인만 한다.
"""
import base64
import hashlib
import os
import re
import subprocess
import sys

import requests

from . import EXE_NAME, GITHUB_REPO, VERSION
from .paths import app_dir

API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


class UpdateError(Exception):
    pass


def parse_version(v: str):
    m = re.match(r"^v?(\d+)\.(\d+)(?:\.(\d+))?", (v or "").strip())
    if not m:
        return None
    return tuple(int(x or 0) for x in m.groups())


def is_newer(remote: str, local: str = VERSION) -> bool:
    r, l = parse_version(remote), parse_version(local)
    return bool(r and l and r > l)


def can_apply() -> bool:
    return bool(getattr(sys, "frozen", False)) and os.name == "nt"


def check() -> dict:
    try:
        res = requests.get(API, timeout=15, headers={"Accept": "application/vnd.github+json"})
    except requests.RequestException:
        return {"ok": False, "error": "업데이트를 확인하지 못했습니다(인터넷 연결)."}
    if res.status_code == 404:
        return {"ok": True, "available": False}
    if not res.ok:
        return {"ok": False, "error": f"업데이트를 확인하지 못했습니다(HTTP {res.status_code})."}
    data = res.json()
    tag = data.get("tag_name", "")
    asset = next((a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")), None)
    if not is_newer(tag) or not asset:
        return {"ok": True, "available": False, "latest": tag}
    digest = asset.get("digest") or ""
    return {
        "ok": True,
        "available": True,
        "version": tag.lstrip("v"),
        "notes": (data.get("body") or "").strip()[:2000],
        "url": asset.get("browser_download_url"),
        "size": asset.get("size"),
        "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else "",
        "can_apply": can_apply(),
    }


def download(info: dict, progress=None) -> str:
    url = info.get("url") or ""
    if not url.startswith(f"https://github.com/{GITHUB_REPO}/releases/download/"):
        raise UpdateError("업데이트 주소가 올바르지 않습니다.")
    dest = app_dir() / (EXE_NAME + ".new")
    h = hashlib.sha256()
    done = 0
    try:
        with requests.get(url, stream=True, timeout=60) as res:
            res.raise_for_status()
            total = int(res.headers.get("Content-Length") or info.get("size") or 0)
            with open(dest, "wb") as f:
                for chunk in res.iter_content(1 << 16):
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    if progress and total:
                        progress(done, total)
    except (requests.RequestException, OSError) as e:
        if dest.exists():
            dest.unlink()
        raise UpdateError(f"새 버전을 내려받지 못했습니다: {e.__class__.__name__}") from e
    if info.get("sha256") and h.hexdigest() != info["sha256"].lower():
        dest.unlink()
        raise UpdateError("내려받은 파일 검증(SHA-256)에 실패했습니다. 다시 시도해 주세요.")
    return str(dest)


def launch_swap(new_path: str):
    """앱이 끝나기를 기다렸다가 exe를 바꾸고 다시 실행하는 PowerShell을 띄운다.
    onefile exe는 부트로더·본체 두 프로세스가 같은 exe를 쓰므로, 그 exe 경로를 쓰는
    프로세스가 하나도 남지 않을 때까지(최대 2분) 기다린 뒤 교체한다.
    한글 경로가 깨지지 않도록 -EncodedCommand(UTF-16LE)로 넘긴다."""
    if not can_apply():
        raise UpdateError("Windows exe에서만 업데이트할 수 있습니다.")
    exe = sys.executable

    def ps_quote(s):
        return "'" + str(s).replace("'", "''") + "'"

    script = (
        f"$exe = {ps_quote(exe)}; $new = {ps_quote(new_path)}; "
        "$until = (Get-Date).AddMinutes(2); "
        "while ((Get-Process | Where-Object { $_.Path -eq $exe }) -and (Get-Date) -lt $until) { Start-Sleep -Milliseconds 300 }; "
        "Start-Sleep -Milliseconds 500; "
        "$ok = $false; for ($i = 0; $i -lt 40 -and -not $ok; $i++) { try { Move-Item -Force -LiteralPath $new -Destination $exe -ErrorAction Stop; $ok = $true } catch { Start-Sleep -Milliseconds 500 } }; "
        "Start-Process -FilePath $exe"
    )
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
        creationflags=flags,
        close_fds=True,
    )
