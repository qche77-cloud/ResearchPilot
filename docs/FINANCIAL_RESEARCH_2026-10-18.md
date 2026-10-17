# 财报异常发现、利润归因与观点复盘

日期：2026-10-18，Asia/Shanghai。基于 `51c7a57`。本轮按已确定的三个方向实现，
不把事件研究、因子回测、同行比较或情景预测标记为完成。

## 实现与新旧对比

| 能力 | 原有实现 | 本轮实现 |
| --- | --- | --- |
| 财务线索 | 质量体检与两类财务反思 | 七类可追溯异常规则、明确阈值与研究问题 |
| 利润分析 | 同比、环比、利润率 | 同口径净利润变化桥、可点击瀑布图及未解释差额 |
| 观点记录 | 人工观点、状态、复盘历史、可确认的模型建议 | 数值判据、目标期与复盘日；不可变版本与固定财务输入检查 |
| 研究证据 | 财务原值与基础计算 | 追加规则观察、分解结果及其原始输入，供现有 Agent 引用 |
| 数据覆盖 | 原财务指标 | 增加存货、应收账款、费用化研发费用、扣非归母净利润的规范化输入 |

### 七类财务线索

所有规则使用同一股票、币种、报表范围和指定财报期；流量指标选择累计或单季，
期末余额按同一季度末同比比较。默认比较上年同期，不把上季度累计与本季度累计直接比较。

1. 营业收入增加、利润减少；优先使用存在的归母利润，观察值明确实际使用的利润指标。
2. 同期正净利润大于经营现金流，提示检查营运资金。
3. 存货余额同比增速高于收入同比增速 **超过 10 个百分点**。
4. 应收账款余额同比增速高于收入同比增速 **超过 10 个百分点**。
5. 毛利率较上年同期下降 **至少 2 个百分点**。
6. 收入增加但费用化研发费用减少；不能由此推断总研发投入减少。
7. 正归母利润与扣非归母利润的差额占归母利润 **至少 50%**；不自动归因为资产处置。

阈值在输出中可检查，Python 接口支持显式覆盖，界面本轮展示默认阈值。
状态为 triggered / clear / unavailable。“未触发”只针对该条规则；
缺失、冲突、未知口径、不适合的分母或不安全金额不被当作正常。
库存与收入的比较是期末余额/期间流量的增速线索，不是周转率或坏账判断。

### 利润变化桥

必须有同口径两期营业收入 R、营业成本 C、净利润 P；不使用营业总成本替代 C，
也不把归母利润与合并净利润混用。基期营业收入须为正。

- 收入贡献 = `(R1-R0) × (R0-C0)/R0`，按原币单位保留 0.01，ROUND_HALF_EVEN。
- 毛利率贡献 = `Δ(R-C) - 收入贡献`，即在此分解顺序下的毛利率变化贡献。
- 两期期间费用 E 齐全时，费用贡献 = `-(E1-E0)`。
- 未解释差额 = `ΔP - 以上已计算贡献之和`。
- 基期净利润 + 各项贡献 + 未解释差额 = 本期净利润。

Decimal 精度 40。超出安全范围或无法勾稽时不画分解图。缺少期间费用时，
费用项不补零、不作为已解释贡献，未解释差额明确注明含未拆费用。
税费、减值、投资收益等未结构化拆解的项目保留在差额，不能将差额视为某一种原因。
这是金额恒等分解，不是独立识别的因果效应；分解顺序会影响贡献解释。

瀑布图浮点只用于坐标和显示，导出金额与 input_ids 保留 Python 精确结果。
点击图形或规则可查看原值、原始单位、财报期、披露日期、可用日期及来源 URL。

### 可计算的观点复盘

判据包含指标、原值/同比、比较符、阈值、目标财报期、币种、累计/单季/期末口径与报表范围，
另有明确复盘日。界面创建一项主要财务判据；后端支持 1–6 项，全部有数据且满足才算满足。
已有多项设置不会被单项表单静默覆盖。

用户显式执行检查后，结果分别为“未到复盘日”“等待可比披露数据”“财务判据满足”
或“财务判据未满足”。不等同于完整投资论点成立/被推翻，也不看股价涨跌替代经营判断。
未到复盘日前保留过程观察；目标披露不足时等待，不用其他期间凑数。

每次判据保存追加新版本并记录当时观点、基线数据及日期；事务内比较 expected_revision。
检查固定选中的 financial_inputs 版本和截止日，保存实际数值及原始输入。
同一判据版本/数据版本/日期重复执行返回同一记录。后续数据修订改变同一判据观察时，
保留旧结果并显示已观察数值的变化。结果与人工 review/status 独立。
判据实际创建时间不可回填为过去；事后设定的判据不能包装为事前预测。

本轮没有新增定时自动检查或通知任务，用户导入/选择财报后显式运行。

## 自动化验收

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 修改前离线基线 | 29/29 套件，216 单元测试 | `artifacts/research-tools-baseline-2026-10-18.json` |
| 首轮集成 | 30/30 套件，232 单元测试 | `artifacts/research-tools-integration-2026-10-18.json` |
| 最终完整回归 | 31/31 套件，236 单元测试 | `artifacts/research-tools-final-2026-10-18.json` |
| 新增单元测试 | 20/20 | 完整回归中 `scripts.test_research_tools` |
| 固定财务/判据评测 | 12/12 | `artifacts/research-tools-evaluation.json` |
| 新工具浏览器 | 11/11，无页面错误 | `artifacts/research-tools-browser/browser-checks.json` |
| 原驾驶舱浏览器回归 | 14/14，无页面错误 | `artifacts/research-tools-cockpit-regression/browser-checks.json` |
| 原 Studio 浏览器回归 | 21/21，无页面错误 | `artifacts/research-tools-studio-regression/browser-checks.json` |

合计 46 项浏览器检查，包括 390/1024/1440 宽度、图表键盘访问、下载金额勾稽、
判据草稿、财务修订、旧记录保留、复盘日期、人工状态隔离及旧服务数据兼容。
数值单元测试覆盖未知币种/范围/日期、冲突重复、极小分母、大金额、缺少费用、
拒绝归母利润替代、同一数据集多币种、旧数据库加表和过期版本写入拒绝。

12 个评测场景由实现者编写的固定虚构材料构成，保存完整输入、预期和实际结果。
数据集哈希使用规范化 JSON，避免 LF/CRLF 造成文件哈希差异。
它们证明确定性规则符合预期，不代表真实公司研究准确率或投资收益。

开发中实际修正：浏览器发现后台响应重绘会清空未保存判据，增加按公司/观点/版本隔离的
会话草稿；异步文件导入验收改为等待数据版本确认；测试夹具 SQLite 连接未关闭造成的
Windows 临时文件清理错误已修复。截图复查修正图标 SVG 样式影响瀑布图文字描边的问题。
复查还修复旧 ratio 输出缺少币种/范围，以及多币种成本集合错误阻止有效比率计算的问题。
未将这些失败尝试计为通过。

## 修改文件

新增：`src/financial_diagnostics.py`、`src/thesis_tracking.py`、
`src/studio_component/research_tools.js`、`src/studio_component/research_tools.css`、
`scripts/test_research_tools.py`、`scripts/evaluate_research_tools.py`、
`scripts/preview_research_tools.py`、`scripts/check_research_tools_browser.py`、本文及验收产物。

修改：`src/financial_analysis.py`（指标、校验、比率匹配/元数据及 Agent 结构化证据），
`src/workbench.py`（两张增量表与事务版本控制），`src/studio_company.py`、
`src/studio_bridge.py`（只读展示与受校验事件），`src/studio_component/cockpit.js`、
`src/studio_component/index.html`，以及离线测试清单、CI 产物清单、README 和架构文档。
原 Agent 与 pipeline 无框架迁移，人工观点及复盘流程保留。

## 使用与运行

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m scripts.run_offline_tests --output artifacts/research-tools-final-2026-10-18.json
.\.venv\Scripts\python.exe -m scripts.evaluate_research_tools
.\.venv\Scripts\python.exe -m streamlit run scripts/preview_research_tools.py --global.developmentMode false --server.address 127.0.0.1 --server.port 8524 --browser.gatherUsageStats false
```

本地回归使用隔离 Streamlit 1.65.0：`PYTHONPATH=.venv/ci-streamlit165`。
浏览器测试用开发依赖 Playwright/本地 Chromium，未增加生产依赖。
预览 `http://127.0.0.1:8524` 是临时虚构数据库：自选档案 → 公司 A → 财报侦察/投资复盘。
模型研究和真实数据抓取均被禁止，界面可写的内容只进入临时库。
已有生产服务未被停止，新后端需使用更新后的进程；旧数据包/缓存存储对象有兼容提示。

正式财务输入沿用现有 JSON 导入。新增指标使用 `inventory`、`accounts_receivable`、
`rd_expense`、`attributable_profit_excluding_nonrecurring`；前两项 basis 为 instant，
其余为累计或单季。均需明确单位、币种、范围、财报期、来源、抓取和披露时间。
现有在线数据源不保证提供这些字段；缺少时提示不可判定，没有新增万能采集器。

## 成本、兼容和限制

- 工具计算、界面和本轮验收不调用付费模型/搜索 API；没有覆盖密钥、删除用户数据或执行交易。
- 数据库只 CREATE TABLE IF NOT EXISTS 新增 thesis_tests/thesis_test_runs，无删除、列替换或旧表迁移。
- Agent 引用新增 JSON 证据会增加部分上下文，真实模型费用依已有 usage 轨迹计算，不能宣称整项研究免费。
- 尚未用真实外部 API 或真实公司财报进行财务专业人员验收；来源真实性仍需核对。
- 日期级 available_at 与版本化输入不等于完整历史时点数据库，不能直接宣称无前视回测。
- 库存、应收和研发等复杂口径需要原始附注；规则不代替审计，未拆分业务结构、税费或单项减值。
- 大量财务记录和多观点历史会增加当前本地归一化与展示成本，尚未做大规模性能承诺。
- 本轮未提供全自动观点语义裁决、定时判据调度、同行数据库、事件研究、因子收益回测或预测收益。

GitHub 提交和云端原始验收产物在实际完成后补录，云端结果不以本地通过替代。
