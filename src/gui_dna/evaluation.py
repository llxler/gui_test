"""Browser execution, independent state/DOM oracle, evidence, and hard wall timeout."""
import json
import subprocess
import sys
import time
import os
import sysconfig
import signal
from pathlib import Path
from copy import deepcopy

from .tasks import ROOT, dump


def evaluate(app, task, out, suite="hidden", contracts=None, timeout=90):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    job = {"app": str(Path(app).resolve()), "task": task, "out": str(out.resolve()),
           "suite": suite, "contracts": contracts or []}
    started = time.monotonic()
    env = dict(os.environ)
    env.pop("OPENROUTER_API_KEY", None)
    local_libs = ROOT / ".browser-deps/usr/lib" / sysconfig.get_config_var("MULTIARCH")
    if local_libs.exists():
        env["LD_LIBRARY_PATH"] = str(local_libs) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    try:
        with subprocess.Popen([sys.executable, "-m", "gui_dna.evaluation"], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
                              start_new_session=True) as process:
            try:
                stdout, stderr = process.communicate(json.dumps(job), timeout=timeout)
            except subprocess.TimeoutExpired:
                # Stop Chromium/Node descendants as well as the Python worker.
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise
            if process.returncode:
                raise RuntimeError(stderr[-3000:])
            result = json.loads(stdout)
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as error:
        result = {"suite": suite, "passed": False, "runnable": False, "cases": [],
                  "error": str(error), "base_passed": 0, "base_total": len(task["features"])}
    result["elapsed_seconds"] = time.monotonic() - started
    dump(out / "evaluation.json", result)
    return result


def perform(page, event):
    kind = event["type"]
    if kind == "search":
        page.locator("#search").fill(event["value"])
        # fill('') emits input only when value changes. Dispatch a real DOM event for no-op changes.
        if page.evaluate("window.__gui.snapshot().state.query") != event["value"]:
            page.locator("#search").dispatch_event("input")
    elif kind in ("filter", "sort"):
        page.locator("#" + kind).select_option(event["value"])
    elif kind == "page":
        page.locator("#page").fill(str(event["value"]))
        page.locator("#go").click()
    elif kind in ("edit", "delete"):
        page.locator(f'tr[data-id="{event["id"]}"] button[data-action="{kind}"]').click()
    elif kind == "draft":
        control = page.locator("#edit-" + event["field"])
        if event["field"] == "category":
            control.select_option(event["value"])
        else:
            control.fill(str(event["value"]))
            control.dispatch_event("change")
    elif kind == "undo" and page.locator("#undo").is_disabled():
        # A second undo is blocked in UI; also probe reducer idempotence through the event API.
        page.evaluate("e => window.__gui.dispatch(e)", event)
    else:
        page.locator("#" + kind).click()


def check(page, expected):
    from .oracle import project
    actual = page.evaluate("window.__gui.snapshot()")
    assert not actual["errors"], f"Runtime errors: {actual['errors']}"
    for key, value in expected.items():
        assert actual["state"].get(key) == value, f"state.{key}: expected {value!r}, got {actual['state'].get(key)!r}"
    wanted = project(expected)
    for key, value in wanted.items():
        assert actual["view"].get(key) == value, f"view.{key}: expected {value!r}, got {actual['view'].get(key)!r}"
    rendered = page.locator("#rows tr").evaluate_all("rows => rows.map(r => ({id:Number(r.dataset.id),name:r.cells[0].textContent,category:r.cells[1].textContent,score:Number(r.cells[2].textContent)}))")
    assert rendered == wanted["items"], f"Rendered rows differ: {rendered!r}"
    assert page.locator("#total").inner_text() == f"{wanted['total']} items"
    assert page.locator("#editor").is_visible() == (expected["editing"] is not None)
    if expected["editing"]:
        for field in ("name", "category", "score"):
            assert page.locator("#edit-" + field).input_value() == str(expected["editing"][field])
    if "pagination" in expected["enabled"]:
        assert page.locator("#page").input_value() == str(expected["page"])
        assert page.locator("#prev").is_disabled() == (expected["page"] <= 1)
        assert page.locator("#next").is_disabled() == (expected["page"] >= wanted["pages"])
    if "undo" in expected["enabled"]:
        assert page.locator("#undo").is_disabled() == (not expected["history"])
    return actual


def contract_checks(contract_page, contracts, trace):
    from .render import EVENTS
    checked = []
    for function in contracts:
        if function["feature"] != "core" and trace["event"]["type"] not in EVENTS.get(function["feature"], []):
            continue
        for phase in ("pre", "post"):
            expression = function[phase]
            valid = contract_page.evaluate("""({expression,trace}) => {
              const f = new Function('before','event','after','beforeView','afterView','return ('+expression+');');
              return f(structuredClone(trace.before),structuredClone(trace.event),structuredClone(trace.after),structuredClone(trace.beforeView),structuredClone(trace.afterView)) === true;
            }""", {"expression": expression, "trace": trace})
            assert valid, f"Contract {function['name']}.{phase} failed: {expression}"
            checked.append(function["name"] + "." + phase)
    return checked


def run_browser(job):
    from playwright.sync_api import sync_playwright
    from .oracle import project, transition
    from .suites import cases
    out = Path(job["out"])
    records = []
    runnable = True
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width": 1120, "height": 900}, service_workers="block")
        context.route("**/*", lambda route: route.continue_() if route.request.url == Path(job["app"]).as_uri() else route.abort())
        page = context.new_page()
        page.set_default_timeout(1800)
        contract_page = context.new_page()
        console_errors = []
        page.on("pageerror", lambda error: console_errors.append(str(error)))
        page.goto(Path(job["app"]).as_uri(), wait_until="load")
        for case in cases(job["task"], job["suite"]):
            record = {"name": case["name"], "kind": case["kind"], "passed": False, "actions": [], "contracts_checked": []}
            state = deepcopy(case["initial"])
            console_errors.clear()
            try:
                page.evaluate("s => window.__gui.reset(s)", state)
                check(page, state)
                for instruction in case["steps"]:
                    event = dict(instruction)
                    if "pick" in event:
                        rows = project(state)["items"]
                        assert rows, "Evaluator fixture selected a row from an empty view"
                        event["id"] = rows[event.pop("pick")]["id"]
                    record["actions"].append(event)
                    perform(page, event)
                    state = transition(state, event)
                    actual = page.evaluate("window.__gui.snapshot()")
                    if job["contracts"] and actual["trace"]:
                        record["contracts_checked"].extend(contract_checks(contract_page, job["contracts"], actual["trace"][-1]))
                    check(page, state)
                    assert not console_errors, str(console_errors)
                record["passed"] = True
            except Exception as error:
                record["failure"] = str(error)
                screenshot = out / (case["name"] + ".png")
                page.screenshot(path=str(screenshot), full_page=True, timeout=3000)
                record["screenshot"] = str(screenshot)
                try:
                    snapshot = page.evaluate("window.__gui.snapshot()")
                    dump(out / (case["name"] + "-trace.json"), snapshot)
                    if snapshot["errors"]: runnable = False
                except Exception:
                    runnable = False
                if console_errors: runnable = False
            records.append(record)
        browser.close()
    base = [r for r in records if r["kind"] == "base"]
    return {"suite": job["suite"], "passed": all(r["passed"] for r in records), "runnable": runnable,
            "base_passed": sum(r["passed"] for r in base), "base_total": len(base), "cases": records}


if __name__ == "__main__":
    job = json.load(sys.stdin)
    if job['suite'].startswith('v2-'):
        from .followup.evaluator import run_browser as run_followup
        result = run_followup(job)
    else:
        result = run_browser(job)
    print(json.dumps(result, ensure_ascii=False))
