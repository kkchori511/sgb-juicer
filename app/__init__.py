APP_NAME = "생기부 착즙기"
VERSION = "0.14.0"
MAKER = "Made by 김한량 디지털 공방"
TAGLINE = "선생님의 자료 한 방울까지 생기부에 넣겠습니다."
GITHUB_REPO = "kkchori511/sgb-juicer"
EXE_NAME = "생기부착즙기.exe"


def web_ok() -> bool:
    """화면 파일이 함께 묶였는지(빌드 확인용)."""
    from .paths import web_dir

    return all((web_dir() / f).exists() for f in ("index.html", "app.js", "style.css", "guide.html", "icon.png"))
