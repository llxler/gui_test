"""Eight-arm ablation (one deterministic), with a generation/evaluation barrier."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import json
import time

from ..budget import Ledger, BudgetStop
from ..generation import retrieve
from ..library import digest
from ..prompts import INTERFACE
from ..provider import OpenRouter, ProviderError, parse_json
from ..render import write_app
from ..tasks import ROOT, dump
from .domain import METHODS, tasks, atomic_library, expected_plan, compile_plan
from .evaluator import evaluate


def messages_for(task, method, library):
    instruction = INTERFACE + '\nImplement only the requested enabled features. Keep items as canonical data; derive visible rows in select. Never add edit snapshots to deletion history.'
    user = {'requirement': task['requirement'], 'features': task['features'], 'initial_example': task['initial']}
    if method == 'retrieval':
        user['development_examples'] = retrieve(task)
    elif method != 'direct':
        keys = ['name', 'feature', 'code', 'description', 'requires']
        if method in ('metadata', 'constrained', 'compiled', 'deterministic'):
            keys += ['reads', 'writes', 'pre', 'post']
            user['state_contracts'] = library['constraints']
            instruction += '\nExplain shared-state dependencies; preserve all state fields outside each event write set. Satisfy the supplied pre/post expressions.'
        user['functions'] = [{k: v for k, v in f.items() if k in keys} for f in library['functions']]
        instruction += '\nDecompose the requirement, choose functions from this shared atomic library and connect their interfaces. There is no pre-built complete selector or reducer.'
    if method in ('compiled', 'deterministic'):
        instruction += ('\nOverride the JSON output schema above: return {"decomposition":[...],"plan":{'
            '"view":["row transform function names, ending with pageRows"],'
            '"handlers":{"event type":"function name"},"normalize":"normalizePage",'
            '"normalize_when":"after_each_event"}}. Do not output code.'
            ' The compiler inserts the unchanged library function bodies, checks complete enabled-event coverage,'
            ' permits each enabled search/filter/sort row transform once, ensures pageRows is last,'
            ' checks selector functions are read-only, and clamps page after every reducer event'
            ' using the pre-pagination row count. Choose the pipeline and routes explicitly.')
    return [{'role': 'system', 'content': instruction}, {'role': 'user', 'content': json.dumps(user, ensure_ascii=False)}]


def generate(task, method, library, model, repetition, config, provider, folder):
    folder.mkdir(parents=True, exist_ok=True)
    identity = {'task': task, 'method': method, 'library': library['sha256'], 'model': model,
                'repetition': repetition, 'config': config}
    fingerprint = digest(identity)
    if (folder / 'result.json').exists():
        old = json.loads((folder / 'result.json').read_text())
        assert old['fingerprint'] == fingerprint, 'Changed run configuration'
        for version in old['versions']:
            assert digest(Path(version['app']).read_text()) == version['app_sha256'], 'Changed candidate'
        return old
    dump(folder / 'manifest.json', {**identity, 'fingerprint': fingerprint})
    started = time.monotonic()
    messages = messages_for(task, method, library)
    contracts = [f for f in library['constraints'] if f['feature'] in ['core', *task['features']]] if method in ('checks', 'constrained', 'compiled', 'deterministic') else []
    versions = []
    for attempt in range(config['max_repairs'] + 1):
        version = folder / f'candidate-{attempt}'
        dump(version / 'messages.json', messages)
        if method == 'deterministic':
            raw = json.dumps({'decomposition': ['Deterministic feature-to-plan mapping; no model call'], 'plan': expected_plan(task['features'])})
        else:
            raw = provider.call(model, messages, version / 'call', f'v2:{model}:{task["id"]}:{repetition}:{method}:{attempt}', seed=config['seed'] + repetition)
        compile_error = None
        try:
            output = parse_json(raw)
            code = compile_plan(output.get('plan'), task['features'], library) if method in ('compiled', 'deterministic') else output['code']
            if not isinstance(code, str): raise ValueError('code must be a string')
            if method not in ('direct', 'retrieval') and not output.get('decomposition'):
                raise ValueError('Provide the requested decomposition')
            dump(version / 'output.json', output)
        except (ValueError, KeyError, TypeError) as error:
            compile_error = str(error)
            code = 'window.candidate={};'
        (version / 'candidate.js').write_text(code)
        app = write_app(version / 'index.html', task, code)
        if compile_error:
            feedback = {'passed': False, 'compile_error': compile_error}
        else:
            public = evaluate(app, task, version / 'public', contracts=contracts)
            feedback = {'passed': public['passed'], 'error': public.get('error'), 'failures': [
                {'name': c['name'], 'failure': c.get('failure'), 'actions': c['actions'],
                 'contract_failures': c['contract_failures'][:2]} for c in public['cases'] if not c['passed']]}
        dump(version / 'feedback.json', feedback)
        versions.append({'app': str(app.resolve()), 'app_sha256': digest(app.read_text()),
                         'code_sha256': digest(code), 'public_passed': feedback['passed'], 'compile_error': compile_error})
        if feedback['passed']: break
        messages += [{'role': 'assistant', 'content': raw},
                     {'role': 'user', 'content': 'Fix the candidate using only this public feedback. Return the complete requested JSON.\n' + json.dumps(feedback, ensure_ascii=False)}]
    result = {'fingerprint': fingerprint, 'model': model, 'method': method, 'task_id': task['id'],
              'repetition': repetition, 'versions': versions, 'directory': str(folder.resolve()),
              'attempts': len(versions), 'elapsed_seconds': time.monotonic() - started}
    dump(folder / 'result.json', result)
    return result


def summarize(records, accounting, stopped):
    groups = defaultdict(dict)
    for r in records: groups[(r['model'], r['task_id'], r['repetition'])][r['method']] = r
    complete = {key: value for key, value in groups.items() if set(value) == set(METHODS)}
    summary = []
    for model in sorted({key[0] for key in complete}):
        for method in METHODS:
            rows = [v[method] for k, v in complete.items() if k[0] == model]
            ids = {json.loads(p.read_text())['call_id'] for r in rows for p in Path(r['directory']).rglob('request.json')}
            calls = [c for c in accounting['calls'] if c['id'] in ids]
            summary.append({'model': model, 'method': method, 'n': len(rows),
                'first_passed': sum(r['first_hidden']['behavior_passed'] for r in rows),
                'passed': sum(r['hidden']['behavior_passed'] for r in rows),
                'state_passed': sum(r['hidden']['state_passed'] for r in rows),
                'initial_passed': sum(r['hidden']['initial_passed'] for r in rows),
                'runnable': sum(r['hidden']['runnable'] for r in rows),
                'base_retention': sum(r['hidden']['base_passed'] for r in rows)/sum(r['hidden']['base_total'] for r in rows),
                'repairs': sum(r['attempts'] - 1 for r in rows),
                'generation_usd': sum(c['actual'] or 0 for c in calls)/1e6,
                'output_tokens': sum(json.loads(c['usage'] or '{}').get('completion_tokens', 0) for c in calls),
                'mean_seconds': sum(r['elapsed_seconds'] for r in rows)/len(rows)})
    paired = []
    for model in sorted({key[0] for key in complete}):
        for baseline in METHODS[:-1]:
            for metric in ['first_hidden', 'hidden']:
                differences = [int(v['compiled'][metric]['behavior_passed']) - int(v[baseline][metric]['behavior_passed']) for k, v in complete.items() if k[0] == model]
                paired.append({'model': model, 'baseline': baseline, 'metric': metric,
                               'wins': differences.count(1), 'losses': differences.count(-1), 'ties': differences.count(0)})
    return {'complete_groups': len(complete), 'incomplete_groups': len(groups) - len(complete),
            'summary': summary, 'paired': paired, 'accounting': accounting, 'stopped': stopped, 'runs': records}


def report_text(report):
    lines = ['# 第二轮：原子函数与可检查组合计划', '',
             '这是依据第一轮发现设计的新探索实验；第一轮指标与结果保持独立。所有隐藏检查均在全部生成结束后运行。', '',
             '| 模型 | 方法 | 首次行为通过 | 最终行为通过 | 内部状态合规 | 基础保留 | 费用 USD | 修复轮数 | 输出 tokens | 平均生成秒 |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in report['summary']:
        lines.append(f"| {s['model']} | {s['method']} | {s['first_passed']}/{s['n']} | {s['passed']}/{s['n']} | {s['state_passed']}/{s['n']} | {s['base_retention']:.1%} | {s['generation_usd']:.6f} | {s['repairs']} | {s['output_tokens']} | {s['mean_seconds']:.1f} |")
    lines += ['', f"完整八方法组 {report['complete_groups']}，未完成组 {report['incomplete_groups']}。仅完整组进入表格。", '',
              '首次/最终行为通过要求所有隐藏操作序列的可见行、控件、草稿、计数与按钮状态正确；内部状态合规另外比较完整规范状态，不用于主行为指标。基础保留按独立功能场景计算。费用和时间含公开检查与修复，不含共用库来源成本及最终隐藏评价。', '',
              'direct=直接生成；retrieval=开发实现检索；dna=原子函数＋分解；metadata=仅加状态约束说明；checks=仅加运行约束检查；constrained=说明＋检查；compiled=说明＋检查＋模型组合计划编译；deterministic=不调用模型，按已知功能直接构造同一编译计划。全部库方法共享相同函数代码。compiled 的编译器是被测机制，不是所有方法共用的渲染框架。确定性参照按组重复展示，不是独立模型采样。', '',
              '配对比较（compiled 相对基线）：', '']
    for p in report['paired']:
        lines.append(f"- {p['model']} / {p['baseline']} / {p['metric']}：胜 {p['wins']}、负 {p['losses']}、平 {p['ties']}。")
    a = report['accounting']
    lines += ['', f"累计项目已结算 ${a['actual_usd']:.6f}；含全部未结算预留的记账敞口 ${a['exposure_usd']:.6f}。共用第一轮库构建费 ${a['library_usd']:.6f} 已包含在项目总额中，新原子化库为人工重构，未额外调用模型构建。", '',
              '小样本不构成稳定收益或统计显著性结论。编译方法表达空间更窄，依赖人工定义的接口与合法组合规则；不能将编译保证外推到任意 GUI。']
    if report['stopped']: lines += ['', '停止原因：' + report['stopped']]
    return '\n'.join(lines) + '\n'


def run(config, out):
    out.mkdir(parents=True, exist_ok=True)
    library = atomic_library()
    manifest = {'config': config, 'requirements': tasks(), 'library': library,
                'protocol_sha256': digest((ROOT/'artifacts/followup/protocol.md').read_text()),
                'source_sha256': digest({str(p.relative_to(ROOT)): p.read_text() for p in sorted((ROOT/'src/gui_dna').rglob('*')) if p.suffix in ('.py', '.js', '.html')})}
    if (out/'manifest.json').exists():
        assert json.loads((out/'manifest.json').read_text()) == manifest, 'Study changed; do not overwrite a preregistered run'
    dump(out/'manifest.json', manifest)
    dump(out/'library.json', library)
    calibration = json.loads((out/'calibration.json').read_text())
    assert calibration['passed'] and calibration['library_sha256'] == library['sha256'], 'Calibrate before paid requests'
    ledger = Ledger(ROOT/'artifacts/budget.sqlite3', config['budget_usd'], config['stop_new_requests_usd'])
    provider = OpenRouter(config, ledger)
    generated, stopped = [], None
    with ThreadPoolExecutor(max_workers=config['workers']) as pool:
        for repeat in range(config['repetitions']):
            for task in tasks():
                for model in config['models']:
                    print(f'Generating {model} / {task["id"]} / repeat {repeat+1}', flush=True)
                    futures = [pool.submit(generate, task, method, library, model, repeat, config, provider,
                               out/'runs'/model.replace('/', '__')/task['id']/f'repeat-{repeat}'/method) for method in METHODS]
                    for future in futures:
                        try: generated.append(future.result())
                        except (ProviderError, BudgetStop, ValueError) as error: stopped = str(error)
                    if stopped: break
                if stopped: break
            if stopped: break
    dump(out/'generation-complete.json', {'candidates': generated, 'stopped': stopped})
    print(f'Generation frozen; hidden evaluation of {len(generated)} candidates (first and final)', flush=True)
    lookup = {t['id']: t for t in tasks()}
    def final_check(record):
        folder = Path(record['directory'])
        values = {}
        for label, version in [('first_hidden', record['versions'][0]), ('hidden', record['versions'][-1])]:
            assert digest(Path(version['app']).read_text()) == version['app_sha256'], 'Candidate changed after freeze'
            if label == 'hidden' and record['versions'][0]['code_sha256'] == version['code_sha256']:
                values[label] = values['first_hidden']
                continue
            path = folder/label/'evaluation.json'
            values[label] = json.loads(path.read_text()) if path.exists() else evaluate(version['app'], lookup[record['task_id']], folder/label, hidden=True)
        return {**record, **values}
    with ThreadPoolExecutor(max_workers=config['workers']) as pool:
        records = list(pool.map(final_check, generated))
    report = summarize(records, ledger.summary(), stopped)
    dump(out/'results.json', report)
    (out/'report.md').write_text(report_text(report))
    print(json.dumps({'complete_groups': report['complete_groups'], 'stopped': stopped, 'report': str(out/'report.md')}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT/'configs/followup.json')
    parser.add_argument('--out', type=Path, default=ROOT/'artifacts/followup')
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    assert config['methods'] == METHODS and config['max_repairs'] in range(3)
    run(config, args.out)


if __name__ == '__main__':
    main()
