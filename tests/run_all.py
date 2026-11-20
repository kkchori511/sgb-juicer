"""시험 파일을 모두 하나씩 따로 실행한다(파일끼리 자료 폴더가 섞이지 않게). 하나라도 실패하면 종료 코드 1.

- 빌드(GitHub Actions)와 손으로 돌릴 때 같이 쓴다: python tests/run_all.py
- 새 시험 파일(tests/test_*.py)은 목록에 따로 적지 않아도 자동으로 들어간다.
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    files = sorted((ROOT / "tests").glob("test_*.py"))
    failed = []
    t0 = time.time()
    for f in files:
        r = subprocess.run([sys.executable, str(f)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            print(f"ok    {f.name}")
        else:
            failed.append(f.name)
            print(f"FAIL  {f.name} (종료 코드 {r.returncode})")
            print((r.stdout + r.stderr)[-3000:])
    print(f"\n{len(files) - len(failed)}/{len(files)} 통과, {time.time() - t0:.0f}초")
    if not files:
        print("시험 파일을 찾지 못했습니다.")
        return 1
    if failed:
        print("실패: " + ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
