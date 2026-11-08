"""GitHub Release 자동 업데이트.

- 실행할 때 최신 Release를 확인하고 화면에 알린다(작업 중 교체하지 않음).
- [지금 업데이트]: 백업 → 새 exe 내려받기(SHA-256 확인) → 이름 바꿔 교체 → 새 exe 실행 → 이 앱 종료.
  · 실행 중인 exe도 '이름 바꾸기'는 된다: 지금 exe → .old, 내려받은 .new → exe.
  · PowerShell·배치 같은 외부 스크립트를 쓰지 않는다(학교 PC 보안 프로그램이 막는 경우가 있음).
  · 새 앱이 켜지면 남은 .old/.new를 지운다.
- Windows exe(frozen)에서만 교체한다. 개발 실행에서는 확인만 한다.
"""
import datetime as dt
import hashlib
import os
import re
import subprocess
import sys

import requests

from . import EXE_NAME, GITHUB_REPO, VERSION
from pathlib import Path

from .paths import app_dir, data_dir

API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_NAME = "SGB-Juicer.exe"


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
    assets = [a for a in data.get("assets", []) if a.get("name", "").lower().endswith(".exe")]
    asset = next((a for a in assets if a.get("name") == ASSET_NAME), assets[0] if assets else None)
    if not is_newer(tag) or not asset:
        return {"ok": True, "available": False, "latest": tag}
    digest = asset.get("digest") or ""
    sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        sha = ""
    return {
        "ok": True,
        "available": True,
        "version": tag.lstrip("v"),
        "notes": (data.get("body") or "").strip()[:2000],
        "url": asset.get("browser_download_url"),
        "size": asset.get("size"),
        "sha256": sha,
        "can_apply": can_apply() and bool(sha),
    }


def download(info: dict, progress=None) -> str:
    url = info.get("url") or ""
    if not url.startswith(f"https://github.com/{GITHUB_REPO}/releases/download/"):
        raise UpdateError("업데이트 주소가 올바르지 않습니다.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", info.get("sha256") or ""):
        raise UpdateError("검증값(SHA-256)이 없어 자동 업데이트하지 않습니다. 릴리스 페이지에서 직접 내려받아 주세요.")
    dest = current_exe().with_name(current_exe().name + ".new")
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
    if h.hexdigest() != info["sha256"].lower():
        dest.unlink()
        raise UpdateError("내려받은 파일 검증(SHA-256)에 실패했습니다. 다시 시도해 주세요.")
    return str(dest)


def current_exe() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return app_dir() / EXE_NAME


def log(msg: str):
    """업데이트 기록(문제 확인용): 자료 폴더/업데이트_기록.txt"""
    try:
        with open(data_dir() / "업데이트_기록.txt", "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n")
    except OSError:
        pass


def _clean_env():
    """PyInstaller onefile 앱이 다른 onefile 앱을 띄울 때 압축 해제 폴더를 공유하지 않게 한다."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("_PYI") and k != "_MEIPASS2"}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


def swap_and_launch(new_path: str, args=(), before_launch=None):
    """exe 교체 후 새 exe를 띄운다. 실패하면 원래대로 되돌리고 UpdateError.
    before_launch: 새 exe를 띄우기 바로 전에 부른다(실행 잠금 넘겨주기). 이름 바꾸기가 실패하면 부르지 않는다."""
    if not can_apply():
        raise UpdateError("Windows exe에서만 업데이트할 수 있습니다.")
    exe = current_exe()
    new = Path(new_path)
    old = exe.with_name(exe.name + ".old")
    if old.exists():
        try:
            old.unlink()
        except OSError:
            old = exe.with_name(f"{exe.name}.{dt.datetime.now():%H%M%S}.old")
    log(f"교체 시작: {exe.name} ← {new.name}")
    try:
        os.rename(exe, old)
    except OSError as e:
        log(f"실패(지금 exe 이름 바꾸기): {e}")
        raise UpdateError(f"실행 중인 프로그램 이름을 바꾸지 못했습니다({e.__class__.__name__}). 프로그램 폴더에 쓰기 권한이 있는지 확인해 주세요.") from e
    try:
        os.rename(new, exe)
    except OSError as e:
        log(f"실패(새 exe 놓기): {e} — 되돌림")
        try:
            os.rename(old, exe)
        except OSError as e2:
            log(f"되돌리기 실패: {e2}")
        raise UpdateError(f"새 버전으로 바꾸지 못했습니다({e.__class__.__name__}). 다시 시도하거나 릴리스 페이지에서 직접 내려받아 주세요.") from e
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    if not args:
        args = ["--after-update"]  # 새 앱은 이 앱이 잠금을 풀 때까지 기다린다
    if before_launch:
        before_launch()
    try:
        subprocess.Popen([str(exe), *args], cwd=str(exe.parent), env=_clean_env(), creationflags=flags, close_fds=True)
    except OSError as e:
        log(f"새 exe 실행 실패: {e}")
        raise UpdateError(f"새 버전으로 바꿨지만 실행하지 못했습니다. {exe.name}을(를) 직접 실행해 주세요.") from e
    log("교체 완료, 새 버전 실행")


def cleanup_leftovers(wait_seconds: float = 30.0) -> list[str]:
    """새 버전이 켜질 때: 이전 exe(.old)와 남은 .new를 지운다. 이전 앱이 막 끝나는 중일 수 있어 잠시 다시 시도한다."""
    import time

    if not getattr(sys, "frozen", False):
        return []
    exe = current_exe()
    targets = list(exe.parent.glob(exe.name + "*.old")) + [exe.with_name(exe.name + ".new"), app_dir() / (EXE_NAME + ".new")]
    removed = []
    deadline = time.time() + wait_seconds
    pending = [p for p in dict.fromkeys(targets) if p.exists()]
    while pending and time.time() < deadline:
        left = []
        for p in pending:
            try:
                p.unlink()
                removed.append(p.name)
            except FileNotFoundError:
                pass
            except OSError:
                left.append(p)
        pending = left
        if pending:
            time.sleep(0.5)
    if removed:
        log("남은 파일 정리: " + ", ".join(removed))
    return removed
