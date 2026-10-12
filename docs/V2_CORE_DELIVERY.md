# 核心功能落地与验收记录

日期：2026-10-12。这是本地 v2.0 开发版本，含用户原有工作区修改；不是已经发布或完整生产认证的 Git 标签。

## 现在可直接使用

1. **多期财务分析**：个股工作台新增入口，可导入带来源的 JSON，也可在核对后声明旧快照的单位/币种/单季累计/合并母公司口径。计算同比、累计转单季、环比、毛利率、费用率、净利率、TTM 和基础估值。输入缺失、冲突、零/负基期或估值前视时显示明确状态。
2. **可追溯图表与证据**：按指标/口径/币种/报表范围查看曲线，点上带原始 ID、来源、获取时间，下载精确值、公式和 input_ids。估值有市值与财务分母的双侧输入，不用模型算数。
3. **研究假设**：规划可提供可证伪命题；记录支持数据、反例、问题、判断、不确定性与变化历史。自动财务假设覆盖营收/利润和利润/现金流方向。用户投资观点保留，不自动改写复盘。
4. **动态规划**：发现可比财务背离后自动追加毛利率、费用率、业务结构或应收/存货/现金流问题。既有预算不增加，查询规范化去重；自动修订、累计搜索尝试和迭代有上限。
5. **证据关系图和 Critic**：研究对话可选择结论/假设，查看其证据及原始来源；财务派生输入也能追溯。独立逻辑角色检查引用完整性及显式反例是否遗漏，语义未知仍保留 unknown。
6. **持续研究与差异**：更新同一家公司时带入基线和旧假设，再用本轮证据评估；保存不可变版本，比较新增/移除结论、同期间财务修订、失效假设、新记录、同 URL 文本变化及待验证问题，导出 Markdown/JSON。
7. **可配置监控**：自选股有明确开关、1–168 小时间隔、日线/财务模式和 durable 运行记录；交易日期不变也会发现财务源值变化。失败保留旧快照，财务缺失记录 partial，默认关，不自动开付费研究。
8. **兼容的现代技术增量**：按角色或操作显式模型路由，可选 Controller 严格 JSON Schema；原模型/API 默认行为不变。官方文档核查和采纳理由见 V2_TECH_EVALUATION.md。

## 使用入口

重新启动原 Streamlit 服务，使缓存服务对象加载新增模块和 CREATE TABLE IF NOT EXISTS 初始化：

```powershell
.\.venv\Scripts\python.exe -m streamlit run agent_app.py --server.address 127.0.0.1 --server.port 8502
```

- **个股与自选 → 多期财务分析**：导入数据、核对旧快照口径、看图、算估值。
- **个股与自选 → 更新这家公司**：基于上次研究新建版本。
- **研究对话**：查看研究假设、自主计划调整、证据关系、独立检查与版本差异。
- **自选股变化 → 监控频率、来源与运行记录**：保存设置；开关仍由用户显式控制。

旧数据源缺少单位和期间口径时，不能自动“启用”计算。必须核对声明或导入具有明确元数据的源数据。原始数值和原行情快照保留，不用示例代替真实数据。接口失败时，Agent 仍可分析已有独立财务输入。

## 验证证据

| 阶段 | 实际结果 | 报告 |
|---|---|---|
| 起始基线 | 37 项 unittest、16 组入口通过 | artifacts/v2-baseline.json |
| 第一阶段 | 71 项 unittest、18 组入口通过 | artifacts/v2-regression.json |
| 财务增量 | 当时 91 项 unittest、19 组入口通过 | artifacts/v2-financial-regression.json |
| 自主研究增量 | 当时 105 项 unittest、20 组入口通过 | artifacts/v2-autonomy-regression.json |
| 持续研究增量 | 当时 118 项 unittest、21 组入口通过 | artifacts/v2-memory-regression.json |
| 最终开发版本 | **127 项 unittest、21 组入口全部通过** | artifacts/v2-final-regression.json |

最终含金融手算黄金值、累计差分、TTM、PE/PB、跨股票防混、错误指标定义、未来期间、非有限/极端数值、负毛利率和固定舍入等测试；也含实际 Controller/组件的外部 I/O 替身集成，完整 agent_app.py 主页面切到财务工具的 AppTest，假设触发/预算、图谱 SQLite 往返、版本不可变/失效对比、监控频率/失败/源值变化等。

离线 regression runner 阻断网络和项目生产 SQLite 访问，测试数据库只在临时目录。16 个基础合成评测案例仍全部符合预期；一般语义支持全为 unknown，不能将测试命中率写成真实投研准确率。

独立合成演示已运行：**1 个方向假设出现新反例，4 条新财务记录，自动追加原因核查，保存关系图和差异**。所有值为虚构，不调用模型、不写生产数据库、不执行交易。

```powershell
.\.venv\Scripts\python.exe -m scripts.demo_v2
.\.venv\Scripts\python.exe -m scripts.run_offline_tests --output artifacts/v2-final-regression.json
```

输出 `artifacts/v2-demo/capabilities.json` 与 `artifacts/v2-demo/research-diff.md`。编译和 git diff --check 通过；开发中两次新测试路径/辅助参数错误已经修正，未把失败状态标为完成。

## 新旧能力对比

| 能力 | 起始状态 | 当前开发版本 |
|---|---|---|
| 财务 | 源值展示、共同期比较 | 口径约束、确定性多期计算、TTM/估值、图表和输入追溯 |
| 假设 | 用户观点和档案 | 规划命题、结构化假设、支持/反例/历史、旧假设本轮重验 |
| 计划 | 覆盖缺口和用户指令驱动 | 加上两个财务背离触发器、追加任务、预算/迭代/去重约束 |
| 证据 | 摘录、ID、快照 | 加上关系查询、计算 lineage、命名空间和独立反例遗漏提示 |
| 连续研究 | 基线及新增 URL 候选 | 加上不可变财务/假设版本与结构化差异、同 URL 文本变化 |
| 监控 | 固定频率、主要检查日线 | 可配频率/内容、财务源值变化、成功/部分/失败与来源记录 |
| 工程 | 分散脚本与日志 | 显式离线清单、数据集报告、trace、费用未知处理、路由/严格格式契约 |

## 本轮实际文件

新增生产模块：`src/financial_analysis.py`、`src/financial_ui.py`、`src/research_reasoning.py`、`src/reasoning_ui.py`、`src/research_memory.py`。

修改集成：`src/agent.py`、`src/agent_quality.py`、`src/agent_chat.py`、`src/pipeline.py`、`src/workbench.py`、`src/workbench_ui.py`、`src/background.py`、`src/report_links.py`、`src/stock_research.py`、`src/observability.py`、`src/trace_ui.py`、`agent_app.py`、`README.md`。用户已有修改保留。

新增测试/演示：`scripts/test_v2_financial.py`、`scripts/test_v2_autonomy.py`、`scripts/test_v2_memory.py`、`scripts/demo_v2.py`。更新 `scripts/test_v2_quality.py` 和 `scripts/run_offline_tests.py`；新增本阶段文档及 artifacts 中对应报告和演示。

生产库没有运行破坏性迁移或清理。workbench 新增 financial_inputs、monitor_settings、monitor_events，旧表原记录不覆盖；服务启动按需建表。当前 `.git` 权限为只读，且存在用户原有未提交改动；没有创建 commit、打标签或推送，也没有将这些原改动混入提交。

## 费用、风险与未完成项

- 本轮开发未使用真实 OpenAI/Tavily/财务接口，仅只读读取官方技术文档和旧财务字段元数据。无新增付费研究消耗。部署后的实际费用仍需 response usage 和显式模型费率核对；监控只有公开数据请求，没有自动模型调用。
- 反思不额外扩大成功搜索预算；增加任务意味着部分问题可能在预算用尽时仍待验证。role route 不自动选择“最新模型”，配置模型的接口兼容性和实际效果未实测。
- 导入和 metadata 核对是用户声明，不代表原网站、审计报告或事实已经独立认证。财报单位、累计口径和发布日期未知时需要补证据，不生成“真实”替代值。
- 文本方向检查、关系图和 Critic 不是完整语义蕴含证明；当前只对显式财务方向与有限引用模式确定性验证。通用行业假设的自动支持/反例分类仍需更完整的独立 Verifier 和标注评测。
- 新旧结论按文字变化比较，不声称语义变化已经独立确认。财务只比较同期间、同币种、同口径；URL 文本变化不直接称作新公告。
- 监控停服不运行，也没有自动发现全部公告或披露日历。只检查当前适配器可获得的日线和财务源值；依赖 AKShare、东方财富与新浪可用性，真实连通性未在本轮验收。
- 多进程 worker lease、全面锁争用与进程崩溃验收、Reader 私网/重定向/下载边界、浏览器隔离、真实人工标注研究集和云端 CI 尚未完成。没有把整个 v2.0 目标标成生产完成。
- 后续优先验证真实财报元数据映射和真实案例，再增强语义 Verifier；框架整体替换没有足够收益证据，不在本轮强行推进。
