# 逐条结论与证据验证交付记录

日期：2026-10-18（Asia/Shanghai）。基于 `a1c5e45`，本轮范围为上一轮确定的
“结论验证 + 可重复离线评测”。动态搜索策略、通用假设更新、量化回测仍属后续工作。

## 现状与改动

旧验证器可以检查引用存在、摘录来自证据、少量方向和百分比冲突；一般语义支持为 unknown。
报告检查曾把整个引用文档当作该句的支持摘录，容易混入另一家公司或其他语境。
已有 16 条合成评测主要覆盖规则输出，不能代表真实研究准确率。

本轮复用现有 Writer、Agent、pipeline、Critic、ResearchState、证据图谱和报告版本：

1. 以句子作为可审查单元，识别引用编号；保留小数、列表编号、句后引用和多个引用。
   复合句不会自动拆成已验证的原子事实；部分匹配不能证明整句。
2. 每条记录保存原句、章节、稳定内容 ID、引用、原文片段、字符 start/end、来源 URL、
   来源日期/日期可信度和读取状态。偏移是 Python 字符索引，满足 `text[start:end] == excerpt`。
3. 四种状态：`supported`（完整原文陈述匹配）、`contradicted`（直接冲突）、
   `mixed`（来源内或引用间既有匹配又有冲突）、`insufficient_evidence`（未能确定支持）。
   只规范化格式、空白和大小写，不移除预计、否定、主体、财报期或单位；保留问号，
   避免把来源疑问句误当作肯定陈述。
4. 只有读取成功、未回退搜索摘要、未被剔除、非列表页的证据可触发支持/冲突规则。
   方向/百分比冲突还要求其余完整句子模板相同。不同主体、季度、币种、单位、合并范围、
   累计/单季或同比/环比，不被强行认作同一口径。
5. 报告冲突检查由整篇比较改为上述局部规则；聊天回答原有校验契约保留。
   `passed` 明确仅涵盖引用完整性和有限冲突检查，不等于全部结论成立。
   无支持的直接冲突继续阻断正常 Writer/Agent/pipeline 交付；混合证据和未决支持作为 Critic 警告，
   既有 Agent 将有警告的交付标为 partial，保留资料而不伪造结论。
6. 图谱加入 `report_claim` 节点及明确类型的引用关系；不把 `cites` 当作语义支持。
7. 报告快照从本次具体报告和证据重新计算验证，避免复制过期 diagnostics。
   验证随快照一起保存和哈希；不会修改已存版本。对仍有 synthesis 的历史当前报告，下一次显式
   快照可以派生一个带检查的新版本；旧版本保持原样。纯展示不执行回填或写库。
8. Studio 的“过程”面板显示所选版本的逐条验证，点击引用查看该版本原文，下载对应 JSON。
   原生研究界面同样展示记录。未保存验证的旧版本明确显示缺失。

## 验证证据

| 检查 | 实际结果 | 记录 |
| --- | --- | --- |
| 修改前完整基线 | 27/27 套件；197 单元测试 | `artifacts/claim-baseline-2026-10-18.json` |
| 修改后完整回归 | 29/29 套件；216 单元测试 | `artifacts/claim-final-2026-10-18.json` |
| 新增单元测试 | 19/19 | 完整回归中的 `scripts.test_claim_verification` |
| 新增固定材料评测 | 32/32；用例内 false_supports=0 | `artifacts/claim-evaluation.json` |
| 新功能浏览器验收 | 9/9；无页面错误 | `artifacts/claim-browser/browser-checks.json` |
| 原 Studio 浏览器回归 | 21/21；无页面错误 | `artifacts/claim-existing-ui/browser-checks.json` |

新增用例包含直接冲突、跨期间/实体/单位/币种/范围、缺失引用、摘要回退、被剔除证据、
遗漏预计/否定、无依据因果、同一文档自相矛盾、重复报道和版本证据隔离。
32 条分为 16 development、16 heldout；**两组均由实现者编写，不是独立专家盲测**。
该分组为后续维护固定评测集提供入口，不主张独立泛化质量。

基线第一次在受限沙箱运行时，10 个涉及本机通信的套件失败（17/27），原因是 Windows
`socketpair` 被沙箱拒绝；输出终端还出现一次默认 cp1252 编码错误。失败套件记录保存在
`artifacts/claim-baseline-sandbox-2026-10-18.json`。显式 UTF-8 并允许测试所需本机通信后，
同一未修改代码通过 27/27。测试 guard 始终阻止外网和生产 data/ 数据库访问，没有跳过失败测试。

预览首次启动还遇到隔离安装 Streamlit 自动启用 developmentMode、拒绝指定端口；显式关闭
developmentMode 后启动成功。浏览器检查随后通过，没有将连接失败算作验收成功。

## 文件记录

新增：

- `src/claim_verification.py`：句子提取、来源匹配、保守冲突和可追溯记录。
- `evals/claim_cases.json`：冻结的合成材料和预期标签。
- `scripts/evaluate_claims.py`：可重复执行的评测，保存数据集 SHA256、分组和逐例结果。
- `scripts/test_claim_verification.py`：规则、历史隔离、SQLite、图谱和完整性回归。
- `scripts/preview_claims.py`：仅临时虚构数据库的验收入口。
- `scripts/check_claim_browser.py`：版本、引用、导出、转义与移动端验收。
- 本文及上述 `artifacts/claim-*` 验收记录；新界面的桌面/手机截图均为虚构数据。

修改：

- `src/verifier.py`：接入逐句检查，修正跨主体整篇冲突误判。
- `src/research_reasoning.py`：Critic 警告、摘要和图谱关系。
- `src/report_links.py`：验证随报告/证据版本保存。
- `src/reasoning_ui.py`、`src/studio_component/studio.js`：原生界面与 Studio 展示/下载。
- `scripts/run_offline_tests.py`：将新测试和评测纳入现有 guard。
- `.github/workflows/offline-regression.yml`：上传新评测产物。
- `README.md`、`docs/V2_ARCHITECTURE.md`：入口、能力与限制。
- `artifacts/agent-evaluation.json`：本轮重跑原 16 条评测，预期结果保持不变。

## 运行与兼容

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
.\.venv\Scripts\python.exe -m scripts.evaluate_claims
.\.venv\Scripts\python.exe -m scripts.run_offline_tests --output artifacts/claim-final-2026-10-18.json
.\.venv\Scripts\python.exe -m streamlit run scripts/preview_claims.py --global.developmentMode false --server.address 127.0.0.1 --server.port 8522 --browser.gatherUsageStats false
```

本地验收使用与之前 CI 相同的隔离 Streamlit 1.65.0（`PYTHONPATH=.venv/ci-streamlit165`）。
浏览器开发依赖 Playwright 和本地 Chromium，未加入生产依赖。预览仅临时虚构数据，后台提交被禁用；
刻意保存一份冲突报告来检查失败状态的展示，**不表示正常研究流程会允许该报告通过**。

新增验证是纯本地规则，增量模型/搜索 API 费用为 0；完整真实研究的费用仍由已有模型与工具调用决定。
无新增第三方依赖、无数据库 schema 变更、未删除历史数据或覆盖密钥。未停止旧服务。
已运行的生产进程可能缓存旧 Python 模块，需要新的更新后服务进程才能加载本轮后端代码。
本轮预览地址 `http://127.0.0.1:8522` 是本机入口，不是公网部署。

## 尚未完成和下一轮

- 原文匹配证明归属，不证明来源真实、时效、独立佐证或一般语义蕴含。
- 改写、因果和复杂表格常会保守地成为证据不足；不应为提高匹配率而强迫报告机械照抄。
- 仅检查已引用文档；未引用的关键反证仍可能遗漏，没有宣称穷尽性检测。
- 句子切分对缩写、复杂 Markdown 表格、跨句上下文的支持有限；不引入未经评测的自动推断。
- 狭窄模板冲突规则会漏掉同义改写、金额换算等冲突；财务计算继续使用原结构化 Decimal 工具。
- 尚未增加独立模型语义审阅、真实材料专家标签或端到端自主搜索评测。
- 下一轮优先加入有标注的真实冻结材料，再评测语义审阅与证据驱动的搜索/停止策略。
  货币硬预算、通用假设推理、量化历史检验继续单独实施，当前不标为完成。

## GitHub 与云端验收

- 主体实现：`acc278c`，云端 [39051212402](https://github.com/qche77-cloud/ResearchPilot/actions/runs/39051212402) 通过。
- 最终代码：`fc577f22581e4ea951df7c0541cbbcf791498949`，保留问号，加入来源疑问句不能支持肯定句的回归测试。
- 最终 [CI 39051470907](https://github.com/qche77-cloud/ResearchPilot/actions/runs/39051470907) **success**。
  原始云端产物已下载至 `artifacts/claim-ci-fc577f2/`，确认 **29/29 套件、216 单元测试、32/32 新用例**；
  结构化完成记录为 `artifacts/claim-cloud-fc577f2.json`。
- 本地数据集文件 SHA256 为 `1647e4ab507912e448d8447af3adbf198daf704a7afdf06d873549f0d2de52cd`；
  云端为 `ae52ab1053c0f21390d9ecbbf219d19f5a5878491ef57524e2185ee238bd8aa9`。
  当前评测器哈希的是原始文件字节。实际核对将 LF 转为 CRLF 后恰好得到云端哈希，
  且解析后的 JSON 完全相同；差异来自 Git 的 Windows 换行转换，不是测试材料变化。
- Actions 有 Node 20 action 被运行器强制使用 Node 24 的弃用提示，但任务成功。
  本轮未顺带升级 Actions 版本；后续可单独验证升级。
- 已核实并重启本轮端口 8522 的隔离预览以加载最终代码，没有停止既有生产进程。
- 最后补录仅更新文档和验收产物，使用 `[skip ci]` 提交，避免为记录 CI 状态无限触发下一轮 CI。
