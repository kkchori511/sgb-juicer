def count_bytes(text: str) -> int:
    """나이스 기준: UTF-8 바이트(한글 3, 영어·숫자·기호·공백 1, 가운뎃점 2, 둥근 따옴표·특수기호·한자 3, 이모지 4), 줄바꿈은 2."""
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return len(t.encode("utf-8", "surrogatepass")) + t.count("\n")
