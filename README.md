# GUI DNA 组合生成研究原型

基于 [DNA（ICLR 2026）](https://proceedings.iclr.cc/paper_files/paper/2026/hash/9f94298bac4668db4dc77ddb0a244301-Abstract-Conference.html) 的免训练 GUI 迁移：从通过测试的开发实现学习函数库，分解需求，组合 JavaScript，再用浏览器检查和有限修复。研究问题是：给同一函数库附加状态读写与可执行约束，是否改善未见功能组合？

这是固定页面框架下的交互逻辑生成原型。模型生成 `reduce(state,event)` 与 `select(state)`，原生 HTML/CSS/JavaScript 框架负责绘制和事件记录。它不评估任意网页布局、视觉设计或完整软件工程能力，不主张形式化证明、方法独特性或顶会竞争力。

已完成两模型、八任务、两次采样、四方法的 128 个候选实验（32 个完整配对组）。[中文研究报告](研究报告.md) 说明 DNA 论文逻辑、迁移思路、实际方法调整、结果和论文写作局限；[完整实验表](artifacts/live/report.md) 与 [原始记录](artifacts/live/results.json) 可核查。约束法与普通 DNA 在 Qwen 上均为 15/16、DeepSeek 上均为 16/16，未观察到新增约束的通过率收益。已结算费用 $0.424867，含不确定费用预留的记账敞口 $0.496063。

第二轮新增 Qwen3 Coder Plus、DeepSeek V4 Pro 0813，完成 264 个候选（含 24 个确定性参照）。预加载函数库、只生成连接代码后，两模型最终均为 12/12，输出 token 比普通 DNA 减少 51.6% / 53.4%；状态约束尚未在两模型上均提高最终正确率。严格计划生成出现退化，原始负结果保留；新增连接器另用保存响应做离线事后复验。详见[第二轮中文报告](第二轮研究报告.md)、[完整指标](artifacts/followup/combined-report.md)、[主协议](artifacts/followup/protocol.md)及[配置](configs/followup.json)。累计已结算 $1.578579，含未确认费用预留的记账敞口 $3.300928。

```bash
uv run python -m gui_dna.followup.calibrate
uv run python -m gui_dna.followup.study
```

补充实验脚本分别为 `experiments/linked_control.py` 和 `experiments/compact_pair.py`。它们按冻结配置运行并复用已完成候选；新的付费实验应使用独立输出目录。已有结果的汇总和连接器离线复验不调用 API：

```bash
uv run python experiments/summarize_followup.py
uv run python experiments/replay_linked_plans.py
```

离线修复只移除已知未启用节点，仍检查必要功能、事件绑定与执行顺序；没有更改原实验生成器、评分规则或成绩。其 48 组重放属于事后分析，不计入 264 个原始候选，也不能声称优于已经达到 100% 的确定性参照。[离线全功能页面](artifacts/followup/demo/index.html)可直接打开。

第三轮扩大到 16 个需求配置、每任务 5 次采样、两个模型和四方法，目标 640 个新模型候选。目前按用户要求暂停在190个完成候选，47个完整四方法组进入阶段统计，尚余450个候选位置。[阶段报告](第三轮研究报告.md)和[下次续跑说明](继续实验.md)保存了结果、断点和预算。累计已结算 $2.412397，含历史未知预留的敞口 $4.134746；新增模型调用已暂停。

配置与停止规则在 [scale-study.json](configs/scale-study.json) 和[固定协议](artifacts/scale-study/protocol.md)。新任务包含五种交互语义变化，编译器不读取评测策略答案。源码及提示词在首次模型调用前冻结。此次应用户要求先评价已冻结的部分，分阶段评价偏离原时序，详见[过程记录](artifacts/scale-study/pause-deviation.md)。

```bash
# 只检查，不解除暂停、不调用模型
uv run python -m experiments.resume_scale --check
# 下次明确继续时使用；复用现有候选与已结算响应
uv run python -m experiments.resume_scale --resume
```

```bash
uv run python -m experiments.scale_study.calibrate
uv run python -m experiments.scale_study.study
uv run python -m experiments.scale_study.analyze
# 无 API：固定句式需求解析控制，复用哈希一致的参考评测证据
uv run python -m experiments.scale_rule_control
```

第三轮原始 `study` 命令用于实验运行；当前人工暂停后请通过上述 `resume_scale` 入口续跑，不要直接解除账本或删除结果。它会校验冻结源文件及配置，复用完成候选，并保留阶段快照。两种计划方法收到完全相同的初始消息，用于隔离静态检查的作用；主要基线是同一函数库预加载后的自由连接代码。正确率按完整四方法组计算，费用包含所有尝试。统计按功能家族聚类，避免把重复采样视作独立任务。

第二轮评测分别报告可见行为正确率与内部状态合规率，不能直接与第一轮严格状态指标合并。旧结果、旧页面和 [第一轮源码归档](artifacts/v1-source.tar.gz) 保留；当前代码新增了实验和共享输入事件修复，若用当前代码重跑第一轮，应指定新的 `--out`，不要覆盖旧运行清单。

## 安装

需要 Python 3.13 与 [uv](https://docs.astral.sh/uv/)。

```bash
uv sync --extra dev
uv run playwright install chromium
# Linux 系统缺少浏览器运行库时，且有管理员权限：
uv run playwright install-deps chromium
```

当前工作环境缺少 `libnspr4` / `libnss3` 且没有免密 sudo，已解包到项目 `.browser-deps/`，评测子进程自动使用它们。在类似 Debian/Ubuntu 环境可重建：

```bash
mkdir -p .browser-deps
(cd .browser-deps && apt download libnspr4 libnss3)
for package in .browser-deps/*.deb; do dpkg-deb -x "$package" .browser-deps; done
```

其他缺失依赖按 Playwright 官方安装说明处理；本地解包方案只解决这两个库。首次安装需要网络，安装完成后的离线流程不调用 API。

## 四个命令

先验证评测器：手写正确实现必须通过八种组合，四个注入故障必须失败。失败会保存 PNG 截图和 JSON 状态轨迹。

已生成的四类故障截图：[取消编辑写回数据](artifacts/selfcheck/mutants/cancel-mutates-data/checks/base-edit.png)、[删除后页码越界](artifacts/selfcheck/mutants/page-out-of-bounds/checks/heldout-order-1.png)、[保存后筛选未更新](artifacts/selfcheck/mutants/stale-filter-after-save/checks/heldout-order-1.png)、[重复撤销](artifacts/selfcheck/mutants/repeated-undo/checks/base-undo.png)。这些是评测器校准用的注入故障；真实模型的失败证据位于各实验候选目录。

```bash
uv run gui-dna evaluate --self-check --out artifacts/selfcheck
uv run pytest -q
```

离线完整流程：

```bash
uv run gui-dna learn-library --offline
uv run gui-dna generate --offline --requirement '支持搜索、筛选、排序、分页、编辑、删除和撤销的列表' --out artifacts/demo
uv run gui-dna generate --offline --task test-search-edit-pagination --out artifacts/demo-combination
uv run gui-dna evaluate --app artifacts/demo-combination/index.html --task test-search-edit-pagination --out artifacts/demo-evaluation
uv run gui-dna compare --offline
```

直接打开 `artifacts/demo/index.html` 即可操作全部七项功能，无服务器、无网络依赖。`compare --offline` 生成 8 × 4 个确定性候选与 `artifacts/offline/report.md`。**离线四种方法共用参考组合器，只验证工程流程，不是模型能力对照，也不是研究结论。**

真实实验使用环境中已有的 `OPENROUTER_API_KEY`，不写入文件或日志：

```bash
uv run gui-dna learn-library
uv run gui-dna compare
# 单次真实生成：
uv run gui-dna generate --method constrained --task test-delete-pagination --out artifacts/custom-run
```

`generate --requirement '...'` 支持七类功能的中英文关键词；`--features search edit pagination` 可以显式指定，模型仍负责需求分解和实现。自然语言接口限定于本项目定义的列表语义，不是开放域需求理解。自定义任务的完整需求保存于 `manifest.json`。`evaluate --task` 用于预注册任务；自定义页面可用 Python `evaluate(app, task, out, suite='public')` 检查对应任务对象。

实验配置在 `configs/experiment.json`，通过 `gui-dna --config path.json ...` 指定。冻结库及完整候选可以复用；中断恢复会复用已结算的原始响应。检测到篡改、配置变化或无法确认状态的中断请求时停止，不覆盖或重发。要做新的采样，选择新的输出目录；累计预算账本仍共用。

## 实验协议

- 开发集 16 项：七种单功能各两例，以及搜索＋排序、筛选＋删除。撤销单功能从预置删除历史开始。需求与参考代码保存于 `data/dev/`。
- 测试集 8 种未见组合：搜索＋分页、筛选＋分页、编辑＋筛选、编辑＋排序、删除＋分页、删除＋撤销、搜索＋编辑＋分页、筛选＋排序＋删除。
- 四种方法：`direct` 直接生成；`retrieval` 按功能集合 Jaccard 检索两个开发实现；`dna` 函数库＋需求分解；`constrained` 相同函数代码＋状态读写、前后断言和约束检查。
- 用配置中的 `library_model`（`deepseek/deepseek-v3.2`）从全部通过测试的开发实现学习一份共享函数库，两个评测模型复用它。函数名和适配接口固定，代码、说明和依赖由模型归纳；不是训练权重。每次学习最多修复两轮，开发验证全部通过才冻结并记录 SHA-256。前期无契约注释的 Qwen/DeepSeek 学习输出未通过约束校验，失败构建保留于 `artifacts/library-learning-attempt-*`，费用计入总额。
- **实际方法调整：最终学习输入增加 `data/dev/annotations.json` 中人工编写的开发参考契约。模型抽取契约后仍必须通过验证。不能将本轮结果解释为模型自主发现契约或完全自动的契约学习成功。** 调整发生在测试候选生成前，只依据开发反馈；没有向模型提供隐藏测试。研究假设缩小为“附加这些经过验证的状态约束，是否改善组合正确率”。
- 最终冻结库的八个函数体与后置断言均与开发参考标注逐字相同。本轮的库构建实际完成了结构化提取与验证，没有证据表明模型发现了新函数或新契约。
- `qwen/qwen3-coder-30b-a3b-instruct` 与 `deepseek/deepseek-v3.2` 各跑八个任务、每任务两次、每次四方法，共 128 个最终候选。两次用不同 seed；所有方法相同温度、最大输出与最多两轮修复。provider 是否实际保证 seed 可复现不作假设。
- 学习阶段首个 Novita 响应计费后正文为 `null`，原始响应与费用保留。后续固定 Qwen 的提供商顺序为 Alibaba、DeepSeek 为 DeepInfra，禁用 fallback；全套对照的四方法共用这些路由设置。空正文作为一次已计费的无效候选，消耗既定修复预算。
- 四方法都获得相同公开功能检查；约束方法额外获得冻结库契约的检查。普通 DNA 的上下文移除 reads/writes/pre/post，但保留同一函数代码、接口说明和依赖。
- 共享 `deriveView` 已覆盖列表流水线，因此基线可能很强、容易出现天花板。这是研究局限，不能将持平解释为改善。

隐藏测试在 `src/gui_dna/suites.py`，独立 Python 状态规则在 `oracle.py`，从不进入 prompt。隐藏数据含新 id、重复名称、得分并列、负数、空列表、不同页长和操作顺序。**这里的“隐藏”指对生成器隐藏，源码对研究复现者公开。** 对比运行先完成全部生成与公开修复，冻结候选，再统一开始隐藏评测；隐藏失败不用于修复、挑选最佳候选或追加调用。

固定渲染器只复制、绑定、渲染和记录状态，不代替候选实现筛选、排序、分页校正等业务逻辑。评测逐步核对状态和真实 DOM，包括草稿、列表顺序、计数和按钮状态。浏览器在独立进程中运行，每候选有墙钟超时，外部资源请求被拦截；不向候选提供 API 密钥。

## 成本与记录

项目累计账本固定为 `artifacts/budget.sqlite3`，不要删除或替换它来继续同一项目的实验。

- 当前累计硬上限 $9；已结算费用＋未结算预留＋新请求预留超过 $8.8 时停止新请求，保留 $0.2 缓冲。第二轮已收紧持久化策略，旧配置中的 $10 / $9 不会提高现有账本上限。
- SQLite `BEGIN IMMEDIATE` 原子预留，跨线程/进程共享。预留依据 UTF-8 字节保守输入上界、最大输出 token、强制 provider 价格上限；禁用 provider fallback 和 HTTP 传输层重试。
- 对 HTTP 429 限流最多退避重试两次，每次 POST **重新独立预留费用**，原请求无法确认的费用继续保留。重试遵守数字形式的 Retry-After，至少等待 30/60 秒。模型候选预算仍为一次生成＋最多两次修复，所有方法使用相同的网络重试规则。其余错误不自动重发。
- 响应按 OpenRouter `usage.cost` 结算，并保存 token、provider/model 元数据、耗时和 generation id。超时、缺失费用等无法确认收费的请求保留全部预留，不当作免费请求。
- 若实际收费超过预留，已知费用仍入账并停止后续请求。预算依赖服务方遵守价格上限、token 上限和收费字段，不声称能控制第三方异常计费。
- 函数库费用单独汇总且计入项目总额。每个配对组先尝试四方法；中途预算/接口失败则停止扩展，只汇总实际完成的完整四方法组，部分结果仍保留。

每候选目录保存输入需求、完整 prompt、原始响应、分解与共享状态说明、各候选 JS/HTML、公开评测、最终冻结哈希、隐藏评测与失败截图。API 密钥不写入任何这些文件。报告定义组合通过率、已有功能保留率、可运行率、费用与耗时，并列出约束法相对基线的配对胜/负/平。

## 文件导航

| 路径 | 内容 |
|---|---|
| `src/gui_dna/library.py` | 开发集验证、函数库归纳、约束验证与冻结 |
| `src/gui_dna/prompts.py` | 各方法 prompt 与上下文边界 |
| `src/gui_dna/generation.py` | 生成和最多两轮公开修复 |
| `src/gui_dna/evaluation.py` | Playwright 执行、DOM/状态比较、证据 |
| `src/gui_dna/oracle.py`, `suites.py` | 独立评测规则与保留测试 |
| `src/gui_dna/budget.py`, `provider.py` | 持久化预留与 OpenRouter 单次请求 |
| `src/gui_dna/experiment.py` | 平衡实验、冻结屏障与报告 |
| `src/gui_dna/followup/` | 第二轮原子库、计划编译、行为/状态分离评测与八组消融 |
| `experiments/` | 预加载强基线、同等接口配对、离线连接器与汇总脚本 |
| `第二轮研究报告.md` | 优化逻辑、完整正负结果、事后修复与论文表述边界 |
| `artifacts/selfcheck/` | 正确实现、注入错误、失败截图与轨迹 |
| `artifacts/offline/`, `artifacts/live/` | 离线和真实实验结果，分别解释 |
| `third_party/DNA/` | 上游来源、commit、迁移说明、Apache-2.0 许可证 |
| `list.txt` | 用户原有资料列表，保留原样 |

上游参考 [官方代码](https://github.com/marcusm117/DNA)，迁移关系与实现差异见 `third_party/DNA/NOTICE.md`。API 使用依据 [OpenRouter 接口](https://openrouter.ai/docs/api_reference/overview) 和 [费用记录说明](https://openrouter.ai/docs/cookbook/administration/usage-accounting)，浏览器依赖依据 [Playwright 安装文档](https://playwright.dev/python/docs/intro)。
