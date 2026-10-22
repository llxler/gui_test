"""Matched interface-only contexts: free glue JavaScript versus checked plan IR."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import re
import time

from gui_dna.tasks import ROOT,dump
from gui_dna.library import digest
from gui_dna.provider import OpenRouter,ProviderError,parse_json
from gui_dna.budget import BudgetStop
from gui_dna.render import write_app
from gui_dna.prompts import INTERFACE
from gui_dna.followup.domain import atomic_library,tasks,compile_plan,EVENTS
from gui_dna.followup.evaluator import evaluate

OUT=ROOT/'artifacts/compact-pair'
METHODS=['compact_js','compact_plan']


def messages_for(task,method,library):
    docs=[]
    for f in library['functions']:
        parameters=re.search(r'function\s+\w+\s*\(([^)]*)\)',f['code']).group(1)
        doc={k:v for k,v in f.items() if k not in ('code','pre','post')}
        doc['signature']=f['name']+'('+parameters+')'
        if f['name'] not in ['searchRows','filterRows','sortRows','pageRows','normalizePage']:
            doc['calling_convention']='Mutates state s in place, returns undefined; handles '+','.join(EVENTS[f['feature']])
        elif f['name']=='normalizePage':doc['calling_convention']='Mutates s.page in place; total is the full matching count before pagination; returns undefined'
        elif f['name']=='pageRows':doc['calling_convention']='Pure; returns {items,total,pages}, respects s.enabled to disable pagination; rows is the complete matching ordered array'
        else:doc['calling_convention']='Pure; returns a new transformed row array; preserves canonical s.items'
        docs.append(doc)
    constraints=[{k:v for k,v in f.items() if k in ['name','feature','pre','post']} for f in library['constraints']]
    payload={'requirement':task['requirement'],'features':task['features'],'initial_example':task['initial'],
             'functions':docs,'state_contracts':constraints}
    common=('The listed immutable functions are already loaded into the page under their exact names. '
            'Compose their interfaces for the requested behavior. Satisfy the state contracts. No DOM, network or storage access. '
            'Plan the shared state relationships. The reducer/selector interface is:\n'+INTERFACE.split('reduce receives',1)[1])
    if method=='compact_js':
        common+='\nReturn JSON {"decomposition":[...],"code":"glue JavaScript assigning window.candidate={reduce,select}"}. Call the preloaded functions; do not repeat or redefine them. Add any ordinary JavaScript glue needed.'
    else:
        common+='\nReturn JSON {"decomposition":[...],"plan":{"view":["row transform function names, ending in pageRows"],"handlers":{"event type":"handler function name"},"normalize":"normalizePage","normalize_when":"after_each_event"}}. No code. Use each enabled search/filter/sort row transform once, with pageRows last. The compiler inserts frozen functions, validates all enabled event bindings and read-only view stages, and normalizes page after each event using the pre-pagination count.'
    return [{'role':'system','content':common},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}]


def generate(task,model,repeat,method,config,library,provider):
    folder=OUT/'runs'/model.replace('/','__')/task['id']/f'repeat-{repeat}'/method
    folder.mkdir(parents=True,exist_ok=True)
    if (folder/'result.json').exists():
        r=json.loads((folder/'result.json').read_text())
        for v in r['versions']:assert digest(Path(v['app']).read_text())==v['app_sha256']
        return r
    messages=messages_for(task,method,library)
    prefix='\n'.join(f['code'] for f in library['functions'])+'\n'
    contracts=[f for f in library['constraints'] if f['feature'] in ['core',*task['features']]]
    versions=[];started=time.monotonic()
    for attempt in range(config['max_repairs']+1):
        version=folder/f'candidate-{attempt}'
        dump(version/'messages.json',messages)
        raw=provider.call(model,messages,version/'call',f'compact:{model}:{task["id"]}:{repeat}:{method}:{attempt}',seed=config['seed']+repeat)
        error=None
        try:
            output=parse_json(raw)
            code=compile_plan(output.get('plan'),task['features'],library) if method=='compact_plan' else prefix+output['code']
            if not output.get('decomposition'):raise ValueError('Missing decomposition')
            dump(version/'output.json',output)
        except (ValueError,TypeError,KeyError) as e:code,error='window.candidate={};',str(e)
        (version/'candidate.js').write_text(code)
        app=write_app(version/'index.html',task,code)
        if error:feedback={'passed':False,'compile_error':error}
        else:
            r=evaluate(app,task,version/'public',contracts=contracts)
            feedback={'passed':r['passed'],'error':r.get('error'),'failures':[
                {'name':c['name'],'failure':c.get('failure'),'actions':c['actions'],'contract_failures':c['contract_failures'][:2]}
                for c in r['cases'] if not c['passed']]}
        dump(version/'feedback.json',feedback)
        versions.append({'app':str(app),'app_sha256':digest(app.read_text()),'code_sha256':digest(code),'public_passed':feedback['passed']})
        if feedback['passed']:break
        messages += [{'role':'assistant','content':raw},{'role':'user','content':'Fix the candidate using only this public feedback. Return the complete requested JSON.\n'+json.dumps(feedback,ensure_ascii=False)}]
    r={'model':model,'task_id':task['id'],'repetition':repeat,'method':method,'directory':str(folder),
       'versions':versions,'attempts':len(versions),'elapsed_seconds':time.monotonic()-started}
    dump(folder/'result.json',r);return r


def main():
    config=json.loads((ROOT/'configs/followup.json').read_text());library=atomic_library()
    manifest={'config':config,'library_sha256':library['sha256'],'requirements':tasks(),'script_sha256':digest(Path(__file__).read_text()),
              'protocol_sha256':digest((OUT/'protocol.md').read_text()),'primary_manifest_sha256':digest(json.loads((ROOT/'artifacts/followup/manifest.json').read_text()))}
    if (OUT/'manifest.json').exists():assert json.loads((OUT/'manifest.json').read_text())==manifest
    dump(OUT/'manifest.json',manifest)
    for task in tasks():assert messages_for(task,'compact_js',library)[1]==messages_for(task,'compact_plan',library)[1]
    provider=OpenRouter(config);records=[];stopped=None
    with ThreadPoolExecutor(max_workers=2) as pool:
        for repeat in range(config['repetitions']):
            for task in tasks():
                for model in config['models']:
                    print(f'Compact pair {model} / {task["id"]} / repeat {repeat+1}',flush=True)
                    futures=[pool.submit(generate,task,model,repeat,m,config,library,provider) for m in METHODS]
                    for f in futures:
                        try:records.append(f.result())
                        except (ProviderError,BudgetStop) as e:stopped=str(e)
                    if stopped:break
                if stopped:break
            if stopped:break
    dump(OUT/'generation-complete.json',{'candidates':records,'stopped':stopped})
    print('Compact generation frozen; evaluating first and final candidates',flush=True)
    lookup={t['id']:t for t in tasks()}
    def check(r):
        values={};folder=Path(r['directory'])
        for label,v in [('first_hidden',r['versions'][0]),('hidden',r['versions'][-1])]:
            assert digest(Path(v['app']).read_text())==v['app_sha256']
            if label=='hidden' and v['code_sha256']==r['versions'][0]['code_sha256']:
                values[label]=values['first_hidden'];continue
            path=folder/label/'evaluation.json'
            values[label]=json.loads(path.read_text()) if path.exists() else evaluate(v['app'],lookup[r['task_id']],folder/label,hidden=True)
        return {**r,**values}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(check,records))
    dump(OUT/'results.json',{'runs':results,'stopped':stopped,'accounting':provider.ledger.summary()})
    print({'completed':len(results),'stopped':stopped},flush=True)


if __name__=='__main__':main()
