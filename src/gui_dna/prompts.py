"""Explicit context boundary: only public requirements and frozen dev artifacts."""
import json

INTERFACE = """Implement native JavaScript for a fixed HTML renderer. Return JSON only:
{"decomposition": ["short implementation steps"], "shared_state": ["state relationships"], "code": "complete JavaScript"}.
Code must assign window.candidate = {reduce(state,event), select(state)}.
reduce receives a deep copy of the current state, may mutate it, MUST return the entire state.
select is pure, returns {items: visible item objects, total: matching count BEFORE pagination, pages: page count}.
Do not access DOM, network, storage, __gui, or global initial data. All inputs come from state.
State: {items:[{id:number,name:string,category:'A'|'B'|'C',score:number}],enabled:[feature names],query:'',filter:'all',sort:'none',page:1,pageSize:3,editing:null,history:[]}.
editing is null or a COPY of a full item. History entries are {item:full item,index:original array index}.
Preserve fields and ids. No extra item fields. No HTML or external dependencies. Disabled features have default state.
Events: {type:'search',value:string}, {type:'filter',value:'all'|'A'|'B'|'C'}, {type:'sort',value:'none'|'name-asc'|'score-desc'},
{type:'page',value:number}, {type:'edit',id:number}, {type:'draft',field:'name'|'category'|'score',value:string|number},
{type:'save'}, {type:'cancel'}, {type:'delete',id:number}, {type:'undo'}.
Only enabled feature events are sent. Empty undo is possible. page values outside range must be clamped.
Without pagination return ALL matching items, pages=1 and page=1. Data is JSON-compatible; names use ASCII lexical comparison.
The fixed renderer and trace logger handle event binding, rendering and cloning, but no business logic.
"""


def generation_messages(task, method, library, examples):
    user = {"requirement": task["requirement"], "features": task["features"], "example_initial_state": task["initial"]}
    instruction = INTERFACE
    if method == "direct":
        instruction += "\nImplement the requested behavior directly."
    elif method == "retrieval":
        instruction += "\nUse these nearest development implementations as examples."
        user["retrieved_development_examples"] = examples
    else:
        instruction += "\nDecompose the requirement, select reusable functions from the frozen library, and compose their code with any necessary glue. Include function names in decomposition."
        allowed = ("name", "feature", "code", "requires", "description")
        if method == "constrained":
            allowed += ("reads", "writes", "pre", "post")
            instruction += "\nExplicitly reconcile shared state reads/writes and satisfy the attached executable pre/post assertions. These are empirically checked contracts, not proofs."
        user["functions"] = [{k: v for k, v in f.items() if k in allowed} for f in library["functions"]]
    return [{"role": "system", "content": instruction}, {"role": "user", "content": json.dumps(user, ensure_ascii=False)}]


def library_messages(records, annotations):
    instruction = """Learn a reusable GUI function library from these 16 tested development implementations and requirements.
Deduplicate shared abstractions, document interfaces and dependencies, infer state read/write sets and executable before/after constraints.
The supplied development_annotations are human-authored contracts attached to the tested reference primitives.
Use their validated pre/post semantics as seeds when extracting the library; preserve these semantics exactly.
Do not invent stronger assertions that reject valid development behavior. This is annotation-guided extraction,
not a claim of autonomous contract discovery.
Return JSON {"functions":[...]}, exactly eight functions. The exact (name, feature) pairs are:
("deriveView", "core"), ("search", "search"), ("filter", "filter"), ("sort", "sort"),
("pagination", "pagination"), ("edit", "edit"), ("removeItem", "delete"), ("undo", "undo").
The name field is a JavaScript identifier, NEVER a slash-separated label.
Retain these interface names for the validation adapter, but extract/refine bodies from the corpus.
deriveView(s) returns {items,total,pages}; all other functions (s,e) mutate s in-place, returning nothing.
edit handles edit,draft,save,cancel; pagination handles page. The adapter calls one event function then clamps s.page using deriveView(s).pages.
Each entry MUST have name,feature,description,requires (function-name array),reads (state-field array),writes (state-field array),code (a function declaration),pre,post.
pre/post are JavaScript boolean EXPRESSIONS using only before,event,after,beforeView,afterView and standard JavaScript.
In assertions the event variable is named event, NEVER e or s. These are expressions, not function declarations.
before is the state BEFORE the whole event, after is the state AFTER the adapter's page clamping.
For example, a search predicate can reference event.value and after.query. A pagination postcondition MUST
account for the adapter clamping to afterView.pages, including requests for page 999 and page 0.
An undo with empty history is valid and must leave state unchanged. Deletion's target exists in before.items and is absent from after.items.
For edit, include an assertion that draft/cancel leave items unchanged; saving may change items.
before and after are separately cloned JSON values: compare arrays/objects structurally with JSON.stringify, NEVER with reference equality.
The core postcondition must include the page range and item-id uniqueness. Do not use a constant-true postcondition.
They run on relevant events only; core runs on every event. All pre and post assertions must be valid for the corpus.
Do not hardcode data or task ids. Do not use hidden combinations or invent additional features. Include useful nontrivial constraints, e.g. draft/cancel preserve items, page bounds, undo consumes history.
"""
    return [{"role": "system", "content": instruction + "\nState:" + INTERFACE.split("State:", 1)[1].split("Events:")[0]},
            {"role": "user", "content": json.dumps({"tested_development_implementations": records,
                                                       "development_annotations": annotations}, ensure_ascii=False)}]
