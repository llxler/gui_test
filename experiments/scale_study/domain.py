"""Public requirements, immutable primitives, and typed composition; no test data."""
from copy import deepcopy
import json
import re

from gui_dna.tasks import initial_state, development_items
from gui_dna.library import digest
from gui_dna.followup.domain import atomic_library, EVENTS
from gui_dna.prompts import INTERFACE

METHODS = ['dna', 'linked_js', 'plan_unchecked', 'plan_checked']
FAMILIES = [
    ['search', 'filter', 'pagination'], ['edit', 'filter', 'pagination'],
    ['edit', 'sort', 'delete', 'undo'], ['search', 'sort', 'pagination', 'edit'],
    ['filter', 'sort', 'delete', 'undo', 'pagination'], ['search', 'edit', 'delete', 'undo'],
    ['filter', 'edit', 'delete', 'undo', 'pagination'],
    ['search', 'filter', 'sort', 'pagination', 'edit', 'delete', 'undo'],
]
POLICY_BITS = [0, 31, 4, 24, 2, 18, 10, 21, 1, 17, 8, 30, 6, 25, 11, 20]


def tasks():
    result = []
    for i, bits in enumerate(POLICY_BITS):
        fs = FAMILIES[i // 2]
        policy = {'prefix': bool(bits & 1) and 'search' in fs,
                  'id_ties': bool(bits & 2) and 'sort' in fs,
                  'cancel_view': bool(bits & 4) and 'edit' in fs,
                  'keep_page': bool(bits & 8) and 'pagination' in fs,
                  'append_undo': bool(bits & 16) and 'undo' in fs}
        rules = ['Build the requested list manager. Only the listed enabled features are active.',
                 'Preserve canonical items and stable IDs. History contains deletions only, never edits.',
                 'Selectors are pure. Apply enabled search/filter/order before pagination; total is the count before pagination.',
                 'Sort none restores current canonical array order. Disabled pagination shows all matches with page=pages=1.',
                 'Clamp page after every event, including save/delete/undo; empty matches have page 1.']
        if 'search' in fs:
            rules.append('Search names case-insensitively after trimming the query; match '+('only name PREFIXES.' if policy['prefix'] else 'any name SUBSTRING.'))
        if 'filter' in fs: rules.append('Category filter supports all, A, B, C.')
        if 'sort' in fs:
            rules.append('Sort name-asc uses lowercase ASCII lexical order; score-desc uses descending numeric score. Equal keys '+('break ties by ascending numeric ID.' if policy['id_ties'] else 'retain current canonical array order.'))
        rules.append('On search/filter/sort events, '+('retain the current page and clamp it to the new range.' if policy['keep_page'] else 'reset page to 1.'))
        if 'edit' in fs:
            rules += ['Edit a copy; draft never mutates items; save replaces by stable ID and closes editor; cancel discards the draft.',
                      'On every search/filter/sort/page event, '+('discard any draft and close the editor, including no-op view events.' if policy['cancel_view'] else 'preserve the draft exactly, even when its item becomes invisible.')]
        if 'delete' in fs: rules.append('Delete by stable ID, push {item,index} to history; close the draft only when deleting its own item.')
        if 'undo' in fs:
            rules.append('Undo consumes the last deletion once, preserves any current draft, and '+('appends the restored item to the END of canonical items.' if policy['append_undo'] else 'restores the item at its recorded canonical array index.')+' Empty undo does nothing; never duplicate an existing ID.')
        result.append({'id': f's3-{i+1:02}', 'family': i//2, 'features': fs,
                       'requirement': ' '.join(rules), 'policy': policy,
                       'initial': initial_state(development_items(), fs)})
    return result


def library():
    old = atomic_library()
    keep = ['filterRows', 'pageRows', 'normalizePage', 'pagination', 'edit', 'removeItem']
    functions = [deepcopy(f) for f in old['functions'] if f['name'] in keep]
    for f in functions:
        f.pop('pre', None); f.pop('post', None)
    def add(name, kind, feature, reads, writes, description, code):
        functions.append({'name': name, 'kind': kind, 'feature': feature, 'reads': reads,
                          'writes': writes, 'description': description, 'code': code})
    for feature, field in [('search', 'query'), ('filter', 'filter'), ('sort', 'sort')]:
        for keep_page in [False, True]:
            name = feature + ('Keep' if keep_page else 'Reset')
            add(name, 'event', feature, ['page'], [field] + ([] if keep_page else ['page']),
                f'Handles {feature}; set {field} from e.value; '+('retain page (caller clamps).' if keep_page else 'reset page to 1.'),
                f'function {name}(s,e){{s.{field}=e.value;'+('' if keep_page else 's.page=1;')+'}')
    for prefix in [False, True]:
        name = 'searchPrefix' if prefix else 'searchContains'
        add(name, 'rows', 'search', ['query'], [], 'Case-insensitive trimmed '+('prefix' if prefix else 'substring')+' name match.',
            f'function {name}(rows,s){{return rows.filter(x=>x.name.toLowerCase().'+('startsWith' if prefix else 'includes')+'(s.query.trim().toLowerCase()));}')
    for id_ties in [False, True]:
        name = 'sortById' if id_ties else 'sortStable'
        add(name, 'rows', 'sort', ['sort'], [], 'name-asc/score-desc; ties '+('by numeric ID ascending' if id_ties else 'retain canonical input order')+'; none copies input.',
            f"function {name}(rows,s){{const out=rows.slice();if(s.sort==='none')return out;return out.sort((a,b)=>{{let d=s.sort==='score-desc'?b.score-a.score:(a.name.toLowerCase()<b.name.toLowerCase()?-1:a.name.toLowerCase()>b.name.toLowerCase()?1:0);return d"+('||a.id-b.id' if id_ties else '')+';});}')
    for append in [False, True]:
        name = 'undoAppend' if append else 'undoOriginal'
        add(name, 'event', 'undo', ['history', 'items'], ['history', 'items'],
            'Pop deletion once; no duplicate IDs; preserve draft; restore '+('at end.' if append else 'at original index.'),
            f'function {name}(s,e){{const x=s.history.pop();if(x&&!s.items.some(y=>y.id===x.item.id))'+('s.items.push(x.item);' if append else 's.items.splice(x.index,0,x.item);')+'}')
    add('cancelDraftOnView', 'after', 'edit', ['editing'], ['editing'],
        'After search/filter/sort/page events, discard draft, including no-op events. Other events unchanged.',
        "function cancelDraftOnView(s,e){if(['search','filter','sort','page'].includes(e.type))s.editing=null;}")
    add('preserveDraft', 'after', 'edit', [], [], 'No-op after hook: retain draft across view events.', 'function preserveDraft(s,e){}')
    for f in functions:
        f.setdefault('kind', 'rows' if f['name'] in ['filterRows', 'pageRows'] else 'after' if f['name']=='normalizePage' else 'event')
        params = re.search(r'function\s+\w+\s*\(([^)]*)\)', f['code']).group(1)
        f['signature'] = f['name']+'('+params+')'
        f['returns'] = '{items,total,pages}' if f['name']=='pageRows' else 'new rows array' if f['kind']=='rows' else 'undefined; mutates s in place'
    data = {'origin': 'Human semantic variants of v2 frozen library; no learning claim', 'source_sha256': old['sha256'], 'functions': functions}
    data['sha256'] = digest(data)
    return data


ROUTES = {'search': ['searchReset', 'searchKeep'], 'filter': ['filterReset', 'filterKeep'],
          'sort': ['sortReset', 'sortKeep'], 'page': ['pagination'],
          **{e: ['edit'] for e in ['edit', 'draft', 'save', 'cancel']},
          'delete': ['removeItem'], 'undo': ['undoOriginal', 'undoAppend']}
STAGES = {'search': ['searchContains', 'searchPrefix'], 'filter': ['filterRows'], 'sort': ['sortStable', 'sortById']}


def compile_plan(plan, features, lib, checked=True):
    """Task-policy-blind compiler: validates effects/coverage, never expected semantics."""
    if not isinstance(plan, dict): raise ValueError('plan must be an object')
    view, routes, after = plan.get('view'), plan.get('handlers'), plan.get('after')
    if not isinstance(view, list) or not isinstance(routes, dict) or not isinstance(after, list):
        raise ValueError('Required fields: view array, handlers object, after array')
    lookup = {f['name']: f for f in lib['functions']}
    if any(not isinstance(n, str) or n not in lookup for n in [*view, *routes.values(), *after]):
        raise ValueError('Unknown function name')
    if set(routes) - ROUTES.keys(): raise ValueError('Unknown event name')
    # Feature-aware linking shared by both plan arms; only known disabled nodes removed.
    enabled = {e for f in features for e in EVENTS[f]}
    routes = {e:n for e,n in routes.items() if e in enabled}
    view = [n for n in view if lookup[n]['feature'] in ['core', *features]]
    after = [n for n in after if lookup[n]['feature'] in ['core', *features]]
    if checked:
        if set(routes) != enabled or any(n not in ROUTES[e] for e,n in routes.items()):
            raise ValueError('Missing or invalid enabled-event routes; allowed: '+json.dumps({e:ROUTES[e] for e in sorted(enabled)}))
        if not view or view[-1]!='pageRows' or view.count('pageRows')!=1:
            raise ValueError('Use pageRows exactly once, last after all row transforms')
        if any(lookup[n]['kind']!='rows' or lookup[n]['writes'] for n in view):
            raise ValueError('View must contain pure row functions only')
        for f in features:
            if f in STAGES and sum(n in STAGES[f] for n in view)!=1:
                raise ValueError('Choose exactly one enabled '+f+' row stage')
        if any(lookup[n]['kind']!='after' for n in after) or after.count('normalizePage')!=1 or after[-1]!='normalizePage':
            raise ValueError('After hooks must end in exactly one normalizePage')
        if 'edit' in features and sum(n in ['preserveDraft','cancelDraftOnView'] for n in after)!=1:
            raise ValueError('Choose exactly one draft policy after hook')
    selected = set(view + list(routes.values()) + after)
    code = '\n'.join(f['code'] for f in lib['functions'] if f['name'] in selected)
    matching = 'let rows=s.items.slice();'+''.join(f'rows={n}(rows,s);' for n in view if n!='pageRows')+'return rows;'
    pipeline = 'let rows=s.items.slice();'+''.join(f'rows={n}(rows,s);' for n in view)+'return rows;'
    branches = ''.join(f'case {json.dumps(e)}:{n}(s,e);break;' for e,n in routes.items())
    hooks = ''.join('normalizePage(s,matching(s).length);' if n=='normalizePage' else f'{n}(s,e);' for n in after)
    return code+'\nfunction matching(s){'+matching+'}\nwindow.candidate={select(s){'+pipeline+'},reduce(s,e){switch(e.type){'+branches+'}'+hooks+'return s;}};'


def reference_plan(task, defaults=False):
    """Calibration ceiling has structured policy access; never shown to generators."""
    p = {k: False for k in task['policy']} if defaults else task['policy']
    features = task['features']
    selectors = {'search':'searchPrefix' if p['prefix'] else 'searchContains', 'filter':'filterRows', 'sort':'sortById' if p['id_ties'] else 'sortStable'}
    routes = {}
    for f in features:
        for e in EVENTS[f]:
            routes[e] = f+('Keep' if p['keep_page'] else 'Reset') if f in ['search','filter','sort'] else ('undoAppend' if p['append_undo'] else 'undoOriginal') if f=='undo' else ROUTES[e][0]
    return {'view':[selectors[f] for f in features if f in selectors]+['pageRows'], 'handlers':routes,
            'after':(['cancelDraftOnView' if p['cancel_view'] else 'preserveDraft'] if 'edit' in features else [])+['normalizePage']}


def messages_for(task, method, lib):
    # Explicit allowlist prevents structured answers and evaluator policy from entering context.
    data = {k:task[k] for k in ['requirement','features','initial']}
    data['functions'] = [{k:v for k,v in f.items() if k!='code' or method=='dna'} for f in lib['functions']]
    common = ('Compose immutable functions to implement the exact requested behavior. Distinguish semantic variants. '
              'Do not access DOM/network/storage. Explain a short decomposition. Interface: reduce receives'+INTERFACE.split('reduce receives',1)[1])
    if method=='dna':
        instruction = common+'\nReturn JSON {"decomposition":[...],"code":"complete JS assigning window.candidate={reduce,select}"}. Include needed function definitions and glue.'
    elif method=='linked_js':
        instruction = common+'\nFunctions are already preloaded under their names. Return JSON {"decomposition":[...],"code":"glue JS assigning window.candidate={reduce,select}"}. Do not redefine functions.'
    else:
        instruction = common+('\nReturn JSON {"decomposition":[...],"plan":{"view":["row function names"],"handlers":{"event type":"function name"},"after":["after hook names"]}}. No code. '
            'Choose semantic variants from the requirement. Include each enabled search/filter/sort transform once; pageRows must occur exactly once last. '
            'Bind all enabled events, including all four edit/draft/save/cancel routes. Choose one draft policy after-hook when edit is enabled. '
            'End after hooks with normalizePage: the compiler passes it the filtered/ordered count before pagination, after every event. '
            'Known disabled nodes are pruned. Function bodies are frozen. Return only this plan schema, never JavaScript.')
    return [{'role':'system','content':instruction},{'role':'user','content':json.dumps(data,ensure_ascii=False)}]
