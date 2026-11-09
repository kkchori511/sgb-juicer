"""v0.15 1·2학기 합산 과목: 2학기 목표 = 합산 − 1학기 최종안 바이트."""
import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app import config, openrouter
from app.api import Api
from app.textutil import count_bytes

SENT = []
openrouter.chat = lambda key, model, system, user, privacy_block=False: (SENT.append(system) or "결과", 0.0)
openrouter.balance = lambda key: 1.0


class W:
    def create_file_dialog(self, *a, **k): return ()
    def evaluate_js(self, js): pass


def ok(r):
    assert r.get("ok"), r
    return r


def main():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api(); api.attach(W())
    ok(api.create_year(2026, "subject"))
    s1 = ok(api.add_group({"kind": "subject", "name": "공통수학1", "semester": 1}))["id"]
    s2 = ok(api.add_group({"kind": "subject", "name": "공통수학2", "semester": 2}))["id"]
    other = ok(api.add_group({"kind": "subject", "name": "물리학", "semester": 2}))["id"]
    rows = [{"student_no": "10101", "name": "김하나"}, {"student_no": "10102", "name": "이두리"}]
    for g in (s1, s2):
        ok(api.roster_apply(g, rows, "add"))
    gs = {g["id"]: g for g in ok(api.year_state())["groups"]}
    assert gs[s2]["pair_suggest"] == s1 and gs[other]["pair_suggest"] is None, gs[s2]
    # 연결 규칙: 2학기에서 1학기를, 합산은 양수
    assert not api.update_group(s1, {"pair_id": s2, "pair_total": 1500})["ok"]
    assert not api.update_group(s2, {"pair_id": s1, "pair_total": 0})["ok"]
    ok(api.update_group(s2, {"pair_id": s1, "pair_total": 1500}))
    gs = {g["id"]: g for g in ok(api.year_state())["groups"]}
    assert gs[s2]["pair_id"] == s1 and gs[s2]["pair_total"] == 1500 and gs[s2]["pair_suggest"] is None
    # 1학기 최종안이 없으면 절반
    v = ok(api.student_view(s2, "subject", "10101"))
    assert v["target"] == 750 and v["pair"]["first_bytes"] is None, v["pair"]
    text = "가" * 200  # 600B
    ok(api.edit_final(s1, "subject", "10101", text))
    v = ok(api.student_view(s2, "subject", "10101"))
    assert v["target"] == 1500 - count_bytes(text) == 900 and v["pair"]["first_bytes"] == 600, v["pair"]
    v1 = ok(api.student_view(s1, "subject", "10101"))
    assert v1["pair"]["role"] == "first" and v1["pair"]["total"] == 1500 and v1["target"] == v1["target"]
    # AI 종합은 학생별 남은 바이트를 목표로
    rid = ok(api.add_record(s2, "subject", "10101", {"content": "2학기 활동"}))["id"]
    ok(api.ai_synth(s2, "subject", "10101", [rid], {}))
    assert "900바이트" in SENT[-1], SENT[-1][-300:]
    # 일괄 종합·내보내기 표에 학생별 목표와 1학기 바이트
    b = {x["student_no"]: x for x in ok(api.batch_info(s2, "subject"))["students"]}
    assert b["10101"]["target"] == 900 and b["10101"]["first_bytes"] == 600 and b["10102"]["target"] == 750
    ex = {x["student_no"]: x for x in ok(api.export_preview(s2, "subject"))["rows"]}
    assert ex["10101"]["first_bytes"] == 600 and ex["10101"]["pair_total"] == 1500
    # 1학기가 합산을 다 쓰면 AI를 막는다
    ok(api.edit_final(s1, "subject", "10102", "나" * 520))  # 1560B
    rid2 = ok(api.add_record(s2, "subject", "10102", {"content": "활동"}))["id"]
    e = api.ai_synth(s2, "subject", "10102", [rid2], {})
    assert not e["ok"] and "이미 채웠" in e["error"], e
    # 연결 풀기, 1학기 과목 삭제 시 연결도 풀림
    ok(api.update_group(s2, {"pair_id": None}))
    assert ok(api.student_view(s2, "subject", "10101"))["pair"] is None
    ok(api.update_group(s2, {"pair_id": s1, "pair_total": 1500}))
    ok(api.delete_group(s1))
    gs = {g["id"]: g for g in ok(api.year_state())["groups"]}
    assert gs[s2]["pair_id"] is None
    print("PAIR SUBJECT OK")


if __name__ == "__main__":
    main()
