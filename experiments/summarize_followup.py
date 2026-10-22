"""Combine every registered arm; no best-candidate selection or new API calls."""
from pathlib import Path
from collections import defaultdict
import json

from gui_dna.tasks import ROOT,dump
from gui_dna.budget import Ledger


def main():
    names=['followup','linked-control','compact-pair']
    studies={name:json.loads((ROOT/'artifacts'/name/'results.json').read_text()) for name in names}
    runs=[r for study in studies.values() for r in study['runs']]
    assert len({(r['model'],r['task_id'],r['repetition'],r['method']) for r in runs})==len(runs)
    accounting=Ledger(ROOT/'artifacts/budget.sqlite3').summary()
    groups=defaultdict(list)
    for r in runs:groups[(r['model'],r['method'])].append(r)
    rows=[]
    for (model,method),records in sorted(groups.items()):
        ids={json.loads(p.read_text())['call_id'] for r in records for p in Path(r['directory']).rglob('request.json')}
        calls=[c for c in accounting['calls'] if c['id'] in ids]
        rows.append({'model':model,'method':method,'n':len(records),
            'first_passed':sum(r['first_hidden']['behavior_passed'] for r in records),
            'passed':sum(r['hidden']['behavior_passed'] for r in records),
            'state_passed':sum(r['hidden']['state_passed'] for r in records),
            'initial_passed':sum(r['hidden']['initial_passed'] for r in records),
            'base_passed':sum(r['hidden']['base_passed'] for r in records),'base_total':sum(r['hidden']['base_total'] for r in records),
            'runnable':sum(r['hidden']['runnable'] for r in records),
            'repairs':sum(r['attempts']-1 for r in records),'known_usd':sum(c['actual'] or 0 for c in calls)/1e6,
            'mean_generation_seconds':sum(r['elapsed_seconds'] for r in records)/len(records),
            'unconfirmed_reserve_usd':sum(c['reserved'] for c in calls if c['actual'] is None)/1e6,
            'unconfirmed_requests':sum(c['actual'] is None for c in calls),
            'input_tokens':sum(json.loads(c['usage'] or '{}').get('prompt_tokens',0) for c in calls),
            'output_tokens':sum(json.loads(c['usage'] or '{}').get('completion_tokens',0) for c in calls)})
    paired=[]
    for model in sorted({r['model'] for r in runs}):
        for proposed,baseline in [('constrained','dna'),('linked_dna','dna'),('compiled','dna'),('compiled','constrained'),('compiled','linked_dna'),('compact_plan','compact_js'),('compact_plan','linked_dna'),('deterministic','dna')]:
            left={(r['task_id'],r['repetition']):r for r in runs if r['model']==model and r['method']==proposed}
            right={(r['task_id'],r['repetition']):r for r in runs if r['model']==model and r['method']==baseline}
            keys=left.keys()&right.keys()
            for metric in ['first_hidden','hidden']:
                diffs=[int(left[k][metric]['behavior_passed'])-int(right[k][metric]['behavior_passed']) for k in keys]
                paired.append({'model':model,'proposed':proposed,'baseline':baseline,'metric':metric,'n':len(keys),
                               'wins':diffs.count(1),'losses':diffs.count(-1),'ties':diffs.count(0)})
    result={'summary':rows,'paired':paired,'accounting':accounting,'study_stops':{k:v['stopped'] for k,v in studies.items()},'runs':runs}
    dump(ROOT/'artifacts/followup/combined-results.json',result)
    lines=['# 第二轮全部实验记录','',
           '| 模型 | 方法 | 首次通过 | 最终通过 | 状态合规 | 基础保留 | 可运行 | 修复 | 已结算 USD | 未确认预留 USD | 输入 tokens | 输出 tokens | 平均生成秒 |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['model']} | {r['method']} | {r['first_passed']}/{r['n']} | {r['passed']}/{r['n']} | {r['state_passed']}/{r['n']} | {r['base_passed']}/{r['base_total']} | {r['runnable']}/{r['n']} | {r['repairs']} | {r['known_usd']:.6f} | {r['unconfirmed_reserve_usd']:.6f} | {r['input_tokens']} | {r['output_tokens']} | {r['mean_generation_seconds']:.1f} |")
    lines += ['', '不同阶段均保留；同一任务的首次及最终版本按固定规则评分，不择优。只有双方都完成的同模型、任务、重复编号进入配对统计。确定性参照不调用模型，重复展示不构成独立模型采样。', '',
              '费用为已结算回执，未知费用另保留上界；不确定费用存在时，不能把已结算差额当作最终账单差额。Token统计来自成功返回的费用回执，路由错误没有可用token回执。', '',
              '平均生成秒包括模型调用、公开检查与修复，不含最终隐藏评测。首个Qwen组重放时间不含原始API等待，恢复、服务排队和并行负载也影响时间；只作描述，不据此宣称速度提升。', '',
              f"累计已结算 ${accounting['actual_usd']:.6f}；包含全部未确认预留的记账敞口 ${accounting['exposure_usd']:.6f}；未结算请求 {accounting['unsettled_calls']}。", '', '配对结果：', '']
    for p in paired:
        lines.append(f"- {p['model']}，{p['proposed']} 对 {p['baseline']}，{p['metric']}：胜{p['wins']} / 负{p['losses']} / 平{p['ties']}（n={p['n']}）。")
    (ROOT/'artifacts/followup/combined-report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'candidates':len(runs),'summary':rows,'paired':paired,'costs':{k:accounting[k] for k in ['actual_usd','exposure_usd','unsettled_calls']}},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
