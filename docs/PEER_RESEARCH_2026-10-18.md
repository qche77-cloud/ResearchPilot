# 财报导入、同业比较与研究线索 · 2026-10-18

## 交付功能

公司研究新增“财报导入”和“同业比较”两个页面。复用原财务计算、不可变输入版本、SQLite 和研究执行入口，没有更换 Agent 框架。

1. **PDF 候选提取与确认**：上传本地文字 PDF，填写公司、财报期和公开来源/披露日期。按支持的指标行提取候选金额，保存原始页码、摘录、文件 SHA-256；明确的年报两年表头可以生成上年列候选。用户逐项勾选，确认单位、币种、范围及累计/单季口径后保存。候选不是未经确认的真实财务数据。
2. **原文件与财务版本同时保存**：在同一事务中保存原 PDF 和新财务版本，保留原版本及其他期间。并发期间最新版本发生变化会拒绝旧预览提交。原 PDF 可下载，图表数据点可查看 PDF 页码及文件标识。
3. **可保存的比较组**：用户选择 2–50 家可比公司，比较明确财报期、截止日期、币种、报表范围和累计/单季口径。不将不同财报期混排，缺失不补零。
4. **确定性横向比较**：复用 Python 财务指标，计算营收同比、归母利润同比、毛利率、净利率及现金兑现率的样本中位数与差值；显示每项有效样本数，保存结果和各公司财务版本，刷新后可重新打开并导出。
5. **研究线索**：收入增长但归母利润未增长、现金低于同范围利润，以及至少 3 家有效样本时毛利率低于组中位数至少 5 个百分点，生成明确待查问题。点击研究会携带当次固定财务版本、比较范围、计算依据和反证要求，沿用现有 2–16 次搜索上限。不会仅凭异常自动断言原因。

## 数据与解析边界

- 只新增 `financial_documents`、`peer_groups`、`peer_runs` 三张表，无删除或破坏性迁移。
- PDF 使用已有 pypdf，在独立子进程解析；上限 12 MB、400 页、180 万字符、45 秒。不执行 PDF 脚本、不请求文件中的链接；加密、扫描件、无有效文本、超时会报错。
- 采用保守的指标行和数值列规则，不是通用财报理解/OCR 引擎；跨页表、复杂列、多种单位或特殊格式可能需要 JSON 导入。
- 首列报告期、公司归属和范围必须由用户核对。无法确认表头时不自动生成上年列。明显的原文单位/母公司标题冲突会阻止保存；同指标同期间只能选择一条。
- 同一财报里的历史对照值以该份财报的披露日期作为可用日期，不冒充原年份当时已知数据。
- 比较使用所选输入版本及其日期字段，不是完整历史时点数据库；后续重述、行业成员历史和收益回测没有在本轮实现。
- 公司名单由用户选择，不自动认定行业或全行业分位；银行等不同会计模式不应直接套用同一比较组。
- 本轮没有自动抓取公告、全市场行业库、10–20 家预装真实数据池、分部业务提取、行情回测或自动交易。公开报告仅用作隔离验收，没有写入用户自选或生产财务数据。
- 模型研究本身仍可能产生模型与搜索费用；导入和比较不调用模型。比较结构化证据会增加研究上下文，按既有轨迹记录计量。

## 真实来源与验收

已从公开披露平台下载下列原文件，渲染对应页面并逐项核对数值。原 PDF 保留在本地忽略的 `tmp/pdfs/`；仓库仅保存必要表格摘录、黄金数值和文件哈希。

| 公司 | 来源 | PDF 物理页 | SHA-256 |
| --- | --- | --- | --- |
| 海天味业 603288 | [2024 年年报，2025-04-03](https://static.cninfo.com.cn/finalpage/2025-04-03/1222994233.PDF) | 7 / 208 | `5a97b13534438f5e85249752ef492fbd9e23af73e67845e47bad1ab7d92e20ee` |
| 千禾味业 603027 | [2024 年年报，2025-04-16](https://static.cninfo.com.cn/finalpage/2025-04-16/1223103749.PDF) | 5 / 197 | `bc50e75d62cf8fc585828027763c78220768050e0b938554da4b59ffed2215e3` |
| 中炬高新 600872 | [2024 年年报，2025-04-09](https://static.cninfo.com.cn/finalpage/2025-04-09/1223033026.PDF) | 5 / 193 | `0667d38e8f854628827ca3c33eeb4d3e4fbcf37f2eec5fb88b2e8a3ba1557306` |

- 开发基线：**31/31 套件、236 单元测试**。
- 最终离线回归：**33/33 套件、252 单元测试**；新增 16 项测试，包括原文金额、括号负数、单位/范围冲突、损坏/加密/扫描文件、解析超时、缺失/未来数据、精确中位数、样本门槛、事务、旧版本保留、固定数据研究入口。
- 原 PDF 全文件解析与哈希核验：**3 份报告、30/30 金额、6/6 披露同比值**；仅是三个历史样本的验收结果，不能外推一般提取准确率。
- 新增浏览器 **7/7**；最终后端原公司流程 **14/14**、Studio **21/21**，共 **42 项**。页面没有 JavaScript 异常，未调用付费 API。
- 浏览器导入使用明确标识的虚构解析夹具和临时数据库，验证上传、勾选、确认、字节一致下载、比较导出、刷新重开及手机/平板布局。真实 PDF 解析由独立的全文件验收覆盖，不把夹具输出描述为真实解析。
- JavaScript 语法检查与 `git diff --check` 通过。

实际失败与修正：Exa 后续检索遇到免费限额，改用可用搜索读取公开披露链接；Windows 输出编码改为 UTF-8。浏览器最初因 Streamlit 分片回调超出 mock 作用域失败，已用仅限隔离预览的显式解析器注入修复。验收中的第三家公司故意无财务数据，最初绑定数量断言有误，已核对为 3 行/2 份输入并增加缺失原因断言。另一次原流程测试误用扩展财务夹具，图表数量不符；切换原始兼容夹具后通过。截图复查增加实际 iframe 宽度及 CSS 过渡完成检查。这些失败尝试未计入通过数量。

## 文件与执行

新增核心：`src/financial_import.py`、`src/financial_import_worker.py`、`src/peer_research.py`、`src/peer_workspace.py`、`src/studio_component/peer_workspace.js`、`peer_workspace.css`。

集成修改：`src/workbench.py`、`src/studio_company.py`、`src/studio_bridge.py`、`src/studio_component/cockpit.js`、`studio.js`、`index.html`。沿用旧页面和旧持久化数据。

新增验收：`evals/financial_reports_real.json`、`scripts/test_peer_research.py`、`scripts/evaluate_peer_research.py`、`scripts/preview_peer_research.py`、`scripts/check_peer_browser.py`。更新离线清单、CI 产物清单、README、架构文档和 `.gitignore`。未新增生产依赖。

```powershell
$env:PYTHONPATH='G:\ResearchPilot\.venv\ci-streamlit165'
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m scripts.run_offline_tests
.\.venv\Scripts\python.exe -m scripts.evaluate_peer_research
# 原文件须来自上面的公开链接，并与固定 SHA-256 一致：
.\.venv\Scripts\python.exe -m scripts.evaluate_peer_research --pdf-dir tmp/pdfs
.\.venv\Scripts\python.exe -m scripts.check_peer_browser --url http://127.0.0.1:8527
```

证据：[基线](../artifacts/peer-research-baseline-2026-10-18.json)、[最终回归](../artifacts/peer-research-final-2026-10-18.json)、[原始 PDF](../artifacts/peer-research-original-pdfs.json)、[离线摘录评测](../artifacts/peer-research-evaluation.json)、[新页面浏览器](../artifacts/peer-research-browser/browser-checks.json)、[公司流程](../artifacts/peer-final-company-browser/browser-checks.json)、[Studio](../artifacts/peer-final-studio-browser/browser-checks.json)。

截图全部为临时虚构数据：[导入](../artifacts/peer-research-browser/import-desktop.png)、[比较](../artifacts/peer-research-browser/peers-desktop.png)、[手机比较](../artifacts/peer-research-browser/peers-mobile.png)。

正式本地入口为 `http://127.0.0.1:8528`，保留原来的 8526 等服务。已只读验证正式首页与新前端模块加载、无页面异常，`/_stcore/health` 返回 200/ok，记录见 `artifacts/peer-research-live-2026-10-18.json`。该检查没有创建研究、截图真实档案或调用模型，不等于真实 API 全流程验收。

8527 是隔离预览，仅用于虚构输入测试，不是正式财务输入入口。

## GitHub 验收记录

- 功能提交 `6cadbe7056602687147245c2e19ec61c75edb13c` 已推送 main。
- [GitHub CI 39137013212](https://github.com/qche77-cloud/ResearchPilot/actions/runs/39137013212) 实际 **success**。已通过官方 API 核对完整提交 SHA、作业与步骤结论，记录为 `artifacts/peer-research-cloud-6cadbe7.json`。
- 本地 **33/33、252 单元测试、30/30 金额和 6/6 同比**有原始 JSON 记录。云端原始压缩产物下载在三次尝试中均遇到 Azure 下载域名的 TLS EOF；未绕过证书校验，没有将未下载的云端文件或未提取到的日志计数标记为已核实。可从上面的 Actions 页面查看成功执行与已上传产物。
- Actions 仍提示 Node 20 被运行器强制改用 Node 24，未影响本次通过。本轮仅增加新评测产物路径，没有另做工作流迁移。
- 最终验收元数据通过 `[skip ci]` 文档提交补录，不把该文档提交描述成另一次代码 CI。
