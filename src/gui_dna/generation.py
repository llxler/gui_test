"""Generate candidates and repair using public feedback only."""
import json
import time
from pathlib import Path

from .evaluation import evaluate
from .library import corpus, digest
from .prompts import generation_messages
from .provider import parse_json
from .render import compose, write_app
from .tasks import dump


def retrieve(task):
    features = set(task["features"])
    records = corpus()
    # Deterministic feature-set Jaccard; tie-breaker is id. No hidden features or answers.
    records.sort(key=lambda r: (-len(features & set(r["features"]))/len(features | set(r["features"])), r["id"]))
    return records[:2]


def generate(task, method, library, out, config, offline=False, provider=None, model=None, repetition=0):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    identity = {"task": task, "method": method, "library_sha256": library["sha256"] if method in ("dna", "constrained") or offline else None,
                "config": config, "offline": offline, "model": model, "repetition": repetition}
    fingerprint = digest(identity)
    if (out / "result.json").exists():
        previous = json.loads((out / "result.json").read_text())
        if previous["fingerprint"] != fingerprint:
            raise ValueError(f"Output directory already holds a different run: {out}")
        if digest((out / "candidate.js").read_text()) != previous["candidate_sha256"]:
            raise ValueError("Frozen candidate changed after generation")
        if digest((out / "index.html").read_text()) != previous["app_sha256"]:
            raise ValueError("Frozen HTML changed after generation")
        return previous
    if (out / "manifest.json").exists():
        previous = json.loads((out / "manifest.json").read_text())
        if previous["fingerprint"] != fingerprint:
            raise ValueError(f"Interrupted run configuration changed: {out}")
        # Provider replays settled responses and refuses unknown interrupted POSTs.
    dump(out / "manifest.json", {**identity, "fingerprint": fingerprint})
    started = time.monotonic()
    messages = generation_messages(task, method, library, retrieve(task) if method == "retrieval" else [])
    selected = [f for f in library["functions"] if f["feature"] in ["core", *task["features"]]]
    checks = []
    result_code = "window.candidate = {};"
    for attempt in range(1 if offline else config["max_repairs"] + 1):
        version = out / f"candidate-{attempt}"
        version.mkdir(parents=True, exist_ok=True)
        dump(version / "messages.json", messages)
        if offline:
            output = {"decomposition": [f["name"] for f in selected],
                      "shared_state": ["Recompute derived view and clamp page after each event"],
                      "code": compose(library["functions"], task["features"])}
            raw = json.dumps(output)
        else:
            raw = provider.call(model, messages, version / "call", f"generate:{model}:{task['id']}:{repetition}:{method}:{attempt}",
                                seed=config["seed"] + repetition)
        try:
            output = parse_json(raw)
            result_code = output["code"]
            if not isinstance(result_code, str):
                raise ValueError("code must be a string")
            if method in ("dna", "constrained") and not output.get("decomposition"):
                raise ValueError("Missing requirement decomposition")
            if method == "constrained" and not output.get("shared_state"):
                raise ValueError("Missing shared-state relationships")
            dump(version / "output.json", output)
            (version / "candidate.js").write_text(result_code)
            app = write_app(version / "index.html", task, result_code)
            result = evaluate(app, task, version / "public", "public", selected if method == "constrained" else [])
            feedback = {"passed": result["passed"], "error": result.get("error"),
                        "failures": [{"name": c["name"], "failure": c.get("failure"), "actions": c["actions"]} for c in result["cases"] if not c["passed"]]}
        except (ValueError, KeyError, TypeError) as error:
            feedback = {"passed": False, "error": str(error)}
            result_code = "window.candidate = {};"
        checks.append(feedback)
        if feedback["passed"]:
            break
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "Public development check failed. Return the full corrected JSON candidate.\n" + json.dumps(feedback)}]
    (out / "candidate.js").write_text(result_code)
    app = write_app(out / "index.html", task, result_code)
    result = {"fingerprint": fingerprint, "candidate_sha256": digest(result_code), "task_id": task["id"],
              "app_sha256": digest(app.read_text()),
              "method": method, "model": model if not offline else "offline-fixture", "repetition": repetition,
              "offline": offline, "public_passed": checks[-1]["passed"], "attempts": len(checks),
              "elapsed_seconds": time.monotonic() - started, "directory": str(out.resolve())}
    dump(out / "result.json", result)
    return result
