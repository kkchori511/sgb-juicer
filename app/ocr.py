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


def split_pdf(path: str, max_pages: int = MAX_PAGES_PER_CALL):
    """(전체 페이지 수, [(시작 페이지 index, PDF bytes)])"""
    reader = PdfReader(path)
    total = len(reader.pages)
    chunks = []
    for start in range(0, total, max_pages):
        writer = PdfWriter()
        for i in range(start, min(start + max_pages, total)):
            writer.add_page(reader.pages[i])
        buf = io.BytesIO()
        writer.write(buf)
        chunks.append((start, buf.getvalue()))
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


def image_to_text(img: dict) -> str:
    if img.get("inferResult") and img["inferResult"] != "SUCCESS":
        return f"[인식 실패: {img.get('message') or img['inferResult']}]"
    lines, line = [], []
    for f in img.get("fields") or []:
        line.append(f.get("inferText", ""))
        if f.get("lineBreak"):
            lines.append(" ".join(line))
            line = []
    if line:
        lines.append(" ".join(line))
    return "\n".join(lines).strip()


def ocr_pdf(path: str, url: str, secret: str, lang: str, progress=None, should_stop=None) -> list[str]:
    """페이지 순서대로 텍스트 목록을 돌려준다."""
    import os

    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise OcrError("파일 크기가 50MB를 넘습니다.")
    total, chunks = split_pdf(path)
    if total == 0:
        raise OcrError("PDF에 페이지가 없습니다.")
    name = os.path.basename(path)
    pages: dict[int, str] = {}
    for n, (start, data) in enumerate(chunks):
        if should_stop and should_stop():
            raise Stopped()
        if progress:
            progress(n, len(chunks), total)
        body = call_once(url, secret, data, name, lang)
        images = body.get("images") or []
        for i, img in enumerate(images):
            info = img.get("convertedImageInfo") or {}
            idx = info.get("pageIndex", i) if isinstance(info.get("pageIndex"), int) else i
            pages[start + idx] = image_to_text(img)
        if n < len(chunks) - 1:
            time.sleep(CALL_INTERVAL)
    return [pages.get(i, "") for i in range(total)]
