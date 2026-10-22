import json
import pytest
from gui_dna.tasks import dev_tasks, test_tasks as heldout_tasks
from gui_dna.library import load_library, digest, corpus, validation_feedback
from gui_dna.generation import retrieve
from gui_dna.prompts import generation_messages, library_messages
from gui_dna.render import reference_functions


def test_split_and_context_boundary():
    dev, heldout = dev_tasks(), heldout_tasks()
    assert len(dev) == 16 and len(heldout) == 8
    assert not {frozenset(t["features"]) for t in dev} & {frozenset(t["features"]) for t in heldout}
    for task in heldout:
        for method in ["direct", "retrieval", "dna", "constrained"]:
            messages = generation_messages(task, method, {"functions": reference_functions()}, retrieve(task))
            context = json.dumps(messages)
            assert "heldout-order" not in context
            assert "almanac" not in context
            assert "oracle" not in context
            if method == "dna":
                payload = json.loads(messages[1]["content"])
                assert all("post" not in f and "reads" not in f for f in payload["functions"])
    assert {r["id"] for r in corpus()} == {t["id"] for t in dev}


def test_frozen_library_tamper_detection(tmp_path):
    value = {"functions": reference_functions()}
    value["sha256"] = digest(value)
    path = tmp_path / "library.json"
    path.write_text(json.dumps(value))
    assert load_library(path)["sha256"] == value["sha256"]
    value["functions"][0]["code"] = "tampered"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="hash mismatch"):
        load_library(path)


def test_learning_seeds_disclosed_and_development_counterexamples_reach_feedback(tmp_path):
    messages = library_messages(corpus(), reference_functions())
    assert "human-authored" in messages[0]["content"]
    assert "development_annotations" in json.loads(messages[1]["content"])
    folder = tmp_path / "dev-search-1/checks"
    folder.mkdir(parents=True)
    witness = {"before": {"page": 3}, "event": {"type": "search", "value": ""}, "after": {"page": 1}}
    (folder / "base-search-trace.json").write_text(json.dumps({"trace": [witness]}))
    result = validation_feedback([{"task": "dev-search-1", "cases": [{"name": "base-search", "passed": False, "failure": "bad assertion"}]}], tmp_path)
    assert result[0]["counterexample"] == witness
