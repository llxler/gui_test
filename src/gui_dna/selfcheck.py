"""Calibrate evaluator against a known-good implementation and four mutations."""
from pathlib import Path
from .evaluation import evaluate
from .render import reference_code, write_app
from .tasks import dump, task_by_id, test_tasks


def selfcheck(out):
    out = Path(out)
    records = []
    for task in test_tasks():
        folder = out / "correct" / task["id"]
        app = write_app(folder / "index.html", task, reference_code(task["features"]))
        result = evaluate(app, task, folder / "checks")
        records.append({"case": "correct:" + task["id"], "expected_pass": True, "observed_pass": result["passed"], "result": result})
    mutations = [
        ("cancel-mutates-data", "test-edit-filter", lambda code: code.replace("if (e.type === 'cancel') s.editing = null;", "if (e.type === 'cancel') { s.items=s.items.map(x=>x.id===s.editing.id?{...s.editing}:x); s.editing=null; }")),
        ("page-out-of-bounds", "test-delete-pagination", lambda code: code.replace("s.page = Math.max(1,Math.min(s.page,deriveView(s).pages));", "if(e.type !== 'delete') s.page = Math.max(1,Math.min(s.page,deriveView(s).pages));")),
        ("stale-filter-after-save", "test-edit-filter", lambda code: code + "\nconst old=window.candidate; let cached; let stale=false; window.candidate={reduce(s,e){stale=e.type==='save';return old.reduce(s,e);},select(s){if(stale&&cached)return cached;return cached=old.select(s);}};"),
        ("repeated-undo", "test-delete-undo", lambda code: code.replace("const entry = s.history.pop();", "const entry = s.history.at(-1);")),
    ]
    for name, task_id, mutate in mutations:
        task = task_by_id(task_id)
        original = reference_code(task["features"])
        mutated = mutate(original)
        assert original != mutated, f"Mutation {name} was not applied"
        folder = out / "mutants" / name
        app = write_app(folder / "index.html", task, mutated)
        result = evaluate(app, task, folder / "checks")
        records.append({"case": name, "expected_pass": False, "observed_pass": result["passed"], "result": result})
    summary = {"passed": all(r["expected_pass"] == r["observed_pass"] for r in records), "records": records}
    dump(out / "selfcheck.json", summary)
    return summary
