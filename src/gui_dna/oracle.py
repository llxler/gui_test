"""Independent Python oracle. Imported by the evaluator only, never by prompts."""
from copy import deepcopy
from math import ceil


def project(s):
    rows = [dict(x) for x in s["items"] if s["query"].strip().lower() in x["name"].lower()
            and (s["filter"] == "all" or x["category"] == s["filter"])]
    if s["sort"] == "name-asc":
        rows = sorted(rows, key=lambda x: x["name"].lower())
    elif s["sort"] == "score-desc":
        rows = sorted(rows, key=lambda x: -x["score"])
    total = len(rows)
    pages = max(1, ceil(total / s["pageSize"])) if "pagination" in s["enabled"] else 1
    if "pagination" in s["enabled"]:
        rows = rows[(s["page"] - 1) * s["pageSize"]:s["page"] * s["pageSize"]]
    return {"items": rows, "total": total, "pages": pages}


def transition(before, event):
    s, e = deepcopy(before), event
    action = e["type"]
    if action in ("search", "filter", "sort"):
        s[{"search": "query", "filter": "filter", "sort": "sort"}[action]] = e["value"]
        s["page"] = 1
    elif action == "page":
        s["page"] = int(e["value"])
    elif action == "edit":
        s["editing"] = next(deepcopy(x) for x in s["items"] if x["id"] == e["id"])
    elif action == "draft" and s["editing"]:
        s["editing"][e["field"]] = e["value"]
    elif action == "cancel":
        s["editing"] = None
    elif action == "save" and s["editing"]:
        s["items"] = [deepcopy(s["editing"]) if x["id"] == s["editing"]["id"] else x for x in s["items"]]
        s["editing"] = None
    elif action == "delete":
        index = next(i for i, x in enumerate(s["items"]) if x["id"] == e["id"])
        s["history"].append({"item": s["items"].pop(index), "index": index})
        if s["editing"] and s["editing"]["id"] == e["id"]:
            s["editing"] = None
    elif action == "undo" and s["history"]:
        entry = s["history"].pop()
        s["items"].insert(entry["index"], entry["item"])
    s["page"] = max(1, min(s["page"], project(s)["pages"]))
    return s
