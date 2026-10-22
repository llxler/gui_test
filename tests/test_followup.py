import json
from copy import deepcopy
import pytest

from gui_dna.followup.domain import tasks, atomic_library, expected_plan, compile_plan
from gui_dna.followup.study import messages_for, generate
from gui_dna.followup.evaluator import evaluate
from gui_dna.render import write_app
from gui_dna.tasks import ROOT


def test_composition_rejects_unsafe_stage_order_missing_routes_and_changed_body():
    task, library = tasks()[-1], atomic_library()
    plan = expected_plan(task['features'])
    wrong = deepcopy(plan)
    wrong['view'] = ['pageRows', *plan['view'][:-1]]
    with pytest.raises(ValueError, match='last'):
        compile_plan(wrong, task['features'], library)
    wrong = deepcopy(plan)
    del wrong['handlers']['cancel']
    with pytest.raises(ValueError, match='coverage'):
        compile_plan(wrong, task['features'], library)
    wrong = deepcopy(plan)
    wrong['handlers']['save'] = 'removeItem'
    with pytest.raises(ValueError, match='binding'):
        compile_plan(wrong, task['features'], library)


def test_ablation_context_boundaries():
    task, library = tasks()[-1], atomic_library()
    payloads = {m: json.loads(messages_for(task, m, library)[1]['content']) for m in ['dna', 'metadata', 'checks', 'constrained', 'compiled']}
    assert payloads['dna'] == payloads['checks']
    assert payloads['metadata'] == payloads['constrained'] == payloads['compiled']
    assert all('post' not in f and 'writes' not in f for f in payloads['dna']['functions'])
    assert 'state_contracts' in payloads['constrained']
    for m in payloads:
        serialized = json.dumps(messages_for(task, m, library))
        assert 'heldout-interleave' not in serialized and 'Cedar' not in serialized
    assert {f['name']: f['code'] for f in payloads['dna']['functions']} == {f['name']: f['code'] for f in payloads['compiled']['functions']}


def test_behavior_and_internal_state_are_scored_separately(tmp_path):
    task, library = tasks()[1], atomic_library()  # edit/filter/page without undo
    code = compile_plan(expected_plan(task['features']), task['features'], library)
    mutant = code.replace("if (e.type === 'save' && s.editing) {", "if (e.type === 'save' && s.editing) { s.history.push({item:structuredClone(s.editing),index:0});")
    assert mutant != code
    app = write_app(tmp_path/'mutant.html', task, mutant)
    behavior = evaluate(app, task, tmp_path/'behavior')
    assert behavior['behavior_passed'] and behavior['passed'] and not behavior['state_passed']
    assert any(c['state_failures'] for c in behavior['cases'])
    contracts = [c for c in library['constraints'] if c['name'] == 'historyFrame']
    checked = evaluate(app, task, tmp_path/'checked', contracts=contracts)
    assert checked['behavior_passed'] and not checked['passed']
    assert any(c['contract_failures'] for c in checked['cases'])


def test_cancel_mutation_changes_visible_behavior(tmp_path):
    task, library = tasks()[-1], atomic_library()
    code = compile_plan(expected_plan(task['features']), task['features'], library)
    mutant = code.replace("if (e.type === 'cancel') s.editing = null;", "if(e.type==='cancel'){s.items=s.items.map(x=>x.id===s.editing.id?{...s.editing}:x);s.editing=null;}")
    assert mutant != code
    app = write_app(tmp_path/'cancel.html', task, mutant)
    result = evaluate(app, task, tmp_path/'checks')
    assert not result['behavior_passed']


def test_draft_blur_cannot_swallow_a_following_delete(tmp_path):
    task, library = tasks()[2], atomic_library()
    app = write_app(tmp_path/'reference.html', task, compile_plan(expected_plan(task['features']), task['features'], library))
    result = evaluate(app, task, tmp_path/'checks', hidden=True)
    assert result['behavior_passed'] and result['state_passed'], result


def test_deterministic_reference_needs_no_api_and_has_valid_artifacts(tmp_path):
    class NoCalls:
        def call(self, *args, **kwargs):
            raise AssertionError('Deterministic reference must not call an API')
    task, library = tasks()[0], atomic_library()
    config = json.loads((ROOT/'configs/followup.json').read_text())
    result = generate(task, 'deterministic', library, 'model-group-label', 0, config, NoCalls(), tmp_path/'run')
    assert result['attempts'] == 1 and result['versions'][0]['public_passed']
    assert not list((tmp_path/'run').rglob('request.json'))
