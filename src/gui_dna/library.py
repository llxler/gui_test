"""Corpus extraction, empirical validation, and immutable library artifacts."""
import hashlib
import json
from pathlib import Path

from .evaluation import evaluate
from .prompts import library_messages
from .provider import parse_json
from .render import compose, reference_code, reference_functions, write_app
from .tasks import ROOT, dev_tasks, dump


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def load_library(path):
    library = json.loads(Path(path).read_text())
    stored = library.pop("sha256")
    if digest(library) != stored:
        raise ValueError("Frozen library hash mismatch")
    library["sha256"] = stored
    return library


def corpus():
    return [{"id": t["id"], "requirement": t["requirement"], "features": t["features"],
             "initial": t["initial"], "code": reference_code(t["features"])} for t in dev_tasks()]


def validate_schema(functions):
    expected = {f["name"]: f["feature"] for f in reference_functions()}
    if len(functions) != 8 or {f["name"]: f["feature"] for f in functions} != expected:
        raise ValueError(f"Incorrect name/feature mapping. Expected exactly {expected}; got {[(f.get('name'), f.get('feature')) for f in functions]}. Names must be JavaScript identifiers, not labels.")
    for f in functions:
        for key in ("code", "pre", "post"):
            if not isinstance(f.get(key), str) or not f[key].strip():
                raise ValueError(f"Missing {f['name']}.{key}")
        for key in ("reads", "writes", "requires"):
            if not isinstance(f.get(key), list):
                raise ValueError(f"Missing {f['name']}.{key}")
        if any(name not in expected for name in f["requires"]):
            raise ValueError("Unknown library dependency")
    graph = {f["name"]: f["requires"] for f in functions}
    def visit(name, ancestors):
        if name in ancestors:
            raise ValueError("Cyclic library dependencies")
        for dependency in graph[name]:
            visit(dependency, ancestors | {name})
    for name in graph:
        visit(name, set())


def validate(functions, out):
    validate_schema(functions)
    records = []
    for task in dev_tasks():
        folder = Path(out) / task["id"]
        app = write_app(folder / "index.html", task, compose(functions, task["features"]))
        selected = [f for f in functions if f["feature"] in ["core", *task["features"]]]
        result = evaluate(app, task, folder / "checks", "public", selected)
        records.append({"task": task["id"], **result})
    return records


def validation_feedback(validation, directory):
    failures = []
    for record in validation:
        for case in record["cases"]:
            if case["passed"]:
                continue
            trace_path = Path(directory) / record["task"] / "checks" / (case["name"] + "-trace.json")
            snapshot = json.loads(trace_path.read_text()) if trace_path.exists() else {}
            trace = snapshot.get("trace", [])
            failures.append({"task": record["task"], "case": case["name"], "failure": case.get("failure"),
                             "counterexample": trace[-1] if trace else snapshot})
        if record.get("error"):
            failures.append({"task": record["task"], "error": record["error"]})
    return failures


def learn_library(path, offline, provider=None, model=None):
    path = Path(path)
    if path.exists():
        library = load_library(path)
        if library["mode"] != ("offline" if offline else "live"):
            raise ValueError("Cannot reuse an offline library as a live learned library")
        return library
    out = path.parent / (path.stem + "-build")
    records = corpus()
    for record in records:
        dump(ROOT / "data/dev" / (record["id"] + ".json"), record)
    # Only implementations that pass the development checker may enter learning.
    reference_validation = validate(reference_functions(), out / "reference-validation")
    dump(out / "reference-validation.json", reference_validation)
    if not all(r["passed"] for r in reference_validation):
        raise ValueError("Reference validation failed; inspect library-build/reference-validation.json")
    annotations = reference_functions()
    dump(ROOT / "data/dev/annotations.json", annotations)
    messages = library_messages(records, annotations)
    attempts = 1 if offline else 3
    for attempt in range(attempts):
        candidate_dir = out / f"candidate-{attempt}"
        if offline:
            functions = reference_functions()
        else:
            raw = provider.call(model, messages, candidate_dir, "library:" + str(attempt),
                                max_tokens=provider.config["library_max_tokens"], seed=provider.config["seed"])
            try:
                functions = parse_json(raw)["functions"]
            except (ValueError, KeyError, TypeError) as error:
                messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": f"Invalid library JSON: {error}. Return the full corrected library."}]
                continue
        try:
            validation = validate(functions, candidate_dir / "validation")
            valid = all(r["passed"] for r in validation)
            failures = validation_feedback(validation, candidate_dir / "validation")
        except ValueError as error:
            valid, validation, failures = False, [], str(error)
        dump(candidate_dir / "validation.json", validation)
        if valid:
            library = {"schema": 1, "mode": "offline" if offline else "live", "model": model if not offline else None,
                       "learning": "deterministic extraction of annotated reference primitives" if offline else "LLM abstraction extraction from tested development corpus with human-authored contract annotations",
                       "contract_origin": "human-authored development annotations, empirically validated; not autonomous discovery",
                       "corpus_sha256": digest(records), "development_ids": [r["id"] for r in records],
                       "functions": functions, "validation": {"tasks_passed": len(validation), "contracts_exercised": sorted({x for r in validation for c in r["cases"] for x in c["contracts_checked"]})}}
            library["sha256"] = digest(library)
            dump(path, library)
            return library
        if not offline:
            messages += [{"role": "assistant", "content": raw}, {"role": "user", "content": "Development validation failed. Fix the full library:\n" + json.dumps(failures)}]
    raise ValueError("Library did not pass development validation within the learning budget; no library frozen")
