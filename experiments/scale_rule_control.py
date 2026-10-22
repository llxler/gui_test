"""Zero-API control: parse only the public benchmark's controlled-language clauses."""
from pathlib import Path
import json

from gui_dna.tasks import ROOT,dump
from gui_dna.library import digest
from gui_dna.render import write_app
from experiments.scale_study.domain import tasks,library,reference_plan,compile_plan


def public_plan(requirement, features):
    clauses={
        'prefix':('search','any name SUBSTRING.','only name PREFIXES.'),
        'id_ties':('sort','retain current canonical array order.','break ties by ascending numeric ID.'),
        'cancel_view':('edit','preserve the draft exactly, even when its item becomes invisible.',
                       'discard any draft and close the editor, including no-op view events.'),
        'keep_page':(None,'reset page to 1.','retain the current page and clamp it to the new range.'),
        'append_undo':('undo','restores the item at its recorded canonical array index.','appends the restored item to the END of canonical items.')}
    decoded={}
    for name,(feature,false_clause,true_clause) in clauses.items():
        if feature and feature not in features:decoded[name]=False;continue
        matches=[clause in requirement for clause in [false_clause,true_clause]]
        if sum(matches)!=1:raise ValueError('Unsupported or ambiguous controlled-language clause: '+name)
        decoded[name]=matches[1]
    return reference_plan({'features':features,'policy':decoded})


def main():
    out=ROOT/'artifacts/scale-rule-control';lib=library()
    protocol=('Added while third-round generation is ongoing, before reading any third-round model hidden score. '
              'This deterministic control receives public requirement text and features only. '
              'It recognizes exact benchmark template clauses, not unrestricted natural language. '
              'No task policy field, task ID, hidden data, expected state or model response is passed to the parser. '
              'If emitted HTML is byte-identical to the already-calibrated reference, reuse that public/hidden evaluation '
              'and record both hashes and evidence paths, rather than counting a new browser trial. Zero API calls.')
    dump(out/'manifest.json',{'script_sha256':digest(Path(__file__).read_text()),'protocol':protocol,
                             'primary_manifest_sha256':digest(json.loads((ROOT/'artifacts/scale-study/manifest.json').read_text()))})
    rows=[]
    for task in tasks():
        plan=public_plan(task['requirement'],task['features'])
        code=compile_plan(plan,task['features'],lib)
        app=write_app(out/task['id']/'index.html',task,code)
        reference=ROOT/'artifacts/scale-study/calibration/reference'/task['id']
        assert digest(app.read_text())==digest((reference/'index.html').read_text())
        rows.append({'task_id':task['id'],'app':str(app),'app_sha256':digest(app.read_text()),'plan':plan,
                     'calibration_evidence':str(reference),
                     'public':json.loads((reference/'public/evaluation.json').read_text()),
                     'hidden':json.loads((reference/'hidden/evaluation.json').read_text())})
    dump(out/'results.json',{'new_api_calls':0,'new_model_samples':0,'passed':sum(r['hidden']['behavior_passed'] for r in rows),'n':len(rows),'runs':rows})
    print({'public_text_rule_control_passed':sum(r['hidden']['behavior_passed'] for r in rows),'n':len(rows),'new_api_calls':0})


if __name__=='__main__':main()
