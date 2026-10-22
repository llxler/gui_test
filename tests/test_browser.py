from gui_dna.selfcheck import selfcheck
from gui_dna.library import validate
from gui_dna.render import reference_functions
from gui_dna.render import write_app
from gui_dna.tasks import task_by_id
from gui_dna.evaluation import evaluate


def test_evaluator_detects_required_mutations(tmp_path):
    report = selfcheck(tmp_path / "selfcheck")
    assert report["passed"], [(r["case"], r["result"]) for r in report["records"] if r["observed_pass"] != r["expected_pass"]]
    mutants = [r for r in report["records"] if not r["expected_pass"]]
    assert len(mutants) == 4
    assert all(any(c.get("screenshot") for c in r["result"]["cases"]) for r in mutants)


def test_all_development_references_and_contracts(tmp_path):
    records = validate(reference_functions(), tmp_path / "development")
    assert len(records) == 16
    assert all(r["passed"] for r in records), records
    exercised = {x for r in records for c in r["cases"] for x in c["contracts_checked"]}
    assert all(f["name"] + ".post" in exercised for f in reference_functions())


def test_infinite_candidate_has_a_wall_timeout(tmp_path):
    task = task_by_id("test-search-pagination")
    app = write_app(tmp_path / "index.html", task, "while(true) {}")
    result = evaluate(app, task, tmp_path / "checks", timeout=2)
    assert not result["passed"] and not result["runnable"]
    assert result["elapsed_seconds"] < 10
