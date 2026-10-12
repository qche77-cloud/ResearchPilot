# ResearchPilot v2.0：初步代码审查、测试基线与实施计划

日期：2026-10-12。审查对象：本地当前工作区，HEAD `81b9e2d`，包含用户已有未提交修改。本文不是对干净 Git 提交或线上环境的验收。

本轮按最新指示“先分析一下”完成核心链路审查、离线基线和设计建议，不实施业务升级，也不将计划标记为已完成。没有改写配置、迁移数据库、执行交易、联网研究或提交用户已有修改。

## 1. 当前架构

实际有两条研究入口，共用研究组件和 ResearchState：

- `app.py → app_service.py → research_service.py → pipeline.py`：顺序流水线，阶段检查点写入 researchpilot.db。
- `agent_app.py → background.Runner → agent.tick`：逐步执行、命令队列、显式暂停恢复、对话调整计划，使用同一套 Planner/Searcher/Reader/Evaluator/Synthesizer/Writer。

旧流水线包括分析、规划、搜索、读取、失败来源替换、评分、覆盖检查、一次补充搜索、综合、Research Health、写作。后台 Agent 包括个股数据采集、规划、决策、分批读取、综合、写作；已有证据缺口驱动选择和用户指令驱动重新规划。

`researchpilot.db`：research_runs 表保存完整 JSON 状态、阶段、错误和时间，schema_version=1；查询使用参数绑定和分页，连接启用 WAL。

`workbench.db`：preferences、watchlist、snapshots、theses、commands、monitors、alerts、stock_directory、stock_profiles、stock_runs、judgment_proposals、thesis_history。每次操作独立连接，20 秒锁等待；观点确认采用 BEGIN IMMEDIATE 和原记录比对，避免旧建议覆盖新复盘。该库未像研究库一样配置 WAL。

暂停在工具调用结束后处理，通过 Runner 的运行标志实现；ResearchState 没有独立 paused 状态。线程可跨浏览器断线运行，不能跨服务进程重启生存。持久化后显式恢复，并非操作系统级后台调度。

## 2. v2.0 能力现状

| 能力 | 判定 | 真实实现与缺口 |
|---|---|---|
| 自主规划、补充检索 | 部分实现 | agent.choose_action、evidence_strategy 已实现预算和覆盖驱动检索；缺少结构化假设及新证据驱动的明确修订记录 |
| 证据追溯 | 部分实现 | 来源 ID、证据 ID、逐字摘录、证据卡片、报告快照；不能证明摘录蕴含结论 |
| 行为轨迹与成本 | 部分实现 | events 保存 tool/reason/result，流水线有诊断；缺少统一调用 ID、起止时间、耗时、usage、费率版本和费用统计 |
| 工程评测 | 部分实现 | 多个离线脚本与 37 个现有 unittest；无统一四场景评测集、指标报告及 CI 入口 |
| 财务分析 | 部分实现 | 原始指标、明确单位时的 Decimal 换算、共同报告期对比；源同比字段只是展示，没有统一确定性增长/估值工具 |
| 图表 | 部分实现 | 股价曲线和日 K 线；缺少逐数据点绑定原始财务记录的财务分析图表 |
| 研究假设 | 部分实现 | 投资观点、支持/反面/问题档案及核查建议；不是 Agent 自动维护的可验证研究假设生命周期 |
| 证据关系图 | 部分实现 | finding → evidence → source 对象关联；无 hypothesis 节点、关系类型或图查询视图 |
| Critic / Verifier | 部分实现 | 引用和摘录校验、过期/列表页限制；无独立结论检查、数值一致性和矛盾检测模块 |
| 长期记忆与持续研究 | 部分实现 | 股票隔离档案、历史研究关联、基线快照、版本化复盘；缺少结构化结论/假设差异和失效判断 |
| 监控 | 部分实现 | 默认关闭；工作日上海时间 16 点后、间隔至少 20 小时；有失败提示；频率硬编码，主要监控日线变化而非公告/财报变化 |

不建议重做上述已有能力。README 的 v1.3 标记和部分模块注释已经落后于当前实现。

## 3. 问题清单与优先级

以下区分已复现问题与代码审查发现的风险，避免将未验证风险写成故障。

### P0：研究真实性与结论完整性

1. **旧流水线搜索降级为模拟来源（已复现）**。`Searcher.search` 在无密钥、无结果和调用异常时进入 `_mock_search`。无密钥的 QUICK 样本返回 4 条模板来源且 mode=mock。虽然有警告，但这些来源继续走读取/评分/综合路径。应将模拟数据限制到显式离线夹具；真实入口返回无证据/不可用状态，历史数据保持可读。Agent 新入口已经在缺 Tavily 时失败，不应反向移植旧降级行为。
2. **引用完整性不等于结论支持（已复现）**。`agent_chat.validate_citations` 接受“收入增长”的回答配上真实“收入下降”摘录；无引用的事实性回答也可通过。须增加逐结论验证、事实/推断区分和数值检查。不能把 citation_check 改名为事实验证来掩盖缺口。
3. **无效引用被删除而结论保留（已复现）**。`writer._sanitize_citations` 将不存在的 `[E99]` 删除，留下原结论。应保留检测结果，拒绝该结论或进行有界修复；同时对最终报告执行验证，而非仅对 synthesis 检查。

### P1：运行可靠性与评测

4. **两条入口的成功标准不同（代码发现）**。pipeline 末尾直接 mark_completed；Agent 会拒绝没有引用结论的结果并区分 partial。后台路径没有调用流水线的 Research Health 步骤。应建立共享的交付质量契约，兼容旧状态和 UI。
5. **并发保障限于单 Runner（代码发现）**。线程 Lock 防止同一 Runner 同任务双写；数据库没有 worker lease 或状态 revision 条件更新。多个服务实例可能覆盖同一快照。SQLite 事务不自动解决陈旧状态覆盖。需用临时库验证双 Runner 场景，再实现轻量抢占/版本检查。
6. **持久化失败恢复不足（代码发现）**。Runner 异常处理再次 save_state，若数据库持续不可写，二次异常可能逃出线程；初始读取位于 try 外。命令与状态分属两库，保存状态后 ack 有重放去重机制，但不是跨库原子事务，也不保证外部调用 exactly-once。
7. **预算尚非成本预算（代码发现）**。成功搜索限制 1–16，连续空结果会停；失败请求不计成功预算且本轮失败停止。反复手动恢复、对话、引用修复、双重规划会产生额外调用。需要累计 attempts/model calls/tokens/工具预算及最大迭代，不能只统计成功搜索。
8. **规划元数据可能不同步（代码发现，待测试）**。focus_plan 替换 steps，未重新 attach_evidence_strategies；可能丢失原任务策略、时效和来源偏好。应补定向测试后修复。
9. **Reader 获取边界不足（代码发现，未进行攻击测试）**。requests 自动跟随重定向并读取完整响应，未见私网地址限制和下载大小限制。随着自主工具能力扩大，应验证 URL/重定向、内容大小和 PDF 解析资源边界。
10. **测试执行形式混杂（已观察）**。unittest 与 main/assert 脚本并存，有些 test_*.py 实际调用真实接口。不能把一次 unittest discover 当完整回归，也不能无区别运行所有 test 文件。需要显式离线清单、网络阻断和实际用例数检查。

### P2：持续研究与维护

11. stock_history 对旧代码匹配历史只读取两个 100 条分页；显式 stock_runs 关联不受此截断。旧历史超过 200 条可能漏掉。
12. update_brief 主要识别日期晚于基线且 URL 新出现的来源，不检测同一 URL 的内容变化；列表页识别使用有限 URL 模式。
13. 监控外层异常被忽略；日线日期未变时不会报告财务变化。需要独立监控状态、来源、失败记录、可配频率和内容指纹。
14. 模型调用分散在多个模块，均使用 urllib Chat Completions 和 json_object + 手工校验；统一 provider 边界有明确收益。requirements 使用范围约束，无锁定环境/CI 配置；这是复现风险，不代表当前依赖缺失。

## 4. 2026-10-12 测试基线

环境：Windows PowerShell，项目 `.venv`，Python 3.11.4。测试在 socket.connect 阻断网络的进程运行；业务 mocks 保持不变。仅选取经检查的离线脚本。没有使用真实 OpenAI/Tavily/金融接口；这些结果不能证明最新数据源可用或真实模型质量。

| 测试入口 | 结果 |
|---|---|
| scripts.test_agent | 9/9 通过 |
| scripts.test_workbench | 7/7 通过 |
| scripts.test_stock_research | 8/8 通过 |
| scripts.test_judgments | 9/9 通过 |
| scripts.test_stock_presentation | 4/4 通过 |
| scripts.test_research_health | 脚本退出码 0 |
| scripts.test_v112_reader_reliability | 脚本退出码 0 |
| scripts.test_v121_regression | 脚本退出码 0 |
| scripts.test_v12_evidence_strategy | 脚本退出码 0 |
| scripts.test_v13_research_state | 脚本退出码 0 |
| scripts.test_v13_sqlite_storage | 脚本退出码 0 |
| scripts.test_v13_pipeline_state | 脚本退出码 0 |
| scripts.test_v13_persisted_research | 脚本退出码 0 |
| scripts.test_v13_app_persistence | 脚本退出码 0 |
| scripts.test_v13_history_queries | 脚本退出码 0 |
| scripts.test_v13_history_ui | 脚本退出码 0 |

最终有效基线：37 个 unittest 通过，耗时 8.573 秒；另 11 组 main/assert 回归脚本全部通过。Streamlit AppTest 有无 ScriptRunContext 的 bare-mode 提示，无用例失败。没有进行真实浏览器布局验收、进程重启验收和外部 API 连通性测试。

执行过程中最初用 runpy 运行 unittest 脚本得到“Ran 0 tests”；这些结果已排除，随后通过 loadTestsFromNames 正确执行了上述 37 项。旧测试脚本会修改 stdout 编码，因此部分终端中文乱码，但断言和退出状态有效。test_research_health 生成了其原有的 scripts/_research_health_example.json 输出，未改写业务代码。

当前没有标准数据集指标：引用有效率、语义支持率、数值一致率、矛盾检测 precision/recall、金融计算正确率、真实任务费用均尚未建立或测量，不能以这些测试通过率代替。

复现 37 项测试（PowerShell，含网络阻断）：

```powershell
@'
import socket, sys, unittest
socket.socket.connect = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('OFFLINE_NETWORK_BLOCKED'))
names = ['test_agent', 'test_workbench', 'test_stock_research', 'test_judgments', 'test_stock_presentation']
suite = unittest.defaultTestLoader.loadTestsFromNames(['scripts.' + n for n in names])
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
'@ | ./.venv/Scripts/python.exe -
```

其余 11 个 main/assert 入口可按表逐个在独立进程中用 `runpy.run_module('scripts.<name>', run_name='__main__')` 执行，并先安装相同网络阻断。它们不能当作 unittest 用例计数。

## 5. 增量实施方案（尚未实施）

### 第一阶段：先建立质量和观测闭环

- 创建独立离线测试入口，显式区分 fixture/offline/live；初步建立行业、公司、财务、冲突各 4 个样本，共 16 个固定时间点的合成夹具，明确不是真实公司披露。再逐步补脱敏且可再分发的真实材料。
- 样本记录 query、as_of、原始来源、任务覆盖目标、期待数值、冲突标签及允许结论。包括错误引用、真实摘录支持相反结论、单位混用、累计/单季混用、重复来源、列表日期、数据源失败和恢复场景。
- 分开报告 citation existence、逐字摘录有效率、任务覆盖率、确定性数值一致率和冲突检测 precision/recall；无法确定语义支持的样本标为 unknown，需要独立模型评判或人工标签，不冒充确定性证明。
- 引入统一 trace/provider 边界，先保持现有 Chat Completions。记录调用 ID、run/stage、模型/工具、起止时刻、耗时、成功/失败、重试、实际响应 usage。费用按带日期的可配置费率计算；usage 或费率缺失时为 unknown，离线模拟 usage 标记 fixture，不填真实费用。
- 复用 diagnostics 保存新增数据并验证旧快照兼容。现有序列化按敏感字段名过滤，需要新增测试确保 usage 计数正常保存、凭证与授权头不入库。
- 修复前三个已复现问题及入口成功标准。用临时库补暂停恢复、二次保存失败和双 Runner 测试，再按证据修可靠性问题。

验收：原有 37 项 + 11 组回归保持通过；新评测有机器可读报告和失败退出码；对每个预设缺陷能检测或明确报告 unknown；真实入口不得把 fixture 当真实证据。此时才发布第一阶段基线指标。

### 第二阶段：确定性金融证据

在 stock_data 与 stock_presentation 之上增加 financial_analysis，不替换源数据适配器。统一记录 symbol、metric、period_start/end、single/cumulative、currency、unit、consolidation、value、source URL、fetched_at、raw_record_id 和修订版本。明确单位依据后用 Decimal 标准化。

实现营业收入、净利润、毛利率、现金流多期对比；同比/环比必须比较同口径同长度期间。累计值先满足数据完整性条件才差分为单季；缺期间、未知单位、零分母、负基期、非有限值和合并口径差异明确给状态。亏损不能输出具有误导性的正常 PE，PE/PB 使用明确时点及 TTM/净资产定义。

图表从计算结果生成，每个点附 raw_record_id 和来源；结构化计算证据包含公式、输入和结果，LLM 只能解释。验收包括手算黄金样本、缺失/异常样本和 Agent 接入离线测试。

### 第三阶段：假设、反思、关系和验证

先在 ResearchState 扩展可默认缺省的假设结构，复用已有投资观点但分清用户观点和 Agent 假设。新增支持/反面/未解问题、判断、不确定性、版本和更新依据。

将“营收升、利润降”等确定性触发器接到修订计划，追加毛利率、费用率、业务结构；实行最大迭代、累计工具/模型预算、规范化重复搜索去重。Verifier 作为可测试逻辑角色置于写作前后，无需创建独立 Agent 服务。

关系图先由结构化记录派生 conclusion → hypothesis → evidence → source；有需要再加 SQLite 关系表和索引，不引入图数据库。查询必须绑定 run/version，避免重编号的 E1 在不同研究间混用。

### 第四阶段：持续研究与差异

复用股票关联、档案、report_versions、基线快照和 thesis_history。建立版本可比的假设/结论/财务差异；原 URL 内容更新用内容指纹和采集时间区分。保留用户确认后的观点，不自动覆盖。

增强现有监控：默认关闭、可配频率、数据来源、last_success、结构化 failure、内容变化判断。先在本地单进程可靠运行，不承诺停服后的调度。

### 第五阶段：当前稳定技术评估

尚未进行截至 2026-10-12 的官方在线文档核查，所以本文不声称任何技术是当前最新稳定版本。后续按用户技术清单核对官方来源，OpenAI 部分使用 OpenAI Docs，其他资料按 agent-reach 路由读取。

优先评估 provider 抽象、结构化输出、工具参数校验、分级模型路由及费用观测；Responses API 作为可切换 provider，先通过契约测试再集成。MCP 只有实际外部工具需求时接入。LangGraph/Deep Agents 暂无替换现有 tick/State 的必要证据。浏览器自动化只有普通 HTML/PDF 获取无法满足实际来源需求时评估，且先具备隔离边界。

## 6. 交付边界

本轮新增文件仅为本审查文档。已测试的是现有工作区，不是 v2.0 升级成果。未创建 Git commit，因为本轮仅分析且工作区已有用户未提交业务修改；未把这些改动打包提交。后续开发应显式选择本次文件提交，避免混入原有改动。

未发现阻止第一阶段离线开发的环境问题。外部数据可用性、真实模型质量和当前技术版本核查留待对应阶段；破坏性迁移、整体架构替换和大量付费调用仍需用户确认。
