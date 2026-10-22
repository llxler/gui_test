from copy import deepcopy
import json
import pytest

from experiments.scale_study.domain import tasks,library,reference_plan,compile_plan,messages_for,METHODS
from experiments.scale_study.oracle import project,transition
from experiments.scale_study.fixtures import cases


def test_context_boundaries_and_exactly_matched_plan_prompts():
    lib=library()
    for task in tasks():
        a=messages_for(task,'plan_checked',lib)
        assert a==messages_for(task,'plan_unchecked',lib)
        assert json.loads(a[1]['content'])==json.loads(messages_for(task,'linked_js',lib)[1]['content'])
        for method in METHODS:
            payload=json.loads(messages_for(task,method,lib)[1]['content'])
            assert set(payload)=={'requirement','features','initial','functions'}
            assert 'policy' not in payload and 'family' not in payload
            assert '51019' not in json.dumps(payload) and 'hidden-sequence' not in json.dumps(payload)


def test_compiler_checks_effects_but_does_not_know_the_correct_policy():
    task=tasks()[-1];lib=library();plan=reference_plan(task)
    assert compile_plan(plan,task['features'],lib)
    changed=deepcopy(task);changed['policy']={k:not v for k,v in task['policy'].items()}
    assert compile_plan(reference_plan(changed),task['features'],lib)  # Must not validate against evaluator answers.
    wrong=deepcopy(plan);wrong['view'].insert(0,'removeItem')
    with pytest.raises(ValueError,match='pure'):compile_plan(wrong,task['features'],lib)
    assert compile_plan(wrong,task['features'],lib,checked=False)
    wrong=deepcopy(plan);wrong['view'].reverse()
    with pytest.raises(ValueError,match='last'):compile_plan(wrong,task['features'],lib)
    wrong=deepcopy(plan);del wrong['handlers']['cancel']
    with pytest.raises(ValueError,match='routes'):compile_plan(wrong,task['features'],lib)


def test_semantic_oracle_has_observable_policy_differences():
    task=tasks()[-1];s=deepcopy(task['initial']);p={k:False for k in task['policy']}
    s['query']='ta'
    assert project(s,p)['total']==2
    assert project(s,{**p,'prefix':True})['total']==0
    s['query']='';s['page']=2
    assert transition(s,{'type':'filter','value':'all'},p)['page']==1
    assert transition(s,{'type':'filter','value':'all'},{**p,'keep_page':True})['page']==2
    s['editing']=deepcopy(s['items'][0]);event={'type':'page','value':2}
    assert transition(s,event,p)['editing'] is not None
    assert transition(s,event,{**p,'cancel_view':True})['editing'] is None
    s=transition(s,{'type':'delete','id':s['items'][0]['id']},p)
    restored=transition(s,{'type':'undo'},{**p,'append_undo':True})
    assert restored['items'][-1]['id']==1 and restored['history']==[]


def test_all_directed_and_random_trajectories_use_available_rows():
    for task in tasks():
        for case in cases(task,True)+cases(task,False):
            s=deepcopy(case['initial'])
            for raw in case['steps']:
                event=dict(raw)
                if 'pick' in event:event['id']=project(s,task['policy'])['items'][event.pop('pick')]['id']
                if event['type'] in ['delete','edit']:
                    assert event['id'] in [x['id'] for x in project(s,task['policy'])['items']]
                s=transition(s,event,task['policy'])


def test_cluster_interval_does_not_shrink_when_same_family_observations_are_duplicated():
    from experiments.scale_study.analyze import paired_interval
    paired=[(0,1),(0,1),(1,-1),(1,-1),(2,0),(2,0)]
    assert paired_interval(paired,37,2000)==paired_interval(paired*10,37,2000)
    assert paired_interval([(0,1),(1,1)],37,2000)==[1,1]
    assert paired_interval([],37,2000) is None
