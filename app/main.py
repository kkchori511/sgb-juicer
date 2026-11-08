import webview

from . import APP_NAME, VERSION, config
from .api import Api


def selftest(out_path):
    """빌드 확인용(CI): 묶인 라이브러리가 exe 안에서 동작하는지 본다. 창은 띄우지 않는다."""
    import io
    import sys
    import traceback

    lines = []
    try:
        import pypdfium2 as pdfium
        from pypdf import PdfWriter

        from . import scan

        w = PdfWriter()
        w.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        w.write(buf)
        pdf = pdfium.PdfDocument(buf.getvalue())
        bm = pdf[0].render(scale=1, rev_byteorder=True)
        png = scan._png(bm.width, bm.height, bm.n_channels, bm.stride, bytes(bm.buffer))
        assert png.startswith(b"\x89PNG")
        lines.append("pdfium OK")
        import openpyxl  # noqa: F401
        import webview  # noqa: F401

        from . import web_ok

        lines.append("web OK" if web_ok() else "web MISSING")
        lines.append(f"version {VERSION}")
        if "--after-swap" in sys.argv:
            from . import single, updater

            lines.append("lock OK" if single.acquire(20) else "lock FAILED")
            removed = updater.cleanup_leftovers(60)
            lines.append("leftovers cleaned: " + ",".join(removed))
        code = 0 if "web OK" in lines else 1
    except Exception:
        lines.append(traceback.format_exc())
        code = 1
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    sys.exit(code)


def main():
    import sys

    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
    if len(sys.argv) >= 4 and sys.argv[1] == "--selftest-swap":
        # CI: 실행 중인 exe를 실제로 교체하고 새 exe가 자체 시험을 하게 한다
        from . import single, updater

        try:
            if not single.acquire():
                raise RuntimeError("잠금을 얻지 못함")
            updater.swap_and_launch(sys.argv[2], ["--selftest", sys.argv[3], "--after-swap", "--after-update"])
            import time

            time.sleep(1.5)  # 실제 앱처럼 잠시 잠금을 쥔 채 남아 있다가 끝난다
            sys.exit(0)
        except Exception as e:
            with open(sys.argv[3], "w", encoding="utf-8") as f:
                f.write(f"swap failed: {e}")
            sys.exit(1)
    from . import single

    after_update = "--after-update" in sys.argv
    if not single.acquire(20 if after_update else 0):
        single.notify_running()
        return
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
