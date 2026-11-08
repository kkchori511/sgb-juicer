"""app/__init__.py의 VERSION으로 packaging/version_info.txt를 만든다(빌드 전에 실행)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
src = (ROOT / "app" / "__init__.py").read_text(encoding="utf-8")
ver = re.search(r'VERSION = "([\d.]+)"', src).group(1)
nums = (ver.split(".") + ["0", "0", "0"])[:4]
tup = ", ".join(str(int(n)) for n in nums)
(ROOT / "packaging" / "version_info.txt").write_text(f"""# UTF-8
VSVersionInfo(
    ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup}), mask=0x3F, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([
            StringTable('041204B0', [
                StringStruct('CompanyName', '김한량 디지털 공방'),
                StringStruct('FileDescription', '생기부 착즙기'),
                StringStruct('FileVersion', '{ver}'),
                StringStruct('InternalName', '생기부착즙기'),
                StringStruct('OriginalFilename', '생기부착즙기.exe'),
                StringStruct('ProductName', '생기부 착즙기'),
                StringStruct('ProductVersion', '{ver}'),
            ]),
        ]),
        VarFileInfo([VarStruct('Translation', [1042, 1200])]),
    ],
)
""", encoding="utf-8")
print(ver)
