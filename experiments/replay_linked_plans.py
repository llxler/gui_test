"""No API calls: replay fixed first/final saved plans through the repaired linker."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json

from gui_dna.tasks import ROOT, dump
from gui_dna.library import digest
from gui_dna.provider import parse_json
from gui_dna.render import write_app
from gui_dna.followup.domain import tasks, atomic_library
from gui_dna.followup.evaluator import evaluate
from plan_linker import link_plan

OUT = ROOT / 'artifacts/linked-plan-posthoc'


def main():
    library = atomic_library()
    lookup = {task['id']: task for task in tasks()}
    sources = []
    for cohort, method in [('followup', 'compiled'), ('compact-pair', 'compact_plan')]:
        data = json.loads((ROOT / 'artifacts' / cohort / 'results.json').read_text())
        sources.extend((cohort, run) for run in data['runs'] if run['method'] == method)
    manifest = {'posthoc': True, 'new_api_calls': 0, 'library_sha256': library['sha256'],
                'source_hashes': {str(p.relative_to(ROOT)): digest(p.read_text()) for p in
                                  [Path(__file__), Path(__file__).with_name('plan_linker.py')]},
                'protocol_sha256': digest((OUT / 'protocol.md').read_text()),
                'source_candidates': [{k: r[k] for k in ['model', 'method', 'task_id', 'repetition', 'versions']} for _, r in sources]}
    if (OUT / 'manifest.json').exists():
        assert json.loads((OUT / 'manifest.json').read_text()) == manifest
    dump(OUT / 'manifest.json', manifest)
    records = []
    for cohort, run in sources:
        folder = OUT / cohort / run['model'].replace('/', '__') / run['task_id'] / f'repeat-{run["repetition"]}'
        record = {k: run[k] for k in ['model', 'method', 'task_id', 'repetition', 'attempts']}
        record['source_directory'] = run['directory']
        record['directory'] = str(folder)
        record['versions'] = []
        for label, old in [('first', run['versions'][0]), ('final', run['versions'][-1])]:
            previous = Path(old['app']).parent
            assert digest(Path(old['app']).read_text()) == old['app_sha256']
            responses = [json.loads(p.read_text()) for p in (previous / 'call').rglob('response.json')]
            responses = [r for r in responses if r.get('choices')]
            assert len(responses) == 1, previous
            output = parse_json(responses[0]['choices'][0]['message']['content'])
            destination = folder / label
            dump(destination / 'original-output.json', output)
            try:
                normalized, code, changes = link_plan(output.get('plan'), lookup[run['task_id']]['features'], library)
                if not output.get('decomposition'):
                    raise ValueError('Missing decomposition')
                diagnostic = {'compiled': True, 'plan': normalized, **changes}
            except (ValueError, TypeError, KeyError) as error:
                code = 'window.candidate={};'
                diagnostic = {'compiled': False, 'compile_error': str(error)}
            dump(destination / 'linking.json', diagnostic)
            (destination / 'candidate.js').write_text(code)
            app = write_app(destination / 'index.html', lookup[run['task_id']], code)
            record['versions'].append({'label': label, 'app': str(app), 'app_sha256': digest(app.read_text()),
                                       'code_sha256': digest(code), 'compiled': diagnostic['compiled']})
        records.append(record)
    dump(OUT / 'generation-complete.json', {'candidates': records, 'stopped': None, 'new_api_calls': 0})
    print(f'Frozen {len(records)} saved-plan replays; no API calls', flush=True)

    def check(record):
        result = dict(record)
        task = lookup[record['task_id']]
        contracts = [f for f in library['constraints'] if f['feature'] in ['core', *task['features']]]
        for version in record['versions']:
            label = version['label']
            assert digest(Path(version['app']).read_text()) == version['app_sha256']
            if label == 'final' and version['code_sha256'] == record['versions'][0]['code_sha256']:
                result['final'] = result['first']
                continue
            folder = Path(version['app']).parent
            scores = {}
            for suite in ['public', 'hidden']:
                saved = folder / suite / 'evaluation.json'
                scores[suite] = json.loads(saved.read_text()) if saved.exists() else evaluate(
                    Path(version['app']), task, folder / suite, hidden=suite == 'hidden',
                    contracts=contracts if suite == 'public' else [])
            result[label] = scores
        return result

    evaluated = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(check, records):
            evaluated.append(result)
            print(f'Evaluated {len(evaluated)}/{len(records)}', flush=True)
    groups = defaultdict(list)
    for record in evaluated:
        groups[(record['model'], record['method'])].append(record)
    summary = []
    for (model, method), runs in sorted(groups.items()):
        row = {'model': model, 'source_method': method, 'n': len(runs)}
        for label in ['first', 'final']:
            row[label] = {'behavior_passed': sum(r[label]['hidden']['behavior_passed'] for r in runs),
                          'state_passed': sum(r[label]['hidden']['state_passed'] for r in runs),
                          'public_passed': sum(r[label]['public']['passed'] for r in runs),
                          'base_passed': sum(r[label]['hidden']['base_passed'] for r in runs),
                          'base_total': sum(r[label]['hidden']['base_total'] for r in runs)}
        summary.append(row)
    dump(OUT / 'results.json', {'posthoc': True, 'new_api_calls': 0, 'summary': summary, 'runs': evaluated})
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
