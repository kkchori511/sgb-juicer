import webview

from . import APP_NAME, VERSION, config
from .api import Api


def main():
    api = Api()
    geo = config.load().get("window") or {}
    kwargs = {}
    if geo.get("width") and geo.get("height") and geo.get("x", -99999) > -2000 and geo.get("y", -99999) > -2000:
        kwargs = {"x": geo["x"], "y": geo["y"], "width": geo["width"], "height": geo["height"]}
    else:
        kwargs = {"width": 1366, "height": 860, "maximized": True}  # 첫 실행은 최대화
    window = webview.create_window(
        f"{APP_NAME} v{VERSION} (베타)",
        url="app/web/index.html",  # pywebview가 앱 루트(_MEIPASS) 기준 내장 서버로 제공
        js_api=api,
        min_size=(1024, 640),
        **kwargs,
    )
    api.attach(window)
    window.events.closing += api.save_window
    webview.start()


if __name__ == "__main__":
    main()
