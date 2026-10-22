"""Fresh fixtures and operation seeds, isolated from all generation context."""
from copy import deepcopy
import random

from gui_dna.tasks import initial_state
from .oracle import project, transition


def fresh_items(seed, count):
    rng=random.Random(seed)
    ids=rng.sample(range(2001,9500),count)
    names=['bramble','Amber','Jade','lamplight','AMBER','elm','garnet','bamboo','Quartz','alpha']
    return [{'id':ids[i],'name':names[i%len(names)],'category':'CBACBAAB'[i%8],
             'score':[-8,17,17,0,40,-8][i%6]} for i in range(count)]


def trajectory(initial, policy, seed, decisions):
    rng=random.Random(seed);state=deepcopy(initial);steps=[]
    def emit(kind,**fields):
        nonlocal state
        e={'type':kind,**fields};steps.append(e);state=transition(state,e,policy)
    for _ in range(decisions):
        f=rng.choice(state['enabled']);visible=project(state,policy)['items']
        if f=='search':emit('search',value=rng.choice(['am',' AM ','a','','zz-never']))
        elif f=='filter':emit('filter',value=rng.choice(['all','A','B','C']))
        elif f=='sort':emit('sort',value=rng.choice(['none','name-asc','score-desc']))
        elif f=='pagination':emit('page',value=rng.choice([0,1,2,4,999]))
        elif f=='undo':emit('undo')
        elif f=='delete' and visible:emit('delete',id=rng.choice(visible)['id'])
        elif f=='edit' and visible:
            item=rng.choice(visible);emit('edit',id=item['id'])
            field=rng.choice(['name','category','score'])
            value=rng.choice(['am saved','Jasper','same']) if field=='name' else rng.choice(['A','B','C']) if field=='category' else rng.choice([-33,0,72])
            emit('draft',field=field,value=value)
            views=[x for x in ['filter','sort','search','pagination'] if x in state['enabled']]
            if views and rng.random()<.7:
                v=rng.choice(views)
                emit('page' if v=='pagination' else v,value={'filter':'B','sort':'score-desc','search':'am','pagination':2}[v])
            if state['editing'] is not None:emit(rng.choice(['save','cancel','save']))
    return steps


def cases(task, hidden):
    fs,p=task['features'],task['policy']
    rows=fresh_items(51019,31) if hidden else deepcopy(task['initial']['items'])
    result=[]
    def add(name,kind,steps,initial=None):
        result.append({'name':name,'kind':kind,'initial':initial or initial_state(deepcopy(rows),fs),'steps':steps})
    for f in fs:
        s=initial_state(deepcopy(rows),fs)
        if f=='search':steps=[{'type':'search','value':v} for v in ['am' if hidden else 'ta','  AL ','nothing-884','']]
        elif f=='filter':steps=[{'type':'filter','value':v} for v in ['B','C','all']]
        elif f=='sort':
            s['items'].reverse()
            steps=[{'type':'sort','value':v} for v in ['score-desc','name-asc','none']]
        elif f=='pagination':steps=[{'type':'page','value':v} for v in [2,999,0,1]]
        elif f=='edit':
            i=rows[0]['id'];steps=[{'type':'edit','id':i},{'type':'draft','field':'name','value':'altered'},
                                 {'type':'cancel'},{'type':'edit','id':i},{'type':'draft','field':'score','value':-44},{'type':'save'}]
        elif f=='delete':steps=[{'type':'delete','id':rows[1]['id']}]
        else:
            s['history']=[{'item':s['items'].pop(1),'index':1}]
            steps=[{'type':'undo'},{'type':'undo'}]
        add('base-'+f,'base',steps,s)
    # Directed interactions expose semantic distinctions through public behavior.
    s=initial_state(deepcopy(rows),fs);steps=[]
    def emit(kind,**fields):
        nonlocal s
        e={'type':kind,**fields};steps.append(e);s=transition(s,e,p)
    if 'pagination' in fs:emit('page',value=2)
    if 'filter' in fs:emit('filter',value='all')
    elif 'sort' in fs:emit('sort',value='score-desc')
    elif 'search' in fs:emit('search',value='')
    visible=project(s,p)['items']
    if 'edit' in fs and visible:
        emit('edit',id=visible[0]['id']);emit('draft',field='name',value='temporary')
        for f in ['filter','search','sort','pagination']:
            if f in fs:
                emit('page' if f=='pagination' else f,value={'filter':'all','search':'','sort':'name-asc','pagination':1}[f]);break
        if s['editing']:emit('cancel')
    if 'sort' in fs:emit('sort',value='none')
    if 'pagination' in fs:emit('page',value=1)
    if 'delete' in fs and project(s,p)['items']:
        emit('delete',id=project(s,p)['items'][0]['id'])
        if 'undo' in fs:emit('undo');emit('undo')
    add('semantic-interactions','composition',steps)
    seeds=[67103,67217,67511] if hidden else [9109]
    for i,seed in enumerate(seeds):
        s=initial_state(fresh_items(seed,17+i*12) if hidden else deepcopy(rows),fs)
        s['pageSize']=[2,5,8][i] if hidden else 3
        if hidden and 'sort' in fs:s['sort']='name-asc' if i==1 else 'score-desc'
        if hidden and i==1 and 'filter' in fs:s['filter']='C'
        add(('hidden' if hidden else 'public')+f'-sequence-{i}','composition',trajectory(s,p,seed,70 if hidden else 15),s)
    if hidden:
        s=initial_state([],fs)
        add('empty','composition',trajectory(s,p,69557,18),s)
        if 'delete' in fs:
            steps=([{'type':'page','value':999}] if 'pagination' in fs else [])
            steps += [{'type':'delete','pick':0} for _ in rows]
            if 'undo' in fs:steps += [{'type':'undo'} for _ in range(len(rows)+2)]
            add('drain-restore','composition',steps)
    return result
