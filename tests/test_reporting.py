from gui_dna.experiment import report_data, METHODS


def test_incomplete_groups_excluded_and_all_failed_live_not_offline(tmp_path):
    accounting = {"calls": []}
    empty = report_data([], accounting, "API unavailable", 0)
    assert empty["offline"] is False
    assert empty["complete_groups"] == 0
    records = []
    for method in METHODS:
        records.append({"model": "m", "method": method, "task_id": "t", "repetition": 0,
                        "directory": str(tmp_path), "offline": False, "elapsed_seconds": 1, "attempts": 1,
                        "hidden": {"passed": method == "constrained", "base_total": 2, "base_passed": 1,
                                   "runnable": True, "elapsed_seconds": 1}})
    records.append({**records[0], "task_id": "incomplete"})
    report = report_data(records, accounting, "budget stop", 0)
    assert report["complete_groups"] == report["incomplete_groups"] == 1
    assert all(s["n"] == 1 and s["base_retention"] == 0.5 for s in report["summary"])
    assert all(p["wins"] == 1 and p["losses"] == 0 for p in report["paired_comparisons"])
