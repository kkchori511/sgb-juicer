def _is_hangul(ch: str) -> bool:
    c = ord(ch)
    return (
        0xAC00 <= c <= 0xD7A3  # 완성형
        or 0x1100 <= c <= 0x11FF  # 자모
        or 0x3130 <= c <= 0x318F  # 호환 자모
        or 0xA960 <= c <= 0xA97F
        or 0xD7B0 <= c <= 0xD7FF
    )


def count_bytes(text: str) -> int:
    """한글 3바이트, 그 밖(영어·숫자·기호·공백·줄바꿈) 1바이트."""
    return sum(3 if _is_hangul(ch) else 1 for ch in text or "")
