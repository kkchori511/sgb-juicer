import os, sys, tempfile, zipfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, openrouter
from app.api import Api
from app.standards import read_hwpx_text, read_pdf_text
from app.db import DbError

SENT = []
openrouter.chat = lambda key, model, system, user, privacy_block=False: (SENT.append((system, user)) or ("세특 결과", 0.0))
openrouter.balance = lambda key: 1.0
HERE = os.path.dirname(__file__)

def ok(r):
    assert r.get("ok"), r
    return r

def make_hwpx(path):
    sec = ('<?xml version="1.0" encoding="UTF-8"?><hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
           'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:t>[10공수1-01-01] 다항식의 사칙연산을 할 수 있다.</hp:t></hp:run></hp:p>'
           '<hp:p><hp:run><hp:tbl><hp:tr><hp:tc><hp:subList><hp:p><hp:run><hp:t>A</hp:t></hp:run></hp:p></hp:subList></hp:tc>'
           '<hp:tc><hp:subList><hp:p><hp:run><hp:t>사칙연산을 능숙하게 한다</hp:t></hp:run></hp:p></hp:subList></hp:tc></hp:tr></hp:tbl></hp:run></hp:p>'
           '<hp:p><hp:run><hp:t>[10공수1-01-02] 항등식의 성질을 이해한다.</hp:t></hp:run></hp:p></hs:sec>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", sec)

def test():
    d = tempfile.mkdtemp()
    hx = os.path.join(d, "std.hwpx"); make_hwpx(hx)
    t = read_hwpx_text(hx)
    assert t.split("\n") == ["[10공수1-01-01] 다항식의 사칙연산을 할 수 있다.", "A", "사칙연산을 능숙하게 한다", "[10공수1-01-02] 항등식의 성질을 이해한다."], t
    try:
        read_pdf_text(os.path.join(HERE, "fixtures", "scan_sample.pdf")); raise AssertionError("이미지 PDF를 거부해야 함")
    except DbError as e:
        assert "텍스트를 읽을 수 없는 PDF" in str(e)
    bad = os.path.join(d, "x.hwpx"); open(bad, "w").write("x")
    try:
        read_hwpx_text(bad); raise AssertionError
    except DbError:
        pass

    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api()
    ok(api.create_year(2026, "subject"))
    sub = ok(api.add_group({"kind": "subject", "name": "공통수학1", "semester": 1, "level_scale": 3}))["id"]
    club = ok(api.add_group({"kind": "club", "name": "탐구반"}))["id"]
    p = api.roster_from_text("학번\t이름\t성취수준\n20301\t김철수\tA\n20302\t이영희\tC")
    ok(api.roster_apply(sub, api.roster_build(sub, p["raw"], p["header"], p["columns"])["rows"]))
    assert not api.standards_get(club)["ok"]
    ok(api.standards_save(sub, t, "std.hwpx"))
    st = ok(api.standards_get(sub)); assert st["text"] == t and st["source"] == "std.hwpx" and st["levels"] == {"A": 1, "C": 1}
    assert ok(api.standards_overview())["subjects"][0]["has"]
    v = ok(api.student_view(sub, "subject", "20301")); assert v["standards"]["level_scale"] == 3 and v["standards"]["text"] == t

    # 기록 + 성취기준 + 수준
    rid = ok(api.add_record(sub, "subject", "20301", {"content": "인수분해 풀이를 친구에게 설명함"}))["id"]
    r = ok(api.ai_synth(sub, "subject", "20301", [rid], None, None, None, {"text": t, "level": "A"}))
    sys_, user = SENT[-1]
    assert "[성취기준 — 반드시 참고]" in sys_ and "3단계 중 A" in sys_ and "관점에서 해석" in sys_
    for leak in ("20301", "김철수"): assert leak not in sys_ and leak not in user
    assert not api.ai_synth(sub, "subject", "20301", [rid], None, None, None, {"text": t, "level": "E"})["ok"]  # 3단계 범위 밖
    # 성취기준 없이 종합하면 규칙 안 붙음
    ok(api.ai_synth(sub, "subject", "20301", [rid], None)); assert "[성취기준" not in SENT[-1][0]
    # 기록 없는 학생: 성취기준만으로
    assert not api.ai_standards_only(sub, "subject", "20302", {"text": t, "level": ""})["ok"]  # 수준 필수
    assert not api.ai_standards_only(sub, "subject", "20302", {"text": "", "level": "C"})["ok"]  # 기준 필수
    so = ok(api.ai_standards_only(sub, "subject", "20302", {"text": t, "level": "C"}))
    assert "누가기록이 없다" in SENT[-1][0] and "3단계 중 C" in SENT[-1][0] and "이영희" not in SENT[-1][1]
    res = ok(api.student_view(sub, "subject", "20302"))["results"][0]
    assert res["meta"]["basis"] == "standards_only" and res["meta"]["level"] == "C"
    ok(api.adopt_result(so["id"]))
    f = ok(api.student_view(sub, "subject", "20302"))["final"]; assert '"basis": "standards_only"' in f["meta"]
    print("STANDARDS OK")

if __name__ == "__main__":
    test()
