"""같은 자료 폴더로 앱을 두 번 켜지 못하게 한다(설정·DB 동시 쓰기 방지)."""
import os

from .paths import data_dir

_handle = None


def acquire() -> bool:
    """잠금을 얻으면 True. 프로세스가 끝나면 운영체제가 자동으로 푼다."""
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
