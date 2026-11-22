"""시험 중 바깥 연결 막기(tests/run_all.py가 PYTHONPATH에 넣는다). 이 PC 안(127.0.0.1·localhost)만 허용.
시험이 실수로 AI·CLOVA·GitHub에 요청하면 바로 실패하게 한다(Codex v1 F8)."""
import socket

_LOCAL = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
_gai = socket.getaddrinfo
_connect = socket.socket.connect


def _host(addr):
    return addr[0] if isinstance(addr, tuple) and addr else addr


def getaddrinfo(host, *a, **k):
    if host not in _LOCAL and not (isinstance(host, str) and host.startswith("127.")):
        raise OSError(f"[시험] 바깥 연결 막힘: {host}")
    return _gai(host, *a, **k)


def connect(self, addr):
    h = _host(addr)
    if isinstance(h, str) and h not in _LOCAL and not h.startswith("127.") and self.family in (socket.AF_INET, socket.AF_INET6):
        raise OSError(f"[시험] 바깥 연결 막힘: {h}")
    return _connect(self, addr)


socket.getaddrinfo = getaddrinfo
socket.socket.connect = connect
