"""Balanced generation batches, a hidden-evaluation barrier, and honest reporting."""
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from pathlib import Path
import json
import platform
import time
import importlib.metadata

from .budget import Ledger, BudgetStop
from .evaluation import evaluate
from .generation import generate
from .library import digest, learn_library
from .provider import OpenRouter, ProviderError
from .tasks import ROOT, dump, test_tasks

METHODS = ["direct", "retrieval", "dna", "constrained"]


def run_compare(config, out, library_path, offline=False):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(ROOT / "artifacts/budget.sqlite3", config["budget_usd"], config["stop_new_requests_usd"])
    provider = None if offline else OpenRouter(config, ledger)
    library = learn_library(library_path, offline, provider, config["library_model"])
    manifest = {"config": config, "offline": offline, "library_sha256": library["sha256"],
                "python": platform.python_version(), "playwright": importlib.metadata.version("playwright"),
                "test_requirements": test_tasks(),
                "implementation_sha256": digest({str(p.relative_to(ROOT)): p.read_text() for p in sorted((ROOT / "src/gui_dna").rglob("*")) if p.suffix in (".py", ".js", ".html")})}
    if (out / "manifest.json").exists() and json.loads((out / "manifest.json").read_text()) != manifest:
        raise ValueError("Comparison manifest changed; choose a new output directory")
    dump(out / "manifest.json", manifest)
    generated = []
    stopped = None
    started = time.monotonic()
    models = ["offline-fixture"] if offline else config["models"]
    repetitions = 1 if offline else config["repetitions"]
    with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
        for repetition in range(repetitions):
            for task in test_tasks():
                for model in models:
                    print(f"Generating {model} / {task['id']} / repeat {repetition+1}", flush=True)
                    futures = []
                    # Complete all four arms of a paired group before starting another.
                    for method in METHODS:
                        folder = out / "runs" / model.replace("/", "__") / task["id"] / f"repeat-{repetition}" / method
                        futures.append(pool.submit(generate, task, method, library, folder, config, offline, provider, model, repetition))
                    for future in futures:
                        try:
                            generated.append(future.result())
                        except (BudgetStop, ProviderError, ValueError) as error:
                            stopped = str(error)
                    if stopped: break
                if stopped: break
            if stopped: break
    # No candidate receives ANY hidden feedback. All LLM calls end before this phase.
    dump(out / "generation-complete.json", {"candidates": generated, "stopped": stopped})
    tasks = {t["id"]: t for t in test_tasks()}
    def final_evaluation(record):
        folder = Path(record["directory"])
        if digest((folder / "candidate.js").read_text()) != record["candidate_sha256"]:
            raise ValueError("Candidate changed at the hidden evaluation barrier")
        if digest((folder / "index.html").read_text()) != record["app_sha256"]:
            raise ValueError("HTML changed at the hidden evaluation barrier")
        result_path = folder / "hidden/evaluation.json"
        evaluation = json.loads(result_path.read_text()) if result_path.exists() else evaluate(folder / "index.html", tasks[record["task_id"]], folder / "hidden")
        return {**record, "hidden": evaluation}
    print(f"Generation frozen; evaluating {len(generated)} candidates against held-out cases", flush=True)
    with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
        results = list(pool.map(final_evaluation, generated))
    report = report_data(results, ledger.summary() if not offline else None, stopped, time.monotonic()-started)
    dump(out / "results.json", report)
    (out / "report.md").write_text(report_markdown(report))
    return report


def report_data(results, accounting, stopped, duration):
    groups = defaultdict(list)
    for record in results:
        groups[(record["model"], record["task_id"], record["repetition"])].append(record)
    complete = {key for key, values in groups.items() if {r["method"] for r in values} == set(METHODS)}
    paired = [r for r in results if (r["model"], r["task_id"], r["repetition"]) in complete]
    summaries = []
    for model in sorted({r["model"] for r in paired}):
        for method in METHODS:
            rows = [r for r in paired if r["model"] == model and r["method"] == method]
            costs = 0.0
            call_ids = {json.loads(p.read_text())["call_id"] for r in rows for p in Path(r["directory"]).rglob("request.json")}
            if accounting:
                costs = sum(c["actual"] or 0 for c in accounting["calls"] if c["id"] in call_ids) / 1e6
            base_total = sum(r["hidden"]["base_total"] for r in rows)
            summaries.append({"model": model, "method": method, "n": len(rows),
                              "passed": sum(r["hidden"]["passed"] for r in rows),
                              "pass_rate": sum(r["hidden"]["passed"] for r in rows)/len(rows),
                              "base_retention": sum(r["hidden"]["base_passed"] for r in rows)/base_total,
                              "runnable_rate": sum(r["hidden"]["runnable"] for r in rows)/len(rows),
                              "generation_usd": costs,
                              "mean_seconds": sum(r["elapsed_seconds"] + r["hidden"]["elapsed_seconds"] for r in rows)/len(rows),
                              "repairs": sum(r["attempts"]-1 for r in rows)})
    comparisons = []
    for model in sorted({r["model"] for r in paired}):
        for baseline in ("dna", "retrieval", "direct"):
            wins = losses = ties = 0
            for key in complete:
                if key[0] != model: continue
                values = {r["method"]: r["hidden"]["passed"] for r in groups[key]}
                diff = int(values["constrained"]) - int(values[baseline])
                wins += diff > 0
                losses += diff < 0
                ties += diff == 0
            comparisons.append({"model": model, "baseline": baseline, "wins": wins, "losses": losses, "ties": ties})
    return {"offline": accounting is None, "complete_groups": len(complete),
            "incomplete_groups": len(groups)-len(complete), "stopped": stopped, "wall_seconds": duration,
            "summary": summaries, "paired_comparisons": comparisons, "accounting": accounting, "runs": results}


def report_markdown(report):
    lines = ["# GUI DNA 组合实验", ""]
    if report["offline"]:
        lines += ["**离线流程演示：四个标签使用同一确定性参考函数组合，不是模型对照实验，不能用于支持研究假设。**", ""]
    else:
        lines += ["模型候选先通过公开检查与最多两轮修复，然后冻结。所有生成调用结束后才运行隐藏测试。", ""]
        lines += ["方法限制：自动契约归纳在开发校验中失败，最终函数库学习使用开发参考实现的人工契约注释作为种子，再做浏览器验证。此实验检验附加这些约束的效果，不能证明模型自主发现契约的能力。失败学习费用包含在项目总成本中。", ""]
    lines += [f"完整四方法配对组：{report['complete_groups']}；未完成组：{report['incomplete_groups']}。以下统计仅包含完整组，所有部分结果仍保留于 results.json。", "",
              "| 模型 | 方法 | 组合任务通过 | 基础功能保留 | 可运行 | 生成费用 USD | 平均秒数 | 修复次数 |",
              "|---|---|---:|---:|---:|---:|---:|---:|"]
    for s in report["summary"]:
        lines.append(f"| {s['model']} | {s['method']} | {s['passed']}/{s['n']} ({s['pass_rate']:.1%}) | {s['base_retention']:.1%} | {s['runnable_rate']:.1%} | {s['generation_usd']:.6f} | {s['mean_seconds']:.1f} | {s['repairs']} |")
    lines += ["", "组合任务通过：该候选全部隐藏单功能、组合与边界场景通过。基础功能保留：组合候选中独立功能场景通过数 / 总场景数。可运行：页面可加载且操作无 JavaScript 运行异常；行为错误可以仍然可运行。耗时包含生成、公开检查、修复和最终隐藏评测，不含函数库构建。", ""]
    if report["accounting"]:
        acc = report["accounting"]
        lines += [f"项目账本已结算费用 **${acc['actual_usd']:.6f}**，其中函数库构建 **${acc['library_usd']:.6f}**（单独记录，只计一次）。包含未结算预留的最大记账敞口 ${acc['exposure_usd']:.6f}；未结算调用 {acc['unsettled_calls']}。表中生成费用不含函数库；项目总成本包含全部已结算调用及其他/部分运行。金额按调用向上取整到微美元。", ""]
    if report["stopped"]:
        lines += [f"停止原因：{report['stopped']}", ""]
    if not report["offline"]:
        for p in report["paired_comparisons"]:
            lines.append(f"- {p['model']}：约束方法相对 {p['baseline']}，胜 {p['wins']} / 负 {p['losses']} / 平 {p['ties']}。")
        lines += ["", "只有两个模型中 constrained 都高于 dna 和 retrieval、且基础功能保留率不下降，才将结果视为继续研究的积极信号。持平或下降按负结果报告。每个任务仅两次采样，固定模板和窄领域可能导致天花板效应；本实验不提供统计显著性或独特性主张。"]
    failures = [(r, c) for r in report["runs"] for c in r["hidden"]["cases"] if not c["passed"]]
    if failures:
        lines += ["", "失败证据（全部轨迹与截图见各候选 hidden 目录）：", ""]
        for r, c in failures[:12]:
            lines.append(f"- {r['model']} / {r['method']} / {r['task_id']} / {c['name']}：{c.get('failure','')[:180]}。截图：{c.get('screenshot','无')}。")
    return "\n".join(lines) + "\n"
