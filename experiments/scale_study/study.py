"""Prospective four-arm study, balanced groups, durable costs and freeze barrier."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import sys
import time

from gui_dna.tasks import ROOT, dump
from gui_dna.library import digest
from gui_dna.provider import OpenRouter, ProviderError, parse_json
from gui_dna.budget import BudgetStop
from gui_dna.render import write_app
from .domain import METHODS, tasks, library, messages_for, compile_plan
from .evaluator import evaluate

OUT=ROOT/'artifacts/scale-study'


def generate(task, model, repeat, method, config, lib, provider):
    folder=OUT/'runs'/model.replace('/','__')/task['id']/f'repeat-{repeat}'/method
    identity=digest({'task':task,'model':model,'repeat':repeat,'method':method,'config':config,'library':lib['sha256']})
    if (folder/'result.json').exists():
        old=json.loads((folder/'result.json').read_text());assert old['fingerprint']==identity
        for v in old['versions']:assert digest(Path(v['app']).read_text())==v['app_sha256']
        return old
    messages=messages_for(task,method,lib);versions=[];start=time.monotonic();status='generated';error=None
    for attempt in range(config['max_repairs']+1):
        version=folder/f'candidate-{attempt}';dump(version/'messages.json',messages)
        try:
            raw=provider.call(model,messages,version/'call',f'scale:{model}:{task["id"]}:{repeat}:{method}:{attempt}',seed=config['seed']+repeat)
        except (ProviderError,BudgetStop) as e:
            status='budget_stopped' if isinstance(e,BudgetStop) else 'transport_failed';error=str(e);break
        compile_error=None
        try:
            output=parse_json(raw)
            if method.startswith('plan_'):code=compile_plan(output.get('plan'),task['features'],lib,checked=method=='plan_checked')
            else:
                code=output['code']
                if not isinstance(code,str):raise ValueError('code must be a string')
                if method=='linked_js':code='\n'.join(f['code'] for f in lib['functions'])+'\n'+code
            if not output.get('decomposition'):raise ValueError('Missing decomposition')
            dump(version/'output.json',output)
        except (ValueError,KeyError,TypeError) as e:
            compile_error=str(e);code='window.candidate={};'
        (version/'candidate.js').write_text(code)
        app=write_app(version/'index.html',task,code)
        if compile_error:feedback={'passed':False,'compile_error':compile_error}
        else:
            public=evaluate(app,task,version/'public')
            feedback={'passed':public['passed'],'error':public.get('error'),
                      'failures':[{'name':c['name'],'failure':c.get('failure'),'actions':c['actions'],
                                   'state_failures':c['state_failures'][:2]} for c in public['cases'] if not c['passed']][:3]}
        dump(version/'feedback.json',feedback)
        versions.append({'app':str(app),'app_sha256':digest(app.read_text()),'code_sha256':digest(code),
                         'public_passed':feedback['passed'],'compile_error':compile_error})
        if feedback['passed']:break
        messages += [{'role':'assistant','content':raw},{'role':'user','content':
                     'Repair using only the public feedback below. Preserve the requested output schema and return the complete candidate.\n'+json.dumps(feedback,ensure_ascii=False)}]
    result={'fingerprint':identity,'model':model,'task_id':task['id'],'family':task['family'],'repetition':repeat,
            'method':method,'status':status,'error':error,'directory':str(folder),'versions':versions,
            'attempts':len(versions),'elapsed_seconds':time.monotonic()-start}
    dump(folder/'result.json',result)
    return result


def run():
    config=json.loads((ROOT/'configs/scale-study.json').read_text());lib=library()
    assert config['methods']==METHODS
    files=sorted((ROOT/'experiments/scale_study').glob('*.py'))+sorted((ROOT/'src/gui_dna').rglob('*.py'))+sorted((ROOT/'src/gui_dna/assets').glob('*'))
    manifest={'config':config,'requirements':tasks(),'library':lib,'python':sys.version,
              'protocol_sha256':digest((OUT/'protocol.md').read_text()),
              'sources':{str(p.relative_to(ROOT)):digest(p.read_text()) for p in files if p.is_file()},
              'prior_budget':{k:v for k,v in json.loads((ROOT/'artifacts/followup/final-verification.json').read_text())['accounting'].items() if k in ['actual_usd','exposure_usd']}}
    if (OUT/'manifest.json').exists():assert json.loads((OUT/'manifest.json').read_text())==manifest,'Frozen study changed'
    dump(OUT/'manifest.json',manifest)
    calibration=json.loads((OUT/'calibration.json').read_text())
    assert calibration['passed'] and calibration['library_sha256']==lib['sha256']
    provider=OpenRouter(config)
    dump(OUT/'models.json',{m:provider.models[m] for m in config['models']})
    def model_worker(model):
        records=[];stop=None;failed_groups=0
        for repeat in range(config['repetitions']):
            for index,task in enumerate(tasks()):
                # Complete recorded groups can always be replayed, even after budget exhaustion.
                group=OUT/'runs'/model.replace('/','__')/task['id']/f'repeat-{repeat}'
                existing=all((group/m/'result.json').exists() for m in METHODS)
                if not existing and provider.ledger.summary()['exposure_usd']+config['group_admission_margin_usd']>config['stop_new_requests_usd']:
                    stop='Budget group admission margin reached';break
                shift=(index+repeat)%len(METHODS);order=METHODS[shift:]+METHODS[:shift]
                print(f'Generate {model} {task["id"]} repeat {repeat+1}/{config["repetitions"]}',flush=True)
                current=[]
                for method in order:
                    r=generate(task,model,repeat,method,config,lib,provider);records.append(r);current.append(r)
                    if r['status']=='budget_stopped':stop=r['error'];break
                failed_groups=failed_groups+1 if any(r['status']=='transport_failed' for r in current) else 0
                if failed_groups>=config['max_consecutive_transport_failed_groups']:stop='Three consecutive groups contain transport failures'
                dump(OUT/(model.replace('/','__')+'-progress.json'),{'records':len(records),'stopped':stop,'budget':provider.ledger.summary()['exposure_usd']})
                if stop:break
            if stop:break
        return records,stop
    with ThreadPoolExecutor(max_workers=2) as pool:by_model=list(pool.map(model_worker,config['models']))
    records=[r for rows,_ in by_model for r in rows]
    stops={model:value[1] for model,value in zip(config['models'],by_model)}
    dump(OUT/'generation-complete.json',{'candidates':records,'stops':stops,'accounting':provider.ledger.summary()})
    print('ALL GENERATION FROZEN; starting independent hidden evaluation',flush=True)
    lookup={t['id']:t for t in tasks()}
    def score(r):
        if r['status']!='generated':return r
        result=dict(r);folder=Path(r['directory'])
        for label,v in [('first_hidden',r['versions'][0]),('hidden',r['versions'][-1])]:
            assert digest(Path(v['app']).read_text())==v['app_sha256']
            if label=='hidden' and v['code_sha256']==r['versions'][0]['code_sha256']:
                result[label]=result['first_hidden'];continue
            saved=folder/label/'evaluation.json'
            result[label]=json.loads(saved.read_text()) if saved.exists() else evaluate(v['app'],lookup[r['task_id']],folder/label,hidden=True)
        return result
    evaluated=[]
    with ThreadPoolExecutor(max_workers=config['evaluation_workers']) as pool:
        for r in pool.map(score,records):
            evaluated.append(r)
            if len(evaluated)%10==0:print(f'Hidden evaluated {len(evaluated)}/{len(records)}',flush=True)
    dump(OUT/'results.json',{'runs':evaluated,'stops':stops,'accounting':provider.ledger.summary()})
    print(f'Completed {len(evaluated)} candidate records',flush=True)


if __name__=='__main__':run()
