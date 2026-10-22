"""One explicit recovery window for two exhausted upstream-overload requests."""
from pathlib import Path
import json
import shutil
import compact_pair as study
from gui_dna.provider import OpenRouter
from gui_dna.library import digest
from gui_dna.tasks import dump

root=study.OUT
allowed={root/'runs/deepseek__deepseek-v4-pro-0813/v2-edit-filter-pagination/repeat-0'/m/'candidate-0/call' for m in study.METHODS}


class RecoveredRouter(OpenRouter):
    def call(self,model,messages,out,purpose,max_tokens=None,seed=None):
        out=Path(out)
        if out in allowed:
            original=json.loads((out/'request.json').read_text())
            assert original['body']['model']==model and original['body']['messages']==messages
            out=out/'manual-recovery-1'
            purpose+=':transport-recovery-1'
        return super().call(model,messages,out,purpose,max_tokens,seed)


if __name__=='__main__':
    archive=root.parent/'compact-pair-429-archive'
    if not archive.exists():
        archive.mkdir()
        for name in ['results.json','generation-complete.json']:
            if (root/name).exists():shutil.move(root/name,archive/name)
        for path in list((root/'runs').glob('*/*/*/*/*hidden')):
            target=archive/path.relative_to(root);target.parent.mkdir(parents=True,exist_ok=True)
            shutil.move(path,target)
    dump(root/'recovery.json',{'reason':'DeepInfra upstream_provider_shared_pool engine_overloaded; more than 160 seconds since previous attempts',
         'scope':'One additional three-POST maximum window for each of the two specifically listed failed calls; every POST separately reserved; original unknown costs retained',
         'calls':[str(p) for p in sorted(allowed)],'source_sha256':digest(Path(__file__).read_text()),
         'model_prompts_and_budgets_unchanged':True,'hidden_feedback_used':False,'previous_hidden_outputs_archived_and_not_reused':True})
    study.OpenRouter=RecoveredRouter
    study.main()
