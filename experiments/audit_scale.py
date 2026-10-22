"""Read-only final audit of the completed enlarged study and report evidence."""
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import os
import re

from gui_dna.tasks import ROOT,dump
from gui_dna.library import digest
from gui_dna.budget import Ledger
from experiments.scale_study.domain import METHODS

OUT=ROOT/'artifacts/scale-study'


def main():
    manifest=json.loads((OUT/'manifest.json').read_text())
    for name,sha in manifest['sources'].items():assert digest((ROOT/name).read_text())==sha,name
    assert digest((OUT/'protocol.md').read_text())==manifest['protocol_sha256']
    assert json.loads((ROOT/'configs/scale-study.json').read_text())==manifest['config']
    previous=json.loads((ROOT/'artifacts/followup/manifest.json').read_text())
    assert digest({str(p.relative_to(ROOT)):p.read_text() for p in sorted((ROOT/'src/gui_dna').rglob('*')) if p.suffix in ('.py','.js','.html')})==previous['source_sha256']
    list_sha=hashlib.sha256((ROOT/'list.txt').read_bytes()).hexdigest()
    assert list_sha=='36542560716246a93489a524bc5980334e0df0a1499e287e3fa8d9e2f3256ad7'
    archive=json.loads((OUT/'source-archive.json').read_text())
    assert hashlib.sha256((OUT/'source-frozen.tar.gz').read_bytes()).hexdigest()==archive['sha256']
    generation=json.loads((OUT/'generation-complete.json').read_text())
    data=json.loads((OUT/'results.json').read_text());analysis=json.loads((OUT/'analysis.json').read_text())
    identity=lambda r:(r['model'],r['task_id'],r['repetition'],r['method'])
    assert {identity(r) for r in data['runs']}=={identity(r) for r in generation['candidates']}
    assert len({identity(r) for r in data['runs']})==len(data['runs'])
    groups=defaultdict(dict);versions=0;pictures=set();request_ids=set()
    for r in data['runs']:
        groups[(r['model'],r['task_id'],r['repetition'])][r['method']]=r
        folder=Path(r['directory'])
        for p in folder.rglob('request.json'):request_ids.add(json.loads(p.read_text())['call_id'])
        for v in r['versions']:
            app=Path(v['app']);assert digest(app.read_text())==v['app_sha256']
            assert digest(app.with_name('candidate.js').read_text())==v['code_sha256'];versions+=1
        if r['status']=='generated':
            for label in ['first_hidden','hidden']:
                for case in r[label]['cases']:
                    if case.get('screenshot'):
                        p=Path(case['screenshot']);assert p.exists() and p.with_name(p.stem+'-trace.json').exists();pictures.add(str(p))
    complete={k:g for k,g in groups.items() if set(g)==set(METHODS) and all(r['status']=='generated' for r in g.values())}
    assert len(complete)==analysis['complete_groups']
    for row in analysis['summary']:
        selected=[g[row['method']] for k,g in complete.items() if k[0]==row['model']]
        assert row['n']==len(selected)
        assert row['passed']==sum(r['hidden']['behavior_passed'] for r in selected)
        assert row['first_passed']==sum(r['first_hidden']['behavior_passed'] for r in selected)
        assert row['base_total']==sum(r['hidden']['base_total'] for r in selected)
    for group in complete.values():
        messages=[]
        for method in ['plan_checked','plan_unchecked']:
            messages.append(json.loads((Path(group[method]['directory'])/'candidate-0/messages.json').read_text()))
        assert messages[0]==messages[1]
        assert set(json.loads(messages[0][1]['content']))=={'requirement','features','initial','functions'}
    a=Ledger(ROOT/'artifacts/budget.sqlite3').summary()
    calls=[c for c in a['calls'] if c['purpose'].startswith('scale:')]
    assert {c['id'] for c in calls}==request_ids
    assert all(c['status']!='reserved' for c in a['calls'])
    assert a['policy']['cap']==9_000_000 and a['policy']['stop']==8_800_000 and a['exposure_usd']<=9
    assert abs(sum(r['known_usd'] for r in analysis['summary'])-sum(c['actual'] or 0 for c in calls)/1e6)<1e-9
    secret=os.environ.get('OPENROUTER_API_KEY','').encode();scanned=0
    if secret:
        for directory in [ROOT/'experiments',ROOT/'artifacts/scale-study',ROOT/'artifacts/scale-rule-control']:
            for p in directory.rglob('*'):
                if p.is_file() and p.suffix in ['.py','.json','.js','.html','.txt','.md']:
                    assert secret not in p.read_bytes(),str(p);scanned+=1
    for filename in ['README.md','第三轮研究报告.md']:
        for target in re.findall(r'\]\(([^)]+)\)',(ROOT/filename).read_text()):
            if '://' not in target and not target.startswith('#') and target!='artifacts/scale-study/final-verification.json':
                assert (ROOT/target.split('#')[0]).exists(),target
    test_log=(OUT/'tests-before-evaluation.txt').read_text();assert '38 passed' in test_log
    control=json.loads((ROOT/'artifacts/scale-rule-control/results.json').read_text())
    for r in control['runs']:assert digest(Path(r['app']).read_text())==r['app_sha256']
    report={'passed':True,'candidate_records':len(data['runs']),'generated':sum(r['status']=='generated' for r in data['runs']),
            'complete_groups':len(complete),'verified_candidate_versions':versions,'failure_pictures_and_traces':len(pictures),
            'source_and_protocol_hashes_unchanged':True,'v2_sources_unchanged':True,'list_txt_sha256':list_sha,
            'matched_plan_prompts':True,'public_context_allowlist_verified':True,'test_passes':38,
            'key_available_for_exact_scan':bool(secret),'secret_scan_files':scanned,
            'call_statuses':dict(Counter(c['status'] for c in calls)),
            'accounting':{k:a[k] for k in ['actual_usd','exposure_usd','library_usd','unsettled_calls','policy']}}
    dump(OUT/'final-verification.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
