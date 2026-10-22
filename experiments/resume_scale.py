"""Explicit, audited continuation after the user's third-study pause; default is read-only."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sqlite3

from gui_dna.tasks import ROOT,dump
from gui_dna.library import digest
from gui_dna.budget import Ledger

OUT=ROOT/'artifacts/scale-study'
LEDGER=ROOT/'artifacts/budget.sqlite3'


def verify():
    manifest=json.loads((OUT/'manifest.json').read_text())
    assert json.loads((ROOT/'configs/scale-study.json').read_text())==manifest['config'],'Configuration changed'
    assert digest((OUT/'protocol.md').read_text())==manifest['protocol_sha256'],'Frozen protocol changed'
    for name,sha in manifest['sources'].items():assert digest((ROOT/name).read_text())==sha,'Frozen source changed: '+name
    records=[]
    for p in (OUT/'runs').rglob('result.json'):
        row=json.loads(p.read_text())
        for v in row['versions']:
            app=Path(v['app'])
            assert digest(app.read_text())==v['app_sha256'],'Candidate HTML changed: '+str(app)
            assert digest(app.with_name('candidate.js').read_text())==v['code_sha256'],'Candidate code changed'
        records.append(row)
    with sqlite3.connect(f'file:{LEDGER}?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        policy=dict(db.execute('SELECT * FROM policy WHERE id=1').fetchone())
        calls=[dict(r) for r in db.execute('SELECT * FROM calls')]
    assert not any(c['status']=='reserved' for c in calls),'Requests still in flight; wait for settlements'
    return manifest,records,policy,calls


def clear_manual_pause(db_path, pause):
    """Release this manual pause only; never clear a genuine overcharge halt."""
    if not pause.get('not_a_budget_breach') or pause['prior_policy']['halted']!=0:
        raise RuntimeError('Pause was not recorded as a manual halt; do not clear it automatically')
    with sqlite3.connect(db_path,timeout=30) as db:
        db.execute('BEGIN IMMEDIATE')
        cap,stop,halted=db.execute('SELECT cap,stop,halted FROM policy WHERE id=1').fetchone()
        if halted!=1:raise RuntimeError('Expected a paused ledger; refusing duplicate continuation')
        if db.execute("SELECT COUNT(*) FROM calls WHERE status='reserved' OR actual>reserved").fetchone()[0]:
            raise RuntimeError('Unsettled active request or charge breach; leave ledger halted')
        exposure=db.execute('SELECT COALESCE(SUM(COALESCE(actual,reserved)),0) FROM calls').fetchone()[0]
        if exposure>=min(cap,stop):raise RuntimeError('Budget exhausted; leave ledger halted')
        db.execute('UPDATE policy SET halted=0 WHERE id=1')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--check',action='store_true',help='Read-only validation and remaining work (default)')
    group.add_argument('--resume',action='store_true',help='Explicitly resume paid generation under the unchanged $9 cap')
    args=parser.parse_args()
    manifest,records,policy,calls=verify()
    generated=sum(r['status']=='generated' for r in records)
    expected=len(manifest['requirements'])*manifest['config']['repetitions']*len(manifest['config']['models'])*len(manifest['config']['methods'])
    info={'ready':(OUT/'pause-ready.json').exists(),'ledger_halted':bool(policy['halted']),
          'generated':generated,'remaining_candidate_slots':expected-generated,
          'partial_budget_records':sum(r['status']=='budget_stopped' for r in records),
          'actual_usd':sum(c['actual'] or 0 for c in calls)/1e6,
          'exposure_usd':sum(c['actual'] if c['actual'] is not None else c['reserved'] for c in calls)/1e6,
          'cap_usd':policy['cap']/1e6,'stop_new_usd':policy['stop']/1e6}
    print(json.dumps(info,ensure_ascii=False,indent=2),flush=True)
    if not args.resume:return
    if not info['ready']:raise RuntimeError('Pause evaluation/snapshot is not ready; no API call issued')
    ready=json.loads((OUT/'pause-ready.json').read_text())
    snapshot=ROOT/ready['snapshot_directory']
    for name,sha in ready['snapshot_hashes'].items():assert digest((snapshot/name).read_text())==sha,'Pause snapshot changed'
    for name,sha in ready.get('snapshot_binary_hashes',{}).items():
        assert hashlib.sha256((snapshot/name).read_bytes()).hexdigest()==sha,'Binary snapshot changed'
    partial_paths=[Path(row['directory'])/'result.json' for row in records if row['status']=='budget_stopped']
    for p in partial_paths:
        if p.with_name('result-before-user-pause.json').exists():
            raise RuntimeError('Partial record archive already exists; inspect continuation state')
    # This performs a free model-directory read while the ledger remains halted.
    # Missing credentials or a retired model must not consume the pause marker.
    from gui_dna.provider import OpenRouter
    OpenRouter(manifest['config'])
    # Require completion of the read-only pause handoff before clearing the manual halt.
    pause=json.loads((OUT/'pause-request.json').read_text())
    clear_manual_pause(LEDGER,pause)
    resumed=[]
    for p in partial_paths:
        archive=p.with_name('result-before-user-pause.json')
        p.rename(archive);resumed.append(str(archive))
    marker={'started_utc':datetime.now(timezone.utc).isoformat(),'snapshot_directory':ready['snapshot_directory'],
            'partial_records_archived':resumed,'unchanged_manifest_sha256':digest(manifest),
            'prompts_and_hidden_fixtures_unchanged':True,'new_hidden_feedback_supplied_to_generators':False}
    dump(OUT/'resume-started.json',marker)
    (OUT/'pause-ready.json').rename(OUT/'pause-ready-consumed.json')
    # Completed candidates return immediately. Existing settled responses for interrupted
    # candidates replay through OpenRouter.call; they incur no second POST or charge.
    from experiments.scale_study.study import run
    from experiments.scale_study.analyze import main as analyze
    run();analyze()
    dump(OUT/'resume-completed.json',{'finished_utc':datetime.now(timezone.utc).isoformat(),
                                    'accounting':Ledger(LEDGER).summary(),
                                    'note':'Original partial snapshot preserved; consult results.json for final completion/stops'})


if __name__=='__main__':main()
