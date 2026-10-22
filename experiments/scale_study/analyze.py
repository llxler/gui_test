"""Fixed contrasts and family-cluster bootstrap; no hidden-result selection."""
from collections import defaultdict, Counter
import json
import random

from gui_dna.tasks import ROOT,dump
from gui_dna.budget import Ledger
from .domain import METHODS

OUT=ROOT/'artifacts/scale-study'


def paired_interval(pairs, seed, samples):
    """Resample feature families, retaining all task variants and repeated seeds."""
    by_family=defaultdict(list)
    for family,difference in pairs:by_family[family].append(difference)
    if not pairs:return None
    families=sorted(by_family);rng=random.Random(seed);values=[]
    for _ in range(samples):
        rows=[d for family in rng.choices(families,k=len(families)) for d in by_family[family]]
        values.append(sum(rows)/len(rows))
    values.sort()
    return [values[int(.025*samples)],values[min(samples-1,int(.975*samples))]]


def main():
    config=json.loads((ROOT/'configs/scale-study.json').read_text())
    data=json.loads((OUT/'results.json').read_text());runs=data['runs'];groups=defaultdict(dict)
    for r in runs:
        key=(r['model'],r['task_id'],r['repetition'])
        assert r['method'] not in groups[key]
        groups[key][r['method']]=r
    complete={k:v for k,v in groups.items() if set(v)==set(METHODS) and all(r['status']=='generated' for r in v.values())}
    accounting=Ledger(ROOT/'artifacts/budget.sqlite3').summary();rows=[];contrasts=[]
    for model in config['models']:
        selected=[g for k,g in complete.items() if k[0]==model]
        for method in METHODS:
            records=[g[method] for g in selected]
            all_attempted=[r for r in runs if r['model']==model and r['method']==method]
            ids={json.loads(p.read_text())['call_id'] for r in all_attempted for p in (ROOT/r['directory']).rglob('request.json')}
            calls=[c for c in accounting['calls'] if c['id'] in ids]
            rows.append({'model':model,'method':method,'n':len(records),'tasks':len({r['task_id'] for r in records}),
                         'families':len({r['family'] for r in records}),'attempted':len(all_attempted),
                         'transport_failed':sum(r['status']=='transport_failed' for r in all_attempted),
                         'budget_stopped':sum(r['status']=='budget_stopped' for r in all_attempted),
                         'first_passed':sum(r['first_hidden']['behavior_passed'] for r in records),
                         'passed':sum(r['hidden']['behavior_passed'] for r in records),
                         'state_passed':sum(r['hidden']['state_passed'] for r in records),
                         'runnable':sum(r['hidden']['runnable'] for r in records),
                         'base_passed':sum(r['hidden']['base_passed'] for r in records),
                         'base_total':sum(r['hidden']['base_total'] for r in records),
                         'repairs':sum(max(0,r['attempts']-1) for r in all_attempted),
                         'known_usd':sum(c['actual'] or 0 for c in calls)/1e6,
                         'unknown_reserve_usd':sum(c['reserved'] for c in calls if c['actual'] is None)/1e6,
                         'input_tokens':sum(json.loads(c['usage'] or '{}').get('prompt_tokens',0) for c in calls),
                         'output_tokens':sum(json.loads(c['usage'] or '{}').get('completion_tokens',0) for c in calls),
                         'mean_generation_seconds':sum(r['elapsed_seconds'] for r in all_attempted)/len(all_attempted) if all_attempted else None})
        for baseline in ['linked_js','dna','plan_unchecked']:
            for metric in ['first_hidden','hidden']:
                pairs=[(g['plan_checked']['family'],int(g['plan_checked'][metric]['behavior_passed'])-int(g[baseline][metric]['behavior_passed'])) for g in selected]
                differences=[d for _,d in pairs]
                contrasts.append({'model':model,'baseline':baseline,'metric':metric,'n':len(pairs),
                                  'wins':differences.count(1),'losses':differences.count(-1),'ties':differences.count(0),
                                  'delta':sum(differences)/len(differences) if differences else None,
                                  'family_cluster_ci95':paired_interval(pairs,config['bootstrap_seed'],config['bootstrap_samples'])})
    per_task=[]
    for model in config['models']:
        for task_id in sorted({k[1] for k in complete if k[0]==model}):
            selected=[g for k,g in complete.items() if k[0]==model and k[1]==task_id]
            per_task.append({'model':model,'task_id':task_id,'n':len(selected),
                             'passed':{m:sum(g[m]['hidden']['behavior_passed'] for g in selected) for m in METHODS}})
    result={'summary':rows,'contrasts':contrasts,'per_task':per_task,'complete_groups':len(complete),
            'incomplete_groups':len(groups)-len(complete),'status_counts':dict(Counter(r['status'] for r in runs)),
            'stops':data['stops'],'accounting':accounting}
    dump(OUT/'analysis.json',result)
    lines=['# 第三轮扩大实验：全部结果','',
           '| 模型 | 方法 | 完整配对 n | 首次通过 | 最终通过 | 状态合规 | 基础保留 | 可运行 | 修复 | 已结算 USD | 未确认预留 USD | 输出 tokens |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['model']} | {r['method']} | {r['n']} | {r['first_passed']} | {r['passed']} | {r['state_passed']} | {r['base_passed']}/{r['base_total']} | {r['runnable']} | {r['repairs']} | {r['known_usd']:.6f} | {r['unknown_reserve_usd']:.6f} | {r['output_tokens']} |")
    lines+=['',f"完整四方法组 {len(complete)}；不完整组 {len(groups)-len(complete)}；全部状态 {result['status_counts']}。",'',
            '正确率只使用预先规定的完整配对组；费用、token、修复及耗时包含所有已尝试记录（包括不完整组）。精确分母、输入tokens、耗时与逐任务结果见 analysis.json。', '',
            '相对 plan_checked 的固定配对比较（差值为 plan_checked − baseline）：','']
    for c in contrasts:
        lines.append(f"- {c['model']} / {c['baseline']} / {c['metric']}：胜{c['wins']}、负{c['losses']}、平{c['ties']}；差值 {c['delta']}，8 类功能家族聚类 bootstrap 95% 区间 {c['family_cluster_ci95']}。")
    lines+=['','区间按实际存在的功能家族聚类重采样，保留组内任务变体和全部重复采样；不把80个候选看作80类独立任务。家族数至多8，区间仍是小样本探索估计，退化为[0,0]不代表统计等价证明。主要比较为最终 plan_checked 对 linked_js，两个模型分别报告，其余为次要比较。', '',
            f"累计项目已结算 ${accounting['actual_usd']:.6f}；含未知预留敞口 ${accounting['exposure_usd']:.6f}；未结算请求 {accounting['unsettled_calls']}。未知费用未释放。", '',
            '预先固定的源文件、需求、配置、分析规则和协议见 manifest.json 与 protocol.md；原始隐藏证据在 results.json 和 runs/。未以隐藏结果选择候选、修复或删减失败。']
    (OUT/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:result[k] for k in ['summary','contrasts','complete_groups','incomplete_groups','status_counts','stops']},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
