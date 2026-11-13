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
API_LIST = f"https://api.github.com/repos/{GITHUB_REPO}/releases?per_page=30"
# 릴리스 노트에 이 제목의 절(## ⚠ 업데이트 전 꼭 읽기)이 있으면, 화면을 없애거나 합쳐 자료 위치가 바뀌는 업데이트다.
# 앱은 [지금 업데이트]를 누를 때 이 절을 보여 주고 '확인했어요'를 직접 쳐야 진행한다.
WARN_HEAD = "업데이트 전 꼭 읽기"
CONFIRM_WORD = "확인했어요"
# 예비 경로: 일부 학교·통신사 망은 GitHub 릴리스 파일 서버(release-assets.githubusercontent.com)를 막는다.
# 릴리스 때 CI가 같은 exe를 GitHub Pages(gh-pages 브랜치, 최신 1개)에도 올린다. 어디서 받든 SHA-256으로 같은 파일인지 확인한다.
MIRROR = f"https://{GITHUB_REPO.split('/')[0]}.github.io/{GITHUB_REPO.split('/')[1]}/SGB-Juicer-{{version}}.exe"
RELEASES_PAGE = f"https://github.com/{GITHUB_REPO}/releases/latest"


def warning_of(body: str) -> str:
    """릴리스 노트에서 '업데이트 전 꼭 읽기' 절만 꺼낸다(없으면 빈 글자).
    절은 같은 수준이거나 더 높은 제목에서 끝난다(### 하위 제목은 절 안에 포함)."""
    out, level = [], 0
    for ln in (body or "").replace("\r", "").split("\n"):
        m = re.match(r"^(#{1,6})\s", ln)
        if m:
            n = len(m.group(1))
            if level and n <= level:
                break
            if not level:
                if WARN_HEAD in ln:
                    level = n
                continue
        if level:
            if ln.startswith("**Full Changelog"):
                break
            out.append(ln)
    return "\n".join(out).strip()


INCOMPLETE = ("업데이트 안내를 모두 확인하지 못했습니다(인터넷 연결 또는 GitHub 응답 문제). "
              "건너뛴 버전에 메뉴가 없어지거나 합쳐지는 변경이 있을 수 있으니, [변경 내용]이나 릴리스 페이지에서 확인한 뒤 진행하세요.")


def warnings_between(latest_tag: str, latest_body: str, local: str = VERSION, max_pages: int = 10) -> tuple[str, bool]:
    """지금 버전과 새 버전 사이(건너뛴 버전 포함)의 경고를 모은다. 반환: (경고 글, 끝까지 확인했는지).
    릴리스 목록을 지금 버전보다 옛 릴리스가 나올 때까지 쪽마다 넘겨 본다. 중간에 못 읽으면 확인 못 함으로 본다."""
    found, complete = {}, False
    try:
        for page in range(1, max_pages + 1):
            res = requests.get(f"{API_LIST}&page={page}", timeout=15, headers={"Accept": "application/vnd.github+json"})
            if not res.ok:
                break
            rows = res.json()
            if not isinstance(rows, list):
                break
            if not rows:
                complete = True  # 더 없음
                break
            for r in rows:
                tag = r.get("tag_name", "")
                if r.get("draft") or r.get("prerelease") or not is_newer(tag, local) or is_newer(tag, latest_tag.lstrip("v")):
                    continue
                w = warning_of(r.get("body") or "")
                if w:
                    found[tag] = w
            # 목록은 최신순: 이 쪽에 지금 버전 이하가 있으면 그 아래는 볼 필요 없음
            if any(parse_version(r.get("tag_name", "")) and not is_newer(r.get("tag_name", ""), local) for r in rows):
                complete = True
                break
    except (requests.RequestException, ValueError):
        complete = False
    w = warning_of(latest_body)
    if w:
        found[latest_tag] = w
    order = sorted(found, key=parse_version)
    text = found[order[0]] if len(order) == 1 else "\n\n".join(f"[{t}]\n{found[t]}" for t in order)
    return text, complete


class UpdateError(Exception):
    def __init__(self, msg, code=None):
        super().__init__(msg)
        self.code = code


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


def _warning_text(tag, body):
    """확인할 경고 글. 끝까지 확인하지 못했으면 그 사실도 경고로 넣어 '확인했어요' 입력을 받는다(경고 없음과 구분)."""
    text, complete = warnings_between(tag, body)
    if complete:
        return text
    return INCOMPLETE + (f"\n\n{text}" if text else "")


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
        "warning": _warning_text(tag, data.get("body") or ""),
        "confirm_word": CONFIRM_WORD,
        "url": asset.get("browser_download_url"),
        "size": asset.get("size"),
        "sha256": sha,
        "can_apply": can_apply() and bool(sha),
    }


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fetch(url, dest: Path, size_hint=0, progress=None):
    """dest로 받는다. 이미 받은 부분이 있으면 이어 받는다(서버가 Range를 받지 않으면 처음부터)."""
    done = dest.stat().st_size if dest.exists() else 0
    headers = {"Range": f"bytes={done}-"} if done else {}
    with requests.get(url, stream=True, timeout=(15, 60), headers=headers) as res:
        if done and res.status_code != 206:
            done = 0
        res.raise_for_status()
        total = done + int(res.headers.get("Content-Length") or 0) or int(size_hint or 0)
        with open(dest, "ab" if done else "wb") as f:
            for chunk in res.iter_content(1 << 16):
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done, total)


def _why(e) -> str:
    """기록용 짧은 원인(주소에 붙은 서명 값은 남기지 않는다)."""
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}"
    if isinstance(e, requests.exceptions.SSLError):
        return "SSLError(인증서·보안 장비)"
    if isinstance(e, requests.Timeout):
        return "Timeout(응답 없음)"
    if isinstance(e, requests.ConnectionError):
        return "ConnectionError(연결 막힘·끊김)"
    return e.__class__.__name__


def download(info: dict, progress=None, tries=3, wait=1.0) -> str:
    """GitHub 릴리스 파일 → 안 되면 예비 경로(GitHub Pages). 경로마다 끊기면 이어 받기로 몇 번 다시 시도한다."""
    import time

    url = info.get("url") or ""
    if not url.startswith(f"https://github.com/{GITHUB_REPO}/releases/download/"):
        raise UpdateError("업데이트 주소가 올바르지 않습니다.")
    sha = (info.get("sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise UpdateError("검증값(SHA-256)이 없어 자동 업데이트하지 않습니다. 릴리스 페이지에서 직접 내려받아 주세요.")
    dest = current_exe().with_name(current_exe().name + ".new")
    sources = [("GitHub 릴리스", url)]
    if re.fullmatch(r"[0-9A-Za-z.\-]+", info.get("version") or ""):
        sources.append(("예비 경로", MIRROR.format(version=info["version"])))
    why = []
    for label, src in sources:
        try:
            dest.unlink(missing_ok=True)
        except OSError as e:
            raise UpdateError(f"이전에 받다 만 파일을 지우지 못했습니다({e.__class__.__name__}).") from e
        for i in range(tries):
            try:
                _fetch(src, dest, info.get("size"), progress)
                break
            except (requests.RequestException, OSError) as e:
                why.append(f"{label} {i + 1}회: {_why(e)}")
                if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code == 404:
                    break  # 없는 파일: 다시 해도 같다
                if i + 1 < tries:
                    time.sleep(wait)
        else:
            continue
        if dest.exists() and _sha256(dest) == sha:
            if why:
                log("내려받기: " + "; ".join(why) + f" → {label}에서 받음")
            return str(dest)
        why.append(f"{label}: 검증(SHA-256) 실패")
    dest.unlink(missing_ok=True)
    log("내려받기 실패: " + "; ".join(why))
    raise UpdateError("새 버전을 내려받지 못했습니다. 지금 인터넷망이 GitHub 파일 서버를 막고 있을 수 있어요. "
                      "다른 인터넷(휴대폰 핫스폿 등)에서 다시 시도하거나, 릴리스 페이지에서 직접 받아 exe를 바꿔 주세요.")


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


def swap_only(new_path: str):
    """exe만 새 버전으로 바꿔 둔다(실행은 사용자가 다시 켤 때). 보안 프로그램이 자동 실행을 막는 학교 PC용."""
    swap_and_launch(new_path, launch=False)


def swap_and_launch(new_path: str, args=(), before_launch=None, launch=True):
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
    if not launch:
        log("교체 완료, 다시 시작하면 새 버전 실행")
        return
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
