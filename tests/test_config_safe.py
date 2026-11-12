"""설정 파일을 읽지 못하면 기본값으로 덮어쓰지 않고, 깨진 파일은 옮겨 두고 학년도 자료로 이어 쓴다."""
import json, os, sys, tempfile
DATA = tempfile.mkdtemp()
os.environ["SGB_DATA_DIR"] = DATA
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config
from app.api import Api


def test_all():
    api = Api()
    config.save({"openrouter_key": "sk-keep", "setup_done": True})
    assert api.create_year(2026, "homeroom")["ok"]
    path = config.config_path()
    # 1) 잠깐 잠김: 다시 읽어서 통과
    real_open, n = open, {"c": 0}
    import builtins
    def flaky(f, *a, **k):
        if str(f) == str(path) and n["c"] < 2:
            n["c"] += 1
            raise PermissionError(13, "Permission denied")
        return real_open(f, *a, **k)
    builtins.open = flaky
    config.time.sleep = lambda s: None
    try:
        assert config.load()["openrouter_key"] == "sk-keep" and n["c"] == 2
        # 2) 계속 잠김: 기본값을 돌려주되 저장은 막음(키를 지우지 않음)
        n["c"] = -999
        assert config.load()["setup_done"] is False
        r = api.save_config({"menu_collapsed": True})
        assert not r["ok"] and "읽지 못해" in r["error"], r
        lc = api.load_config()
        assert lc["problem"]["error"] and lc["data_dir"]
    finally:
        builtins.open = real_open
    assert json.loads(path.read_text(encoding="utf-8"))["openrouter_key"] == "sk-keep"
    assert api.load_config()["problem"]["error"] is None
    # 3) 깨진 파일: 옮겨 두고 새로 시작, 학년도 자료로 이어 쓰기
    path.write_text("{깨짐", encoding="utf-8")
    lc = api.load_config()
    assert lc["problem"]["broken"] and (path.parent / lc["problem"]["broken"]).exists()
    assert lc["config"]["current_year"] == 2026 and lc["config"]["setup_done"] is True
    ys = api.year_state()
    assert ys["ok"] and ys["year"] == 2026


if __name__ == "__main__":
    test_all()
    print("test_config_safe OK")
