"""통째로 검토 쪽의 [AI로 조합하기](사용자 지정 2026-11-24): 신원 지우고 보내기, ○ 되돌리기, 두 글에 없는 낱말 ⚠, 조합 글로 쓰기."""
import os
import sys
import tempfile

os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, ocr_compare as oc, openrouter  # noqa: E402
from app.api import Api  # noqa: E402

PDF = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "ocr_dummy", "dummy.pdf")
openrouter.balance = lambda key: 1.0


class W:
    def create_file_dialog(self, *a, **k):
        return (PDF,)

    def evaluate_js(self, js):
        pass


def ok(r):
    assert r.get("ok"), r
    return r


def L(t):
    return {"lines": [{"text": x, "box": None} for x in t.split("\n")]}


def Q(t):
    return {"lines": [{"text": x, "unreadable": False} for x in t.split("\n")], "figures": []}


def test_pure():
    a = "학번: 10301 이름: 김가나\n나는 광합성을 탐구함"
    a_s = "학번: ○○○○○ 이름: ○○○\n나는 광합성을 탐구함"
    m, left = oc.restore_ids("학번: ○○○○○ 이름: ○○○\n나는 광합성 실험을 탐구함", [(a_s, a)])
    assert m.startswith("학번: 10301 이름: 김가나") and left == 0, (m, left)
    m, left = oc.restore_ids("○○ 학생", [(a_s, a)])  # 자리를 못 맞추면 그대로 두고 센다
    assert left >= 1
    assert oc.new_words("나는 광합성 실험을 탐구함", "나는 광합성을 탐구함", "나는 광합 성을") == ["실험을"]
    assert oc.new_words("광합성을 탐구함.", "광합성을", "탐구함") == []
    assert "{\"text\"" in oc.MERGE_SYSTEM and "만들지 마세요" in oc.MERGE_SYSTEM


def test_api():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""], "clova_url": "https://x", "clova_secret": "s", "ocr_fix_model": "fixm"})
    api = Api()
    api.attach(W())
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 1, "class_no": 3}))["id"]
    bid = ok(api.inbox_create("조합", hr, "career"))["id"]
    ok(api.inbox_scan_pick(bid))
    ib = api._ib()
    ib.scan_set_mode(bid, "hybrid", 1, 0.14, "m")
    clova = "학번: 10301 이름: 김가나\n탐구 주제 광합성\n빛의 세기를 바꾸어 기포 수를 셈\n결과 표를 그림"
    qwen = "학번 이름\n광합 성 탐구 주제\n빛 세기 바꿔 기포 셈\n결론 정리 표\n선생님 확인"
    ib.scan_store(bid, "clova", pages=[L(clova), L("둘째 쪽")])  # 예시 PDF는 2쪽
    ib.scan_store(bid, "ai", ai_page=(0, {**Q(qwen), "cost": 0}))
    ib.scan_store(bid, "ai", ai_page=(1, {**Q("둘째 쪽"), "cost": 0}))
    r = ok(api.inbox_scan_compare(bid, 0))
    assert r["cmp"]["big"], r["cmp"]["ratio"]
    # 차이별 [AI 제안]은 여전히 막힘, 크지 않은 쪽에서는 조합을 받지 않음
    assert not api.inbox_scan_suggest(bid, 0)["ok"]
    sent = []

    def fake_call(key, model, system, user, privacy_block=False, history=None):
        sent.append((model, system, user))
        return ('{"text": "학번: ○○○○○ 이름: ○○○\\n탐구 주제 광합성\\n빛의 세기를 바꾸어 기포 수를 셈\\n결과 표를 그림\\n선생님 확인 도장"}', 0.0012)

    openrouter.chat = fake_call
    r = ok(api.inbox_scan_merge(bid, 0, "fix"))
    model, system, user = sent[-1]
    assert model == "fixm" and system.startswith(oc.MERGE_SYSTEM[:20])
    assert "10301" not in user and "김가나" not in user and "○" in user  # 신원 지우고 보냄
    m = r["review"]["m"]
    assert m["text"].startswith("학번: 10301 이름: 김가나") and m["left"] == 0, m  # ○ 되돌림
    assert m["new"] == ["도장"], m["new"]  # 두 글에 없는 낱말
    assert r["merge_cost"] == 0.0012
    # 모델 칸 번호로도
    ok(api.inbox_scan_merge(bid, 0, 0))
    assert sent[-1][0] == "m"
    # 조합 글로 쓰기 → 직접 고친 글 자리, 그 뒤에도 고칠 수 있음
    r = ok(api.inbox_scan_decide(bid, 0, {"page": "merge"}))
    assert r["review"]["page"] == "edit" and r["review"]["src"] == "merge" and r["final"].startswith("학번: 10301")
    r = ok(api.inbox_scan_decide(bid, 0, {"page": "edit", "text": "고친 글"}))
    assert r["final"] == "고친 글" and "src" not in r["review"]
    # 고른 것 지우기(reset)에도 조합 글은 남음
    r = ok(api.inbox_scan_decide(bid, 0, {"reset": True}))
    assert r["review"]["m"]["text"] and not r["review"].get("page")
    r = ok(api.inbox_scan_decide(bid, 0, {"page": "clova"}))
    assert "src" not in r["review"]


if __name__ == "__main__":
    test_pure()
    test_api()
    print("MERGE OK")
