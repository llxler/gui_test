"""Public domain specification and shared atomic library; no held-out fixtures."""
import json
from copy import deepcopy

from ..library import load_library, digest
from ..tasks import ROOT, make_task

METHODS = ['direct', 'retrieval', 'dna', 'metadata', 'checks', 'constrained', 'deterministic', 'compiled']
COMBINATIONS = [
    ['search', 'filter', 'pagination'],
    ['edit', 'filter', 'pagination'],
    ['edit', 'sort', 'delete', 'undo'],
    ['search', 'filter', 'sort', 'edit', 'pagination'],
    ['filter', 'edit', 'delete', 'undo', 'pagination'],
    ['search', 'filter', 'sort', 'pagination', 'edit', 'delete', 'undo'],
]
EVENTS = {'search': ['search'], 'filter': ['filter'], 'sort': ['sort'],
          'pagination': ['page'], 'edit': ['edit', 'draft', 'save', 'cancel'],
          'delete': ['delete'], 'undo': ['undo']}
HANDLERS = {'search': 'search', 'filter': 'filter', 'sort': 'sort', 'pagination': 'pagination',
            'edit': 'edit', 'delete': 'removeItem', 'undo': 'undo'}
VIEW_STEPS = {'search': 'searchRows', 'filter': 'filterRows', 'sort': 'sortRows'}


def tasks():
    result = []
    for features in COMBINATIONS:
        task = make_task('v2-' + '-'.join(features), features)
        task['requirement'] += (' History stores DELETIONS ONLY: edit/save/cancel never change history, even when undo is disabled.'
            ' Keep the entire canonical items array; select must not mutate state.'
            ' A draft survives search/filter/sort/page changes; saving updates its stable id even if off-screen.'
            ' Deleting that draft item closes the editor; deleting another item preserves the draft.'
            ' Undo never replaces or duplicates an existing item and preserves any current draft.'
            ' Disable pagination by returning all matching rows, page=1 and pages=1.'
            ' Stable ties follow current canonical array order; sort=none restores that order.')
        result.append(task)
    return result


def atomic_library():
    """Human refactoring of v1, shared by all library arms; no discovery claim."""
    original = load_library(ROOT / 'artifacts/library-live.json')
    functions = deepcopy([f for f in original['functions'] if f['feature'] != 'core'])
    for f in functions:
        f['requires'] = []
    helpers = [
        ('searchRows', 'search', ['items', 'query'],
         "function searchRows(rows,s) { return rows.filter(x=>x.name.toLowerCase().includes(s.query.trim().toLowerCase())); }"),
        ('filterRows', 'filter', ['items', 'filter'],
         "function filterRows(rows,s) { return rows.filter(x=>s.filter==='all'||x.category===s.filter); }"),
        ('sortRows', 'sort', ['items', 'sort'],
         "function sortRows(rows,s) { const out=rows.slice(); if(s.sort==='name-asc') out.sort((a,b)=>a.name.toLowerCase()<b.name.toLowerCase()?-1:a.name.toLowerCase()>b.name.toLowerCase()?1:0); if(s.sort==='score-desc') out.sort((a,b)=>b.score-a.score); return out; }"),
        ('pageRows', 'core', ['items', 'enabled', 'page', 'pageSize'],
         "function pageRows(rows,s) { const total=rows.length, active=s.enabled.includes('pagination'), pages=active?Math.max(1,Math.ceil(total/s.pageSize)):1; return {items:active?rows.slice((s.page-1)*s.pageSize,s.page*s.pageSize):rows.slice(),total,pages}; }"),
        ('normalizePage', 'core', ['enabled', 'page', 'pageSize'],
         "function normalizePage(s,total) { const pages=s.enabled.includes('pagination')?Math.max(1,Math.ceil(total/s.pageSize)):1; s.page=Math.max(1,Math.min(s.page,pages)); }")]
    for name, feature, reads, code in helpers:
        functions.append({'name': name, 'feature': feature, 'code': code,
                          'description': 'Pure rows-to-rows operation' if name.endswith('Rows') and name != 'pageRows' else
                                         'Convert ALL matching ordered rows to {items,total,pages}' if name == 'pageRows' else
                                         'Clamp s.page using the count AFTER search/filter, BEFORE pagination, after each event',
                          'reads': reads, 'writes': ['page'] if name == 'normalizePage' else [], 'requires': []})
    constraints = [f for f in functions if 'post' in f]
    constraints += [
        {'name': 'pageAndIdentity', 'feature': 'core', 'pre': 'Array.isArray(before.items)',
         'post': "after.page>=1 && after.page<=afterView.pages && new Set(after.items.map(x=>x.id)).size===after.items.length"},
        {'name': 'historyFrame', 'feature': 'core', 'pre': 'true',
         'post': "['delete','undo'].includes(event.type)||JSON.stringify(before.history)===JSON.stringify(after.history)"},
        {'name': 'itemsFrame', 'feature': 'core', 'pre': 'true',
         'post': "['save','delete','undo'].includes(event.type)||JSON.stringify(before.items)===JSON.stringify(after.items)"},
        {'name': 'draftFrame', 'feature': 'core', 'pre': 'true',
         'post': "!['search','filter','sort','page','undo'].includes(event.type)||JSON.stringify(before.editing)===JSON.stringify(after.editing)"},
    ]
    library = {'origin': 'Human decomposition of v1 frozen library, not new automatic learning',
               'source_sha256': original['sha256'], 'functions': functions, 'constraints': constraints}
    library['sha256'] = digest(library)
    return library


def expected_plan(features):
    return {'view': [VIEW_STEPS[f] for f in features if f in VIEW_STEPS] + ['pageRows'],
            'handlers': {e: HANDLERS[f] for f in features for e in EVENTS[f]},
            'normalize': 'normalizePage', 'normalize_when': 'after_each_event'}


def compile_plan(plan, features, library):
    """Check a small composition IR and emit glue; never inspect task ids or fixtures."""
    wanted = expected_plan(features)
    if not isinstance(plan, dict):
        raise ValueError('plan must be an object')
    if plan.get('handlers') != wanted['handlers']:
        raise ValueError('Event coverage/binding mismatch. Required enabled routes: ' + json.dumps(wanted['handlers']))
    view = plan.get('view')
    if not isinstance(view, list) or any(not isinstance(x, str) for x in view):
        raise ValueError('view must list atomic row functions')
    if sorted(view) != sorted(wanted['view']) or view[-1] != 'pageRows':
        raise ValueError('Use each enabled row transform once; pageRows must run last, after filtering/search and ordering')
    if plan.get('normalize') != 'normalizePage' or plan.get('normalize_when') != 'after_each_event':
        raise ValueError('Normalize page after every event with pre-pagination matching count')
    lookup = {f['name']: f for f in library['functions']}
    for name in view:
        if lookup[name]['writes']:
            raise ValueError('Selector stage may not write state')
    selected = set(view + list(wanted['handlers'].values()) + ['normalizePage'])
    code = '\n'.join(f['code'] for f in library['functions'] if f['name'] in selected)
    pipeline = 'let rows=s.items.slice();' + ''.join(f'rows={name}(rows,s);' for name in view[:-1]) + 'return rows;'
    branches = ''.join(f'case {json.dumps(e)}: {name}(s,e); break;' for e, name in plan['handlers'].items())
    return code + '\nfunction matchingRows(s){' + pipeline + '}\nwindow.candidate={' + \
        'select(s){return pageRows(matchingRows(s),s);},reduce(s,e){switch(e.type){' + branches + \
        '}normalizePage(s,matchingRows(s).length);return s;}};'
