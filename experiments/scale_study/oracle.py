"""Independent evaluator semantics. Not imported by prompt construction/compiler."""
from copy import deepcopy
from math import ceil


def project(s, policy):
    rows = deepcopy(s['items'])
    if 'search' in s['enabled']:
        q = s['query'].strip().lower()
        rows = [x for x in rows if (x['name'].lower().startswith(q) if policy['prefix'] else q in x['name'].lower())]
    if 'filter' in s['enabled'] and s['filter']!='all': rows = [x for x in rows if x['category']==s['filter']]
    if 'sort' in s['enabled'] and s['sort']!='none':
        def key(x):
            value = x['name'].lower() if s['sort']=='name-asc' else -x['score']
            return (value,x['id']) if policy['id_ties'] else (value,)
        rows.sort(key=key)
    total = len(rows)
    active = 'pagination' in s['enabled']
    pages = max(1, ceil(total/s['pageSize'])) if active else 1
    if active: rows = rows[(s['page']-1)*s['pageSize']:s['page']*s['pageSize']]
    return {'items':rows, 'total':total, 'pages':pages}


def transition(before, event, policy):
    s, e = deepcopy(before), event
    kind = e['type']
    if kind in ('search','filter','sort'):
        s[{'search':'query','filter':'filter','sort':'sort'}[kind]] = e['value']
        if not policy['keep_page']: s['page']=1
    elif kind=='page': s['page']=int(e['value'])
    elif kind=='edit': s['editing']=next(deepcopy(x) for x in s['items'] if x['id']==e['id'])
    elif kind=='draft' and s['editing']: s['editing'][e['field']]=e['value']
    elif kind=='cancel': s['editing']=None
    elif kind=='save' and s['editing']:
        s['items']=[deepcopy(s['editing']) if x['id']==s['editing']['id'] else x for x in s['items']]
        s['editing']=None
    elif kind=='delete':
        i=next(i for i,x in enumerate(s['items']) if x['id']==e['id'])
        s['history'].append({'item':s['items'].pop(i),'index':i})
        if s['editing'] and s['editing']['id']==e['id']:s['editing']=None
    elif kind=='undo' and s['history']:
        entry=s['history'].pop()
        if not any(x['id']==entry['item']['id'] for x in s['items']):
            s['items'].insert(len(s['items']) if policy['append_undo'] else entry['index'],entry['item'])
    if kind in ('search','filter','sort','page') and policy['cancel_view']:s['editing']=None
    s['page']=max(1,min(s['page'],project(s,policy)['pages']))
    return s
