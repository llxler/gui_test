import argparse
import json
from pathlib import Path

from .tasks import ROOT, FEATURES, make_task, task_by_id


def main():
    parser = argparse.ArgumentParser(description="DNA-inspired GUI composition research prototype")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/experiment.json")
    commands = parser.add_subparsers(dest="command", required=True)
    learn = commands.add_parser("learn-library", help="Validate development corpus, learn and freeze abstractions")
    learn.add_argument("--offline", action="store_true")
    learn.add_argument("--out", type=Path)
    generate_parser = commands.add_parser("generate", help="Generate a page using public feedback only")
    generate_parser.add_argument("--task", default="test-search-edit-pagination")
    generate_parser.add_argument("--requirement", help="Natural-language requirement within the seven-feature domain")
    generate_parser.add_argument("--features", nargs="+", choices=FEATURES)
    generate_parser.add_argument("--method", choices=["direct", "retrieval", "dna", "constrained"], default="constrained")
    generate_parser.add_argument("--model")
    generate_parser.add_argument("--offline", action="store_true")
    generate_parser.add_argument("--library", type=Path)
    generate_parser.add_argument("--out", type=Path, default=ROOT / "artifacts/demo")
    evaluation = commands.add_parser("evaluate", help="Run final held-out tests or evaluator self-check")
    evaluation.add_argument("--app", type=Path)
    evaluation.add_argument("--task", default="test-search-edit-pagination")
    evaluation.add_argument("--suite", choices=["public", "hidden"], default="hidden")
    evaluation.add_argument("--self-check", action="store_true")
    evaluation.add_argument("--out", type=Path, default=ROOT / "artifacts/evaluation")
    compare = commands.add_parser("compare", help="Run balanced four-arm experiment and produce a report")
    compare.add_argument("--offline", action="store_true")
    compare.add_argument("--library", type=Path)
    compare.add_argument("--out", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    if config["max_repairs"] not in range(3):
        parser.error("max_repairs must be 0, 1, or 2")
    if config["methods"] != ["direct", "retrieval", "dna", "constrained"]:
        parser.error("The research protocol requires the four specified methods")
    try:
        if args.command == "evaluate":
            if args.self_check:
                from .selfcheck import selfcheck
                result = selfcheck(args.out)
            else:
                from .evaluation import evaluate
                if not args.app: parser.error("--app is required unless --self-check is used")
                result = evaluate(args.app, task_by_id(args.task), args.out, args.suite)
            print(json.dumps({"passed": result["passed"], "output": str(args.out)}, ensure_ascii=False))
            raise SystemExit(0 if result["passed"] else 1)
        from .library import learn_library
        from .provider import OpenRouter
        offline = args.offline
        library_path = getattr(args, "library", None) or ROOT / ("artifacts/library-offline.json" if offline else "artifacts/library-live.json")
        if args.command == "compare":
            from .experiment import run_compare
            out = args.out or ROOT / ("artifacts/offline" if offline else "artifacts/live")
            report = run_compare(config, out, library_path, offline)
            print(json.dumps({"complete_groups": report["complete_groups"], "stopped": report["stopped"], "report": str(out / "report.md")}, ensure_ascii=False))
            if report["stopped"]: raise SystemExit(2)
            return
        provider = None if offline else OpenRouter(config)
        if args.command == "learn-library":
            library_path = args.out or library_path
            library = learn_library(library_path, offline, provider, config["library_model"])
            print(json.dumps({"library": str(library_path), "sha256": library["sha256"]}))
            return
        from .generation import generate
        library = learn_library(library_path, offline, provider, config["library_model"])
        if args.requirement:
            terms = {"search": ("search", "搜索"), "filter": ("filter", "筛选", "过滤"), "sort": ("sort", "排序"),
                     "pagination": ("pagin", "page", "分页"), "edit": ("edit", "编辑"), "delete": ("delete", "删除"), "undo": ("undo", "撤销")}
            features = args.features or [f for f, words in terms.items() if any(w in args.requirement.lower() for w in words)]
            if not features: parser.error("No supported feature recognized; specify --features")
            task = make_task("custom", features)
            task["requirement"] = args.requirement + "\n" + task["requirement"]
        else:
            task = task_by_id(args.task)
        result = generate(task, args.method, library, args.out, config, offline, provider, args.model or config["models"][0])
        print(json.dumps({"app": str(args.out / "index.html"), "public_passed": result["public_passed"]}, ensure_ascii=False))
    except (ValueError, RuntimeError, KeyError) as error:
        parser.exit(2, f"gui-dna: {error}\n")


if __name__ == "__main__":
    main()
