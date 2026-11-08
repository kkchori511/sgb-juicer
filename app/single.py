"""같은 자료 폴더로 앱을 두 번 켜지 못하게 한다(설정·DB 동시 쓰기 방지)."""
import os

from .paths import data_dir

_handle = None


def acquire(wait_seconds: float = 0) -> bool:
    """잠금을 얻으면 True. 업데이트 직후처럼 이전 앱이 막 끝나는 중이면 wait_seconds 동안 다시 시도한다."""
    import time

    deadline = time.time() + wait_seconds
    while True:
        if _try():
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.3)


def release():
    """업데이트로 새 앱을 띄우기 전에 잠금을 넘겨준다."""
    global _handle
    if _handle is not None:
        try:
            if os.name == "nt":
                import msvcrt

                _handle.seek(0)
                msvcrt.locking(_handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(_handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        _handle.close()
        _handle = None


def _try() -> bool:
    global _handle
    path = data_dir() / ".실행중.lock"
    f = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt

            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return False
    _handle = f
    return True


def notify_running():
    msg = "생기부 착즙기가 이미 실행 중입니다.\n작업 표시줄에서 열린 창을 찾아 주세요."
    if os.name == "nt":
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, msg, "생기부 착즙기", 0x40)
    else:
        print(msg)
