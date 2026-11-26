"""CLOVA OCR(General) 호출. 한 번에 PDF 10페이지까지만 읽으므로 나눠서 보낸다."""
import io
import json
import time
import uuid

import requests
from pypdf import PdfReader, PdfWriter

MAX_PAGES_PER_CALL = 10
CALL_INTERVAL = 1.1  # 계정당 권장 1 tps
MAX_FILE_BYTES = 50 * 1024 * 1024


class OcrError(Exception):
    pass


class Stopped(Exception):
    pass


def split_pdf(path: str, max_pages: int = MAX_PAGES_PER_CALL, pages=None):
    """(전체 페이지 수, [(그 묶음의 페이지 번호 목록, PDF bytes)]). pages를 주면 그 쪽들만(남은 쪽만 다시 읽기)."""
    reader = PdfReader(path)
    total = len(reader.pages)
    want = [i for i in (range(total) if pages is None else sorted(set(int(x) for x in pages))) if 0 <= i < total]
    chunks = []
    for k in range(0, len(want), max_pages):
        idx = want[k:k + max_pages]
        writer = PdfWriter()
        for i in idx:
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append((idx, buf.getvalue()))
    return total, chunks


def call_once(url: str, secret: str, data: bytes, name: str, lang: str) -> dict:
    message = {
        "version": "V2",
        "requestId": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
        "lang": lang,
        "enableTableDetection": False,
        "images": [{"format": "pdf", "name": name}],
    }
    try:
        res = requests.post(
            url,
            headers={"X-OCR-SECRET": secret},
            data={"message": json.dumps(message)},
            files={"file": (name, data, "application/pdf")},
            timeout=180,
        )
    except requests.RequestException as e:
        raise OcrError(f"CLOVA OCR에 연결하지 못했습니다: {e.__class__.__name__}") from e

    try:
        body = res.json()
    except ValueError:
        body = None
    if not res.ok:
        msg = f"CLOVA OCR HTTP {res.status_code} 오류"
        if isinstance(body, dict) and (body.get("errorMessage") or body.get("message")):
            msg += f": {body.get('errorMessage') or body.get('message')}"
        if res.status_code == 401:
            msg += "\nSecret Key를 확인해 주세요."
        elif res.status_code in (400, 404):
            msg += "\nInvoke URL을 확인해 주세요."
        raise OcrError(msg)
    if not isinstance(body, dict):
        raise OcrError("CLOVA OCR 응답을 해석하지 못했습니다.")
    return body


def image_lines(img: dict) -> dict:
    """한 페이지 → {"lines": [{"text", "box": [x0, y0, x1, y1]}], "w", "h", "fail"}.
    box는 CLOVA가 변환한 페이지 그림(convertedImageInfo) 기준 좌표. 하이브리드 비교에서 원본 줄을 잘라 보여 줄 때 쓴다."""
    info = img.get("convertedImageInfo") or {}
    out = {"lines": [], "w": info.get("width") or 0, "h": info.get("height") or 0, "fail": ""}
    if img.get("inferResult") and img["inferResult"] != "SUCCESS":
        out["fail"] = str(img.get("message") or img["inferResult"])
        return out
    words, xs, ys = [], [], []

    def flush():
        if words:
            out["lines"].append({"text": " ".join(words), "box": [min(xs), min(ys), max(xs), max(ys)] if xs else None})
        words.clear(), xs.clear(), ys.clear()

    for f in img.get("fields") or []:
        words.append(f.get("inferText", ""))
        for v in ((f.get("boundingPoly") or {}).get("vertices") or []):
            if isinstance(v.get("x"), (int, float)) and isinstance(v.get("y"), (int, float)):
                xs.append(round(v["x"])), ys.append(round(v["y"]))
        if f.get("lineBreak"):
            flush()
    flush()
    from .ocr_layout import words_of
    out["words"] = words_of(img)  # 2단 나누기·기울기 보정용 낱말 좌표(사용자 지정 2026-11-26)
    return out


def page_text(page: dict) -> str:
    if page.get("fail"):
        return f"[인식 실패: {page['fail']}]"
    return "\n".join(l["text"] for l in page.get("lines") or []).strip()


def image_to_text(img: dict) -> str:
    return page_text(image_lines(img))


def ocr_pdf_pages(path: str, url: str, secret: str, lang: str, progress=None, should_stop=None, pages=None, on_chunk=None) -> list[dict]:
    """페이지 순서대로 image_lines 결과 목록(읽지 않은 쪽은 None).
    pages: 읽을 쪽 번호(없으면 전부). on_chunk({쪽 번호: 결과}): 묶음마다 받은 즉시 저장하라고 부른다 —
    중지·뒤 묶음 실패 때 앞서 받은 결과를 버리지 않는다(다시 부르지 않게)."""
    import os

    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise OcrError("파일 크기가 50MB를 넘습니다.")
    total, chunks = split_pdf(path, pages=pages)
    if total == 0:
        raise OcrError("PDF에 페이지가 없습니다.")
    name = os.path.basename(path)
    out: dict[int, dict] = {}
    for n, (idx, data) in enumerate(chunks):
        if should_stop and should_stop():
            raise Stopped()
        if progress:
            progress(n, len(chunks), total)
        body = call_once(url, secret, data, name, lang)
        got: dict[int, dict] = {}
        for i, img in enumerate(body.get("images") or []):
            info = img.get("convertedImageInfo") or {}
            k = info.get("pageIndex", i) if isinstance(info.get("pageIndex"), int) else i
            if 0 <= k < len(idx):
                got[idx[k]] = image_lines(img)
        for pg in idx:  # 응답에 없는 쪽은 백지가 아니라 실패로(다시 읽을 수 있게)
            got.setdefault(pg, {"lines": [], "w": 0, "h": 0, "fail": "CLOVA 응답에 이 쪽이 없습니다"})
        out.update(got)
        if on_chunk:
            on_chunk(got)
        if n < len(chunks) - 1:
            time.sleep(CALL_INTERVAL)
    return [out.get(i) for i in range(total)]


def ocr_pdf(path: str, url: str, secret: str, lang: str, progress=None, should_stop=None) -> list[str]:
    """페이지 순서대로 텍스트 목록을 돌려준다."""
    return [page_text(p) if p else "" for p in ocr_pdf_pages(path, url, secret, lang, progress, should_stop)]
