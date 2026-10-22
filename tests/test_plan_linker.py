from copy import deepcopy

import pytest

from experiments.plan_linker import link_plan
from gui_dna.followup.domain import atomic_library, expected_plan, tasks, compile_plan


def test_disabled_nodes_removed_without_mutating_response_or_inventing_bindings():
    library = atomic_library()
    supplied = expected_plan(tasks()[-1]['features'])
    before = deepcopy(supplied)
    features = ['search', 'filter', 'pagination']
    normalized, code, changes = link_plan(supplied, features, library)
    assert supplied == before
    assert normalized == expected_plan(features)
    assert code == compile_plan(expected_plan(features), features, library)
    assert 'sortRows' in changes['removed_stages'] and 'save' in changes['removed_events']


@pytest.mark.parametrize('fault', ['missing', 'wrong', 'unknown', 'order', 'duplicate', 'normalization'])
def test_linking_does_not_hide_real_plan_errors(fault):
    features = ['edit', 'sort', 'pagination']
    plan = expected_plan(features)
    if fault == 'missing':
        del plan['handlers']['cancel']
    elif fault == 'wrong':
        plan['handlers']['save'] = 'removeItem'
    elif fault == 'unknown':
        plan['view'].insert(0, 'stealData')
    elif fault == 'order':
        plan['view'].reverse()
    elif fault == 'duplicate':
        plan['view'].insert(0, 'sortRows')
    else:
        plan['normalize_when'] = 'initial_only'
    with pytest.raises(ValueError):
        link_plan(plan, features, atomic_library())
