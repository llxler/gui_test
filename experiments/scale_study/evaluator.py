"""Isolated Playwright evaluator; one DOM snapshot per step and a separate oracle."""
from copy import deepcopy
from pathlib import Path
import json
import os
import signal
import subprocess
import sys
import sysconfig
import time

from gui_dna.tasks import ROOT, dump
from gui_dna.evaluation import perform
from .oracle import project, transition
from .fixtures import cases

SNAPSHOT = """() => ({...window.__gui.snapshot(true), dom:{
 rows:[...document.querySelectorAll('#rows tr')].map(r=>({id:Number(r.dataset.id),name:r.cells[0].textContent,category:r.cells[1].textContent,score:Number(r.cells[2].textContent)})),
 total:document.querySelector('#total').textContent,
 empty:!document.querySelector('#empty').hidden,
 editor:!document.querySelector('#editor').hidden,
 controls:Object.fromEntries(['search','filter','sort','page','edit-name','edit-category','edit-score'].map(k=>[k,document.getElementById(k).value])),
 pages:document.querySelector('#pages').textContent,
 disabled:Object.fromEntries(['prev','next','undo'].map(k=>[k,document.getElementById(k).disabled]))}})"""


def check(actual, state, policy):
    assert not actual['errors'], 'Runtime errors: '+str(actual['errors'])
    want=project(state,policy);dom=actual['dom'];fs=state['enabled']
    assert dom['rows']==want['items'], f"Visible rows differ: expected {want['items']!r}, got {dom['rows']!r}"
    assert dom['total']==f"{want['total']} items", 'Visible total mismatch'
    assert dom['empty']==(want['total']==0), 'Empty message mismatch'
    assert dom['editor']==(state['editing'] is not None), 'Draft editor visibility mismatch'
    for feature,key in [('search','query'),('filter','filter'),('sort','sort')]:
        if feature in fs:assert dom['controls'][feature]==state[key],feature+' control mismatch'
    if state['editing']:
        for field in ['name','category','score']:
            assert dom['controls']['edit-'+field]==str(state['editing'][field]), 'Draft '+field+' mismatch'
    if 'pagination' in fs:
        assert dom['controls']['page']==str(state['page']), 'Page value mismatch'
        assert dom['pages']==f"of {want['pages']}", 'Page count mismatch'
        assert dom['disabled']['prev']==(state['page']==1), 'Previous button mismatch'
        assert dom['disabled']['next']==(state['page']>=want['pages']), 'Next button mismatch'
    if 'undo' in fs:assert dom['disabled']['undo']==(not state['history']), 'Undo availability mismatch'


def browser(job):
    from playwright.sync_api import sync_playwright
    task=job['task'];policy=task['policy'];out=Path(job['out']);records=[];runnable=True
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--disable-dev-shm-usage'])
        context=browser.new_context(viewport={'width':1120,'height':900},service_workers='block')
        context.route('**/*',lambda route:route.continue_() if route.request.url==Path(job['app']).as_uri() else route.abort())
        page=context.new_page();page.set_default_timeout(1800)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.goto(Path(job['app']).as_uri())
        for case in cases(task,job['hidden']):
            state=deepcopy(case['initial']);errors.clear()
            record={'name':case['name'],'kind':case['kind'],'actions':[],'behavior_passed':False,'state_failures':[],'initial_passed':False}
            def inspect():
                actual=page.evaluate(SNAPSHOT)
                assert not errors,'JavaScript errors: '+str(errors)
                check(actual,state,policy)
                bad=[k for k,v in state.items() if actual['state'].get(k)!=v]
                if bad:record['state_failures'].append({'step':len(record['actions']),'fields':bad})
                return actual
            try:
                page.evaluate('s=>window.__gui.reset(s)',state);inspect();record['initial_passed']=True
                for step in case['steps']:
                    event=dict(step)
                    if 'pick' in event:event['id']=project(state,policy)['items'][event.pop('pick')]['id']
                    record['actions'].append(event)
                    if event['type']=='search':
                        same=page.locator('#search').input_value()==event['value']
                        page.locator('#search').fill(event['value'])
                        if same:page.locator('#search').dispatch_event('input')
                    else:perform(page,event)
                    state=transition(state,event,policy);inspect()
                record['behavior_passed']=True
            except Exception as error:record['failure']=str(error)
            record['state_passed']=record['behavior_passed'] and not record['state_failures']
            record['passed']=record['state_passed']
            if not record['passed']:
                picture=out/(case['name']+'.png');page.screenshot(path=str(picture),full_page=True,timeout=3000)
                record['screenshot']=str(picture)
                snapshot=page.evaluate('window.__gui.snapshot()');dump(out/(case['name']+'-trace.json'),snapshot)
                if errors or snapshot['errors']:runnable=False
            records.append(record)
        browser.close()
    base=[r for r in records if r['kind']=='base']
    return {'passed':all(r['passed'] for r in records),'behavior_passed':all(r['behavior_passed'] for r in records),
            'state_passed':all(r['state_passed'] for r in records),'initial_passed':all(r['initial_passed'] for r in records),
            'runnable':runnable,'base_passed':sum(r['behavior_passed'] for r in base),'base_total':len(base),'cases':records}


def evaluate(app,task,out,hidden=False):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    job={'app':str(Path(app).resolve()),'task':task,'out':str(out.resolve()),'hidden':hidden}
    env=dict(os.environ);env.pop('OPENROUTER_API_KEY',None)
    libs=ROOT/'.browser-deps/usr/lib'/sysconfig.get_config_var('MULTIARCH')
    if libs.exists():env['LD_LIBRARY_PATH']=str(libs)+os.pathsep+env.get('LD_LIBRARY_PATH','')
    start=time.monotonic()
    try:
        with subprocess.Popen([sys.executable,'-m','experiments.scale_study.evaluator'],cwd=ROOT,env=env,
                              stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True) as proc:
            try:stdout,stderr=proc.communicate(json.dumps(job),timeout=180)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL);proc.communicate();raise
            if proc.returncode:raise RuntimeError(stderr[-3000:])
            result=json.loads(stdout)
    except (subprocess.TimeoutExpired,RuntimeError,json.JSONDecodeError) as error:
        result={'passed':False,'behavior_passed':False,'state_passed':False,'initial_passed':False,'runnable':False,
                'base_passed':0,'base_total':len(task['features']),'cases':[],'error':str(error)}
    result['elapsed_seconds']=time.monotonic()-start;dump(out/'evaluation.json',result)
    return result


if __name__=='__main__':print(json.dumps(browser(json.load(sys.stdin)),ensure_ascii=False))
