"""Fixed renderer and instrumentation, shared without feature logic by every arm."""
import json
import re
from pathlib import Path

ASSETS = Path(__file__).with_name("assets")
EVENTS = {"search": ["search"], "filter": ["filter"], "sort": ["sort"],
          "pagination": ["page"], "edit": ["edit", "draft", "save", "cancel"],
          "delete": ["delete"], "undo": ["undo"]}


def reference_functions():
    source = (ASSETS / "reference.js").read_text()
    return [{**json.loads(meta), "code": code.strip()}
            for meta, code in re.findall(r"// @function (.*?)\n(.*?)// @end", source, re.S)]


def compose(functions, features):
    selected = [f for f in functions if f["feature"] in ["core", *features]]
    code = "\n".join(f["code"] for f in selected)
    branches = []
    for f in selected:
        for event in EVENTS.get(f["feature"], []):
            branches.append(f"case {json.dumps(event)}: {f['name']}(s,e); break;")
    return code + "\nwindow.candidate = { select: deriveView, reduce(s,e) { switch(e.type) {" + "\n".join(branches) + "} s.page = Math.max(1,Math.min(s.page,deriveView(s).pages)); return s; } };\n"


def reference_code(features):
    return compose(reference_functions(), features)


def write_app(path, task, code):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    template = (ASSETS / "shell.html").read_text()
    # Escape script-closing tokens; candidate source executes inside a dedicated script.
    initial = json.dumps(task["initial"], ensure_ascii=False).replace("<", "\\u003c")
    html = template.replace("/*__INITIAL__*/", initial).replace("/*__CANDIDATE__*/", code.replace("</script", "<\\/script"))
    path.write_text(html)
    return path
