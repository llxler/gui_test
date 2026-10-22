from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from gui_dna.tasks import ROOT, dump
from gui_dna.render import write_app
from .domain import tasks, library, reference_plan, compile_plan
from .evaluator import evaluate

OUT=ROOT/'artifacts/scale-study'


def main():
    lib=library();jobs=[]
    for task in tasks():
        jobs.append(('reference',task,reference_plan(task)))
        jobs.append(('default-policy-control',task,reference_plan(task,defaults=True)))
    task=tasks()[-1]
    for field in task['policy']:
        wrong=deepcopy(task);wrong['policy'][field]=not wrong['policy'][field]
        jobs.append(('mutant-'+field,task,reference_plan(wrong)))
    def run(job):
        kind,task,plan=job;folder=OUT/'calibration'/kind/task['id']
        app=write_app(folder/'index.html',task,compile_plan(plan,task['features'],lib))
        public=evaluate(app,task,folder/'public') if kind!='default-policy-control' else None
        hidden=evaluate(app,task,folder/'hidden',hidden=True)
        print(kind,task['id'],public['passed'] if public else '-',hidden['passed'],flush=True)
        return {'kind':kind,'task_id':task['id'],'public':public,'hidden':hidden}
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,jobs))
    correct=[r for r in results if r['kind']=='reference'];mutants=[r for r in results if r['kind'].startswith('mutant-')]
    passed=all(r['public']['passed'] and r['hidden']['passed'] for r in correct) and all(not r['public']['passed'] and not r['hidden']['passed'] for r in mutants)
    dump(OUT/'calibration.json',{'passed':passed,'library_sha256':lib['sha256'],'correct_references':len(correct),'mutants':len(mutants),'records':results})
    assert passed,'Reference or mutation calibration failed; no paid generation allowed'
    print('Calibration passed',flush=True)


if __name__=='__main__':main()
