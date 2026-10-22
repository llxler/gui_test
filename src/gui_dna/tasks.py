"""Public requirements and development data. No held-out fixtures live here."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[2]
FEATURES = ("search", "filter", "sort", "pagination", "edit", "delete", "undo")
RULES = {
    "search": "Case-insensitive name substring search; trim the query for matching. Changing search resets page to 1.",
    "filter": "Category filter: all, A, B, C. Changing filter resets page to 1.",
    "sort": "Sort none (original array order), name-asc (lowercase ASCII lexical), or score-desc; ties retain array order. Changing sort resets page to 1.",
    "pagination": "Page size is 3 by default. Filter and search, then sort, then paginate. Total is before pagination. Pages=max(1,ceil(total/pageSize)); clamp page after every event; empty results have page 1.",
    "edit": "Edit a copy of the selected item. Draft changes never mutate items. Cancel discards the draft. Save replaces that item by stable id, then recomputes filtering/sorting/pagination; only name/category/score are editable.",
    "delete": "Delete by stable id and append {item,index} to history (original array index). Immediately recompute the view and clamp page. Close draft if its item is deleted.",
    "undo": "Pop the most recent deletion and restore it at its recorded array index, at most once; empty undo is a no-op. Recompute the view and clamp page. Undo-only tasks start with a preloaded deletion history.",
}
COMBINATIONS = [
    ("search", "pagination"), ("filter", "pagination"), ("edit", "filter"),
    ("edit", "sort"), ("delete", "pagination"), ("delete", "undo"),
    ("search", "edit", "pagination"), ("filter", "sort", "delete"),
]


def initial_state(items, features, history=None):
    return {"items": items, "enabled": list(features), "query": "", "filter": "all",
            "sort": "none", "page": 1, "pageSize": 3, "editing": None,
            "history": history or []}


def development_items(variant=0):
    names = ["Alpha", "Beta", "Almond", "Delta", "Atlas", "Berry", "Aloe"]
    return [{"id": i + 1 + variant * 20, "name": n if not variant else n + " sample",
             "category": "ABC"[i % 3], "score": [7, 3, 7, 1, 9, 5, 2][i]}
            for i, n in enumerate(names)]


def make_task(task_id, features, variant=0):
    items = development_items(variant)
    history = []
    if features == ["undo"]:
        history = [{"item": items.pop(2), "index": 2}]
    requirement = "Build a local single-page list manager. " + " ".join(RULES[f] for f in features)
    return {"id": task_id, "features": features, "requirement": requirement,
            "initial": initial_state(items, features, history)}


def dev_tasks():
    tasks = [make_task(f"dev-{f}-{v + 1}", [f], v) for f in FEATURES for v in range(2)]
    return tasks + [make_task("dev-search-sort", ["search", "sort"]),
                    make_task("dev-filter-delete", ["filter", "delete"])]


def test_tasks():
    return [make_task("test-" + "-".join(fs), list(fs)) for fs in COMBINATIONS]


def task_by_id(task_id):
    return next(t for t in dev_tasks() + test_tasks() if t["id"] == task_id)


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)
