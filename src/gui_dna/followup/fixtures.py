"""Evaluator-only deterministic trajectories; never serialized into model prompts."""
from copy import deepcopy
import random

from ..oracle import project, transition
from ..suites import basic_steps
from ..tasks import initial_state


def trajectory(initial, seed, decisions):
    rng = random.Random(seed)
    state = deepcopy(initial)
    steps = []

    def emit(kind, **fields):
        nonlocal state
        event = {'type': kind, **fields}
        steps.append(event)
        state = transition(state, event)

    for _ in range(decisions):
        feature = rng.choice(state['enabled'])
        visible = project(state)['items']
        if feature == 'search': emit('search', value=rng.choice(['a', ' AL ', '', 'zz', 'not-found']))
        elif feature == 'filter': emit('filter', value=rng.choice(['all', 'A', 'B', 'C']))
        elif feature == 'sort': emit('sort', value=rng.choice(['none', 'name-asc', 'score-desc']))
        elif feature == 'pagination': emit('page', value=rng.choice([0, 1, 2, 3, 999]))
        elif feature == 'undo': emit('undo')
        elif feature == 'delete' and visible: emit('delete', id=rng.choice(visible)['id'])
        elif feature == 'edit' and visible:
            item = rng.choice(visible)
            emit('edit', id=item['id'])
            field = rng.choice(['name', 'category', 'score'])
            value = rng.choice(['zz saved', 'AL edited', 'Birch']) if field == 'name' else rng.choice(['A', 'B', 'C']) if field == 'category' else rng.choice([-21, 0, 88])
            emit('draft', field=field, value=value)
            # Preserve a draft across a view change, and occasionally delete its item.
            if 'sort' in state['enabled']: emit('sort', value=rng.choice(['name-asc', 'score-desc']))
            if 'filter' in state['enabled']: emit('filter', value=rng.choice(['all', 'A', 'B', 'C']))
            if 'search' in state['enabled']: emit('search', value=rng.choice(['', 'al', 'zz']))
            if 'delete' in state['enabled'] and any(x['id'] == item['id'] for x in project(state)['items']) and rng.random() < .3:
                emit('delete', id=item['id'])
            if state['editing'] is not None: emit(rng.choice(['save', 'save', 'cancel']))
    return steps


def cases(task, hidden):
    state = deepcopy(task['initial'])
    if hidden:
        # Separate from v1's held-out data: new identifiers, Unicode excluded by public spec.
        rows = [{'id': 701 + 11*i, 'name': ['ALTO', 'maple', 'Cedar', 'aloe', 'zz', 'ALTO', 'Aspen'][i % 7],
                 'category': 'ABACABCC'[i % 8], 'score': [5, -3, 5, 0, 99][i % 5]} for i in range(23)]
        state = initial_state(rows, task['features'])
    result = []
    for feature in task['features']:
        initial = deepcopy(state)
        if feature == 'undo' and not initial['history']:
            initial['history'] = [{'item': initial['items'].pop(2), 'index': 2}]
        result.append({'name': 'base-' + feature, 'kind': 'base', 'initial': initial,
                       'steps': basic_steps(feature, hidden)})
    seeds = [107, 331, 809] if hidden else [41]
    for i, seed in enumerate(seeds):
        initial = deepcopy(state)
        initial['pageSize'] = [2, 4, 7][i] if hidden else 3
        if hidden and i == 1:
            if 'sort' in task['features']: initial['sort'] = 'score-desc'
            if 'filter' in task['features']: initial['filter'] = 'A'
        result.append({'name': ('heldout' if hidden else 'public') + f'-interleave-{i}',
                       'kind': 'composition', 'initial': initial,
                       'steps': trajectory(initial, seed, 55 if hidden else 18)})
    if hidden:
        empty = initial_state([], task['features'])
        result.append({'name': 'empty-sequence', 'kind': 'composition', 'initial': empty,
                       'steps': trajectory(empty, 1237, 18)})
        if 'delete' in task['features']:
            initial = deepcopy(state)
            # Delete every visible row at the last page, then restore the complete history twice.
            steps = ([{'type': 'page', 'value': 999}] if 'pagination' in task['features'] else [])
            steps += [{'type': 'delete', 'pick': 0} for _ in initial['items']]
            if 'undo' in task['features']:
                steps += [{'type': 'undo'} for _ in range(len(initial['items']) + 2)]
            result.append({'name': 'drain-and-restore', 'kind': 'composition', 'initial': initial, 'steps': steps})
    return result
