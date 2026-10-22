"""Offline calibration before freezing the follow-up protocol."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..render import write_app
from ..tasks import ROOT, dev_tasks, dump
from .domain import atomic_library, compile_plan, expected_plan, tasks
from .evaluator import evaluate


def calibrate(out):
    out = Path(out)
    library = atomic_library()
    def check(task, hidden):
        folder = out/'calibration'/task['id']
        app = write_app(folder/'index.html', task, compile_plan(expected_plan(task['features']), task['features'], library))
        contracts = [f for f in library['constraints'] if f['feature'] in ['core', *task['features']]]
        r = evaluate(app, task, folder/'checks', hidden=hidden, contracts=contracts)
        return {'task': task['id'], 'passed': r['passed'] and r['state_passed'], 'result': r}
    with ThreadPoolExecutor(max_workers=3) as pool:
        records = list(pool.map(lambda t: check(t, False), dev_tasks()))
        records += list(pool.map(lambda t: check(t, True), tasks()))
    result = {'passed': all(r['passed'] for r in records), 'library_sha256': library['sha256'], 'records': records}
    dump(out/'calibration.json', result)
    print({'passed': result['passed'], 'references': len(records)}, flush=True)
    if not result['passed']:
        for r in records:
            if not r['passed']:
                print(r['task'], r['result'].get('error'), [(c['name'], c.get('failure'), c['contract_failures'][:1], c['state_failures'][:1]) for c in r['result']['cases'] if not c['passed'] or not c['state_passed']])
        raise SystemExit(1)


if __name__ == '__main__':
    calibrate(ROOT/'artifacts/followup')
