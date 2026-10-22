"""Strong DNA control with preloaded identical primitives; no contract or plan compiler."""
from pathlib import Path
import json
import time
from concurrent.futures import ThreadPoolExecutor

from gui_dna.tasks import ROOT, dump
from gui_dna.budget import BudgetStop
from gui_dna.library import digest
from gui_dna.provider import OpenRouter, ProviderError, parse_json
from gui_dna.render import write_app
from gui_dna.followup.domain import atomic_library, tasks
from gui_dna.followup.study import messages_for
from gui_dna.followup.evaluator import evaluate

OUT = ROOT/'artifacts/linked-control'


def generate(task, model, repeat, config, library, provider, folder):
    folder.mkdir(parents=True, exist_ok=True)
    if (folder/'result.json').exists():
        r = json.loads((folder/'result.json').read_text())
        for v in r['versions']:
            assert digest(Path(v['app']).read_text()) == v['app_sha256']
        return r
    messages = messages_for(task, 'dna', library)
    messages[0]['content'] += ('\nAll supplied library functions are ALREADY PRELOADED under their exact names.'
        ' Return only the glue JavaScript assigning window.candidate={reduce,select}, with decomposition.'
        ' Call those functions directly; do not repeat their function definitions.'
        ' You may implement any additional glue needed in ordinary JavaScript.')
    prefix = '\n'.join(f['code'] for f in library['functions']) + '\n'
    versions = []
    started = time.monotonic()
    for attempt in range(config['max_repairs']+1):
        version = folder/f'candidate-{attempt}'
        dump(version/'messages.json', messages)
        raw = provider.call(model, messages, version/'call', f'linked:{model}:{task["id"]}:{repeat}:{attempt}', seed=config['seed']+repeat)
        error = None
        try:
            output = parse_json(raw)
            assert isinstance(output.get('code'), str) and output.get('decomposition'), 'Code and decomposition required'
            code = prefix + output['code']
            dump(version/'output.json', output)
        except (ValueError, TypeError, AssertionError) as e:
            code, error = 'window.candidate={};', str(e)
        (version/'candidate.js').write_text(code)
        app = write_app(version/'index.html', task, code)
        if error:
            feedback = {'passed': False, 'compile_error': error}
        else:
            r = evaluate(app, task, version/'public')
            feedback = {'passed': r['passed'], 'error': r.get('error'), 'failures': [
                {'name': c['name'], 'failure': c.get('failure'), 'actions': c['actions'], 'contract_failures': []}
                for c in r['cases'] if not c['passed']]}
        dump(version/'feedback.json', feedback)
        versions.append({'app':str(app),'app_sha256':digest(app.read_text()),'code_sha256':digest(code),'public_passed':feedback['passed']})
        if feedback['passed']: break
        messages += [{'role':'assistant','content':raw}, {'role':'user','content':'Fix the candidate using only this public feedback. Return the complete requested JSON.\n'+json.dumps(feedback,ensure_ascii=False)}]
    r = {'model':model,'task_id':task['id'],'repetition':repeat,'method':'linked_dna','directory':str(folder),
         'attempts':len(versions),'versions':versions,'elapsed_seconds':time.monotonic()-started}
    dump(folder/'result.json',r)
    return r


def main():
    config = json.loads((ROOT/'configs/followup.json').read_text())
    library = atomic_library()
    manifest = {'config':config,'library_sha256':library['sha256'],'requirements':tasks(),
                'script_sha256':digest(Path(__file__).read_text()),'protocol_sha256':digest((OUT/'protocol.md').read_text()),
                'primary_manifest_sha256':digest(json.loads((ROOT/'artifacts/followup/manifest.json').read_text()))}
    if (OUT/'manifest.json').exists(): assert json.loads((OUT/'manifest.json').read_text()) == manifest
    dump(OUT/'manifest.json',manifest)
    provider = OpenRouter(config)
    records, stopped = [], None
    for repeat in range(config['repetitions']):
        for task in tasks():
            for model in config['models']:
                print(f'Linked {model} / {task["id"]} / repeat {repeat+1}',flush=True)
                folder=OUT/'runs'/model.replace('/','__')/task['id']/f'repeat-{repeat}'
                try: records.append(generate(task,model,repeat,config,library,provider,folder))
                except (ProviderError,BudgetStop) as e:
                    stopped=str(e)
                    break
            if stopped: break
        if stopped: break
    dump(OUT/'generation-complete.json',{'candidates':records,'stopped':stopped})
    print('Linked generation frozen; evaluating first and final candidates',flush=True)
    lookup={t['id']:t for t in tasks()}
    def check(r):
        folder=Path(r['directory']);values={}
        for label,v in [('first_hidden',r['versions'][0]),('hidden',r['versions'][-1])]:
            assert digest(Path(v['app']).read_text())==v['app_sha256']
            if label=='hidden' and v['code_sha256']==r['versions'][0]['code_sha256']:
                values[label]=values['first_hidden'];continue
            path=folder/label/'evaluation.json'
            values[label]=json.loads(path.read_text()) if path.exists() else evaluate(v['app'],lookup[r['task_id']],folder/label,hidden=True)
        return {**r,**values}
    with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(check,records))
    dump(OUT/'results.json',{'runs':results,'stopped':stopped,'accounting':provider.ledger.summary()})
    print({'completed':len(results),'stopped':stopped},flush=True)


if __name__=='__main__':main()
