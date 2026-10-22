"""Separate externally observable behavior from internal state conformance."""
from copy import deepcopy
from pathlib import Path

from ..evaluation import perform, contract_checks, evaluate as isolated_evaluate
from ..oracle import project, transition
from ..tasks import dump
from .fixtures import cases


def evaluate(app, task, out, hidden=False, contracts=None):
    result = isolated_evaluate(app, task, out, 'v2-hidden' if hidden else 'v2-public', contracts, timeout=180)
    result.setdefault('behavior_passed', False)
    result.setdefault('state_passed', False)
    result.setdefault('initial_passed', False)
    dump(Path(out) / 'evaluation.json', result)
    return result


def check_behavior(page, expected):
    actual = page.evaluate('window.__gui.snapshot(true)')
    assert not actual['errors'], f"Runtime errors: {actual['errors']}"
    wanted = project(expected)
    rendered = page.locator('#rows tr').evaluate_all("rs=>rs.map(r=>({id:Number(r.dataset.id),name:r.cells[0].textContent,category:r.cells[1].textContent,score:Number(r.cells[2].textContent)}))")
    assert rendered == wanted['items'], f"Visible rows: expected {wanted['items']!r}, got {rendered!r}"
    assert page.locator('#total').inner_text() == f"{wanted['total']} items", 'Visible total mismatch'
    assert page.locator('#empty').is_visible() == (wanted['total'] == 0), 'Empty state mismatch'
    for feature, field in [('search', 'query'), ('filter', 'filter'), ('sort', 'sort')]:
        if feature in expected['enabled']:
            assert page.locator('#' + feature).input_value() == expected[field], f'{feature} control mismatch'
    assert page.locator('#editor').is_visible() == (expected['editing'] is not None), 'Editor visibility mismatch'
    if expected['editing']:
        for key in ['name', 'category', 'score']:
            assert page.locator('#edit-' + key).input_value() == str(expected['editing'][key]), f'Draft {key} mismatch'
    if 'pagination' in expected['enabled']:
        assert page.locator('#page').input_value() == str(expected['page']), 'Page control mismatch'
        assert page.locator('#pages').inner_text() == f"of {wanted['pages']}", 'Page count mismatch'
        assert page.locator('#prev').is_disabled() == (expected['page'] == 1), 'Previous button mismatch'
        assert page.locator('#next').is_disabled() == (expected['page'] >= wanted['pages']), 'Next button mismatch'
    if 'undo' in expected['enabled']:
        assert page.locator('#undo').is_disabled() == (not expected['history']), 'Undo button mismatch'
    return actual


def run_browser(job):
    from playwright.sync_api import sync_playwright
    out = Path(job['out'])
    records = []
    runnable = True
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-dev-shm-usage'])
        context = browser.new_context(viewport={'width': 1120, 'height': 900}, service_workers='block')
        context.route('**/*', lambda route: route.continue_() if route.request.url == Path(job['app']).as_uri() else route.abort())
        page, contract_page = context.new_page(), context.new_page()
        page.set_default_timeout(1800)
        console = []
        page.on('pageerror', lambda e: console.append(str(e)))
        page.goto(Path(job['app']).as_uri())
        for case in cases(job['task'], job['suite'] == 'v2-hidden'):
            record = {'name': case['name'], 'kind': case['kind'], 'passed': False, 'behavior_passed': False,
                      'initial_passed': False, 'actions': [], 'state_failures': [], 'contract_failures': []}
            state = deepcopy(case['initial'])
            console.clear()
            def inspect():
                actual = check_behavior(page, state)
                mismatches = [k for k, value in state.items() if actual['state'].get(k) != value]
                if mismatches:
                    record['state_failures'].append({'step': len(record['actions']), 'fields': mismatches})
                assert not console, str(console)
                return actual
            try:
                page.evaluate('s=>window.__gui.reset(s)', state)
                inspect()
                record['initial_passed'] = True
                for instruction in case['steps']:
                    event = dict(instruction)
                    if 'pick' in event:
                        event['id'] = project(state)['items'][event.pop('pick')]['id']
                    record['actions'].append(event)
                    if event['type'] == 'search':
                        same = page.locator('#search').input_value() == event['value']
                        page.locator('#search').fill(event['value'])
                        if same: page.locator('#search').dispatch_event('input')
                    else:
                        perform(page, event)
                    state = transition(state, event)
                    actual = inspect()
                    if job['contracts'] and actual['trace']:
                        try:
                            contract_checks(contract_page, job['contracts'], actual['trace'][-1])
                        except Exception as error:
                            record['contract_failures'].append(str(error))
                record['behavior_passed'] = True
                record['passed'] = not record['contract_failures']
            except Exception as error:
                record['failure'] = str(error)
            record['state_passed'] = record['behavior_passed'] and not record['state_failures']
            if not record['passed'] or not record['state_passed']:
                screenshot = out / (case['name'] + '.png')
                page.screenshot(path=str(screenshot), full_page=True, timeout=3000)
                record['screenshot'] = str(screenshot)
                snapshot = page.evaluate('window.__gui.snapshot()')
                dump(out / (case['name'] + '-trace.json'), snapshot)
                if snapshot['errors'] or console: runnable = False
            records.append(record)
        browser.close()
    base = [r for r in records if r['kind'] == 'base']
    return {'suite': job['suite'], 'passed': all(r['passed'] for r in records),
            'behavior_passed': all(r['behavior_passed'] for r in records),
            'state_passed': all(r['state_passed'] for r in records),
            'initial_passed': all(r['initial_passed'] for r in records), 'runnable': runnable,
            'base_passed': sum(r['behavior_passed'] for r in base), 'base_total': len(base), 'cases': records}
