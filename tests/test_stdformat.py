"""v0.15 성취기준 보기 좋게 정리: 원문 글자 보존, 3단계(A·C·E), 머리글 빼기, AI는 역할만."""
import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, openrouter, stdformat
from app.api import Api
from app.standards import standards_rule

SAMPLE = """성취기준별 성취수준 
1) 도형의 방정식

 성취기준
성취기준별 성취수준
[10공수2-01-01] 선분의 내분을 이해하고, 내분점의 좌표를 계산할 수 있다.
A
선분의 내분을 설명하고, 좌표평면 위에서 내분점의 좌표를 구하는 방법을 이해하여 계산할 수 있다.
B
선분의 내분을 이해하고, 좌표평면 위에서 내분점의 좌표를 계산할 수 있다.
C
선분의 내분을 알고, 좌표평면 위에서 내분점의 좌표를 계산할 수 있다.
D 
수직선 위에서 내분점의 좌표를 계산할 수 있다.
E
안내된 절차에 따라 수직선 위에서 내분점의 좌표를 계산할 수 있다.
[10공수2-01-03] 점과 직선 사이의 거리를 구하고, 관련된 문제를 해결할 수 있다.
A
점과 직선 사이의 거리를 구하는 방법을 이해하여 그 거리를 구하고, 관련된 문제를 해결할 수 있다.
B
C
점과 직선 사이의 거리를 구하고, 간단한 문제를 해결할 수 있다.
D 
E
안내된 절차에 따라 원점과 직선 사이의 거리를 구할 수 있다.
[10공수2-01-04] 원의 방정식을 구하고, 그래프를 그릴 수 있다.
A
원의 방정식을 구하고  꼴의 원의 방정식의 그래프를 그릴 수 있다.



2) 집합과 명제
성취기준
[10공수2-02-01] 집합의 개념을 이해하고, 집합을 표현할 수 있다.
A: 집합의 개념을 설명할 수 있다.
C: 집합의 개념을 알 수 있다.
"""

CALLS = []


def fake_chat(key, model, system, user, privacy_block=False):
    CALLS.append(user)
    return '{"0": "header"}', 0.0


openrouter.chat = fake_chat
openrouter.balance = lambda key: 1.0


class W:
    def create_file_dialog(self, *a, **k): return ()
    def evaluate_js(self, js): pass


def ok(r):
    assert r.get("ok"), r
    return r


def norm(s):
    return "".join(s.split())


def main():
    lines = stdformat.split_lines(SAMPLE)
    roles = stdformat.classify(lines)
    assert roles.count("unknown") == 0, [(l, r) for l, r in zip(lines, roles) if r == "unknown"]
    out, three, headers, left = stdformat.build(lines, roles)
    assert three == ["[10공수2-01-03]"] and len(headers) == 4 and left == 0, (three, headers)
    assert "[10공수2-01-03] 점과 직선 사이의 거리를 구하고, 관련된 문제를 해결할 수 있다. (3단계: A·C·E)" in out, out
    assert "  B: 선분의 내분을 이해하고," in out and "  D: 수직선 위에서" in out
    assert "  B: (원문에 내용 없음)" not in out.split("[10공수2-01-03]")[1].split("[10공수2-01-04]")[0]
    assert "  C: (원문에 내용 없음)" not in out  # 한 줄 표기(A: …)도 수준으로 읽음
    assert "  A: 집합의 개념을 설명할 수 있다." in out
    assert stdformat.verify(lines, roles, out) == []
    # 원문 내용 글자가 모두 순서대로(공백만 다를 수 있음)
    body = [l for l, r in zip(lines, roles) if r not in (None, "header", "label")]
    assert all(norm(b.split(":", 1)[-1] if r == "inline" else b) in norm(out) for b, r in zip(body, [r for r in roles if r not in (None, "header", "label")]))
    # 한 글자라도 바뀌면 잡는다
    assert stdformat.verify(lines, roles, out.replace("내분점의 좌표를 계산할 수 있다.", "내분점 좌표를 계산할 수 있다.", 1))
    # 수식 빠진 곳 표시
    assert any("꼴의" in g for _, g in stdformat.gaps(lines, roles))
    # 3단계 규칙이 AI 지침에 들어감
    assert "B면 A 설명을, D면 C 설명을" in standards_rule(out, "B", 5, False)

    # API: 규칙으로 다 되면 AI를 부르지 않음
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api(); api.attach(W())
    ok(api.create_year(2026, "subject"))
    gid = ok(api.add_group({"kind": "subject", "name": "공통수학2", "semester": 2}))["id"]
    r = ok(api.standards_format(gid, SAMPLE, True))
    assert not r["ai_used"] and not CALLS and r["missing"] == [] and r["three_level"] == ["[10공수2-01-03]"]
    # 판단 못 한 줄만 AI에(역할만), 결과는 원문 그대로
    odd = "~~ 참고 자료 ~~\n[10공수2-03-01] 함수의 개념을 설명한다.\nA\n설명 A"
    r = ok(api.standards_format(gid, odd, False))
    assert r["unknown"] == 1 and not r["ai_used"]
    r = ok(api.standards_format(gid, odd, True))
    # V01: AI가 머리글이라 해도 지우지 않고 남기며 알려 준다
    assert r["ai_used"] and CALLS and r["ai_headers"] == ["~~ 참고 자료 ~~"] and "~~ 참고 자료 ~~" in r["text"] and r["missing"] == [], r
    assert "0\t?\t~~ 참고 자료 ~~" in CALLS[-1]
    # 보존 검사는 AI 역할과 무관: 내용 줄을 지운 정리본은 잡는다
    L = stdformat.split_lines("수학적 모델링의 의미를 이해한다.\n[10수-01] 성취기준\nA\n설명")
    assert stdformat.verify(L, ["header", "standard", "label", "text"], "[10수-01] 성취기준\n  A: 설명") == [0]
    # V04: 줄 모양과 맞지 않는 AI 답은 확인 필요로 남김(오류 없음)
    L = stdformat.split_lines("일반 문장입니다\n[10수-01] 기준\nA\n설명")
    roles, hd, chk = stdformat.apply_ai(L, ["unknown", "standard", "label", "text"], '{"0": "label"}')
    assert roles[0] == "keep" and chk == [0]
    out, *_ = stdformat.build(L, roles)
    assert "일반 문장입니다" in out
    roles, hd, chk = stdformat.apply_ai(L, ["unknown", "standard", "label", "text"], "엉터리 답")
    assert roles[0] == "keep" and chk == [0]
    # V03: B·D 기호 자체가 없는 A·C·E도 3단계
    L = stdformat.split_lines("[10수학-01] 기준 문장\nA: 가 설명\nC: 다 설명\nE: 마 설명")
    R = stdformat.classify(L)
    out, three, *_ = stdformat.build(L, R)
    assert three == ["[10수학-01]"] and "(3단계: A·C·E)" in out and "(원문에 내용 없음)" not in out, out
    # 사이가 빈 다른 수준은 '(원문에 내용 없음)'
    L = stdformat.split_lines("[10수학-02] 기준\nA: 가\nB: 나\nD: 라")
    out, three, *_ = stdformat.build(L, stdformat.classify(L))
    assert "  C: (원문에 내용 없음)" in out and not three, out
    print("STDFORMAT OK")


if __name__ == "__main__":
    main()
