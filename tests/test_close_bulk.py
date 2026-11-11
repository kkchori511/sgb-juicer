"""v0.17.1 일괄 마감·해제: 최종안 없는/비활성 학생 건너뛰기, 확인 사항, 되돌리기(반대로 다시)."""
import os, sys, tempfile
os.environ["SGB_DATA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config, openrouter
from app.api import Api

openrouter.chat = lambda *a, **k: ("결과", 0.0)


def ok(r):
    assert r.get("ok"), r
    return r


def main():
    config.save({"openrouter_key": "sk", "models": ["m", "", "", ""]})
    api = Api()
    ok(api.create_year(2026, "homeroom"))
    hr = ok(api.add_group({"kind": "homeroom", "grade": 2, "class_no": 3}))["id"]
    ok(api.roster_apply(hr, [{"student_no": f"2030{i}", "name": n} for i, n in enumerate(["가", "나", "다", "라"], 1)], "add"))
    ok(api.edit_final(hr, "career", "20301", "진로 최종안"))
    ok(api.edit_final(hr, "career", "20302", "진로 최종안 둘"))
    ok(api.edit_final(hr, "career", "20304", "넷"))
    ok(api.set_active(hr, ["20304"], False))
    ok(api.add_record(hr, "career", "20302", {"content": "나중에 더한 기록"}))  # 채택 후 기록 변경(stale)일 수 있음
    info = ok(api.close_info(hr, "career"))
    st = {x["student_no"]: x for x in info["students"]}
    assert st["20301"]["status"] == "final" and st["20303"]["status"] == "none" and not st["20304"]["active"]
    r = ok(api.close_many(hr, "career", ["20301", "20302", "20303", "20304", "99999"], True, 2026))
    assert r["done"] == ["20301", "20302"], r
    assert dict(r["skipped"]) == {"20303": "최종안 없음", "20304": "비활성", "99999": "명렬에 없음"}, r
    st = {x["student_no"]: x for x in ok(api.close_info(hr, "career"))["students"]}
    assert st["20301"]["status"] == "closed" and st["20302"]["status"] == "closed"
    # 다시 마감하면 '이미 마감'으로 건너뜀
    assert dict(ok(api.close_many(hr, "career", ["20301"], True, 2026))["skipped"]) == {"20301": "이미 마감"}
    # 되돌리기 = 바꾼 학생만 반대로
    r2 = ok(api.close_many(hr, "career", r["done"], False, 2026))
    assert r2["done"] == ["20301", "20302"]
    st = {x["student_no"]: x for x in ok(api.close_info(hr, "career"))["students"]}
    assert st["20301"]["status"] == "final"
    # 학년도가 다르면 저장하지 않음
    assert not api.close_many(hr, "career", ["20301"], True, 2025)["ok"]
    # 1·2학기 합쳐 보기: 1학기 최종안, 빈 줄, 2학기 최종안 / 바이트 합 / 두 학기 마감
    s1 = ok(api.add_group({"kind": "subject", "name": "수학Ⅰ", "semester": 1}))["id"]
    s2 = ok(api.add_group({"kind": "subject", "name": "수학Ⅱ", "semester": 2}))["id"]
    ok(api.roster_apply(s1, [{"student_no": "20301", "name": "가"}, {"student_no": "20302", "name": "나"}], "add"))
    ok(api.roster_apply(s2, [{"student_no": "20301", "name": "가"}, {"student_no": "20303", "name": "다"}], "add"))
    assert not ok(api.export_preview(s1, "subject"))["paired"]
    ok(api.update_group(s2, {"pair_id": s1, "pair_total": 1500}))
    assert ok(api.export_preview(s1, "subject"))["paired"] and ok(api.export_preview(s2, "subject"))["paired"]
    ok(api.edit_final(s1, "subject", "20301", "1학기 문장."))
    ok(api.edit_final(s2, "subject", "20301", "2학기 문장."))
    ok(api.set_closed(s1, "subject", "20301", True))
    cb = ok(api.export_combined(s2))
    row = {x["student_no"]: x for x in cb["rows"]}
    assert set(row) == {"20301", "20302", "20303"} and cb["total"] == 1500
    assert row["20301"]["text"] == "1학기 문장.\n\n2학기 문장." and row["20301"]["bytes"] == row["20301"]["bytes1"] + row["20301"]["bytes2"]
    assert row["20301"]["closed1"] and not row["20301"]["closed"]
    assert not ok(api.export_combined(s2, True))["rows"]  # 두 학기 모두 마감한 학생만
    assert not api.export_combined(hr)["ok"]
    print("CLOSE BULK OK")


if __name__ == "__main__":
    main()
