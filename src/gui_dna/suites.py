"""Evaluator-only fixtures. Hidden examples are never included in LLM context."""
from copy import deepcopy
from .tasks import initial_state


def action(kind, value=None, **kwargs):
    return {"type": kind, **({"value": value} if value is not None else {}), **kwargs}


def basic_steps(feature, hidden=False):
    a = action
    return {
        "search": [a("search", " AL "), a("search", "not-present-920"), a("search", "")],
        "filter": [a("filter", "B"), a("filter", "C"), a("filter", "all")],
        "sort": [a("sort", "score-desc"), a("sort", "name-asc"), a("sort", "none")],
        "pagination": [a("page", 2), a("page", 999), a("page", 0), a("page", 1)],
        "edit": [a("edit", pick=0), a("draft", "Temporary", field="name"), a("cancel"),
                 a("edit", pick=0), a("draft", "Al edited" if hidden else "Saved", field="name"),
                 a("draft", "C", field="category"), a("draft", -4, field="score"), a("save")],
        "delete": [a("delete", pick=0), a("delete", pick=0)],
        "undo": [a("undo"), a("undo"), a("undo")],
    }[feature]


def hidden_items():
    # New ids, duplicate names, ties, negative scores, enough category-A rows to paginate.
    return [{"id": 101 + 7*i, "name": name, "category": cat, "score": score}
            for i, (name, cat, score) in enumerate([
                ("alpine", "A", 0), ("ALPHA", "A", 8), ("Basil", "B", -2),
                ("Kale", "A", 8), ("Algae", "A", 5), ("ALPHA", "C", 8),
                ("Zinc", "A", -9), ("Coral", "B", 3), ("Quartz", "C", 5),
                ("almanac", "A", 0)])]


def cases(task, suite):
    hidden = suite == "hidden"
    initial = deepcopy(task["initial"])
    if hidden:
        initial = initial_state(hidden_items(), task["features"])
    result = []
    for feature in task["features"]:
        state = deepcopy(initial)
        if feature == "undo" and not state["history"]:
            state["history"] = [{"item": state["items"].pop(2), "index": 2}]
        result.append({"name": "base-" + feature, "kind": "base", "feature": feature,
                       "initial": state, "steps": basic_steps(feature, hidden)})
    if not hidden:
        # Public checker deliberately uses development data and a single operation ordering.
        if len(task["features"]) > 1:
            steps = [x for f in task["features"] for x in basic_steps(f)]
            result.append({"name": "public-composition", "kind": "composition", "initial": initial, "steps": steps})
        return result
    a = action
    key = frozenset(task["features"])
    sequences = {
        frozenset(["search", "pagination"]): [
            [a("page", 4), a("search", "al"), a("page", 2), a("search", "quartz"), a("search", "missing"), a("search", "")],
            [a("search", " AL "), a("page", 99), a("search", "a"), a("page", 2)]],
        frozenset(["filter", "pagination"]): [
            [a("page", 4), a("filter", "A"), a("page", 2), a("filter", "C"), a("page", 99), a("filter", "all")],
            [a("filter", "B"), a("page", 0), a("filter", "A"), a("page", 2), a("filter", "B")]],
        frozenset(["edit", "filter"]): [
            [a("filter", "A"), a("edit", pick=0), a("draft", "B", field="category"), a("save"), a("filter", "B")],
            [a("filter", "C"), a("edit", pick=0), a("draft", "A", field="category"), a("cancel"), a("edit", pick=0), a("draft", "B", field="category"), a("save")]],
        frozenset(["edit", "sort"]): [
            [a("sort", "score-desc"), a("edit", pick=0), a("draft", -50, field="score"), a("save"), a("sort", "none")],
            [a("sort", "name-asc"), a("edit", pick=0), a("draft", "zzzz", field="name"), a("cancel"), a("edit", pick=0), a("draft", "zzzz", field="name"), a("save")]],
        frozenset(["delete", "pagination"]): [
            [a("page", 4), a("delete", pick=0), a("delete", pick=2), a("delete", pick=1), a("delete", pick=0)],
            [a("page", 99)] + [a("delete", pick=0) for _ in range(10)]],
        frozenset(["delete", "undo"]): [
            [a("delete", pick=1), a("delete", pick=3), a("undo"), a("undo"), a("undo"), a("delete", pick=0), a("undo")],
            [a("delete", pick=0), a("undo"), a("undo"), a("delete", pick=9), a("undo")]],
        frozenset(["search", "edit", "pagination"]): [
            [a("search", "al"), a("page", 3), a("edit", pick=0), a("draft", "Omega", field="name"), a("save"), a("search", "omega")],
            [a("search", "alpha"), a("edit", pick=1), a("draft", "Other", field="name"), a("cancel"), a("edit", pick=0), a("draft", "Other", field="name"), a("save"), a("search", "")]],
        frozenset(["filter", "sort", "delete"]): [
            [a("filter", "A"), a("sort", "score-desc"), a("delete", pick=0), a("sort", "name-asc"), a("delete", pick=1), a("filter", "all")],
            [a("sort", "score-desc"), a("filter", "C"), a("delete", pick=0), a("delete", pick=0), a("filter", "all"), a("sort", "none")]],
    }
    for i, steps in enumerate(sequences.get(key, [])):
        result.append({"name": f"heldout-order-{i+1}", "kind": "composition", "initial": deepcopy(initial), "steps": steps})
    # Empty-state and alternate page-size checks apply across all held-out combinations.
    empty = initial_state([], task["features"])
    steps = []
    for feature in task["features"]:
        if feature == "search": steps.append(a("search", "none"))
        if feature == "filter": steps.append(a("filter", "C"))
        if feature == "sort": steps.append(a("sort", "score-desc"))
        if feature == "pagination": steps.append(a("page", 99))
        if feature == "undo": steps.append(a("undo"))
    result.append({"name": "empty-boundary", "kind": "composition", "initial": empty, "steps": steps})
    if "pagination" in task["features"]:
        alternate = deepcopy(initial)
        alternate["pageSize"] = 2
        result.append({"name": "alternate-page-size", "kind": "composition", "initial": alternate,
                       "steps": [a("page", 5), a("page", 1)]})
    return result
