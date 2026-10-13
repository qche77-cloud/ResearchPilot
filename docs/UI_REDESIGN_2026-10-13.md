# 2026-10-13：研究工作台界面重构与验收

本阶段按用户要求重构现有 ResearchPilot 界面，继续使用 Streamlit、既有研究服务与 SQLite。没有替换研究框架，没有迁移或删除用户数据，也没有为了界面测试发起真实付费研究。

## 实际交付

- **统一视觉**：深青色侧栏、暖白底色、青绿色操作重点，统一字体、间距、按钮、表单、数据卡片和空状态；移除原来两层互相覆盖的主题样式，所有视觉资源保存在本地。
- **首页**：研究流程说明、三个可点击研究方向、集中的问题输入区、当前搜索预算提示；研究方向只填草稿，不自动消耗 API 预算。
- **研究页**：拆分为研究对话、研究报告、证据与来源、假设与验证。状态、搜索预算和来源数单独展示；研究控制仍调用既有后台队列。工具用量和计划缺口移入检查视图，报告可直接阅读和下载。
- **个股页**：拆分行情概览、财务分析、研究档案和投资复盘。行情与财务更新、加入自选和研究个股保持可用；档案和观点继续保存在原存储结构中。
- **财务页**：图表优先，精确值、数据质量、计算结果和公式追溯按需展开；指标与口径筛选并排展示，保留来源 ID、原值和证据下载，不改变计算逻辑。
- **交互兼容**：首页和追问草稿在当前会话切页时保留；恢复、暂停、预算和追问继续由 Runner 执行。历史报告及其对应版本入口保留。
- **适配与可访问性**：窄屏布局、可折叠侧栏、键盘焦点样式和减少动画设置；保留原生输入与按钮，不引入远程字体或图片依赖。

## 修改文件

| 文件 | 用途 |
|---|---|
| `agent_app.py` | 导航、首页、问题输入、研究视图接入 |
| `src/ui_theme.py`、`src/ui_polish.css` | 统一视觉与展示组件 |
| `.streamlit/config.toml` | 与 CSS 一致的原生控件色彩 |
| `src/conversation_ui.py`（新增） | 对话、报告、来源和验证分区 |
| `src/workbench_ui.py` | 个股四个视图与操作布局 |
| `src/financial_ui.py` | 图表优先布局与可展开追溯详情 |
| `requirements.txt` | Streamlit 最低版本提升至 1.41，支持本阶段使用的布局 API |
| `scripts/test_ui_workspace.py`（新增） | 草稿、导航、报告与后台命令回归 |
| `scripts/run_offline_tests.py` | 将新增 UI 测试纳入显式离线清单 |
| `scripts/preview_ui.py`（新增） | 临时数据库、虚构数据和禁用网络工具的独立预览 |
| `scripts/check_ui_browser.py`（新增） | 可重复的浏览器界面验收与截图 |
| `artifacts/ui-regression-2026-10-13.json`、`artifacts/ui-preview/` | 回归、浏览器结果和虚构数据截图 |
| `README.md`、本报告 | 使用入口、测试方法与边界说明 |

本阶段不修改研究计算、检索预算、模型决策和数据库表设计。回归重跑更新了合成评测报告的运行时间，未更改案例定义。

## 验证证据

| 检查 | 结果 |
|---|---|
| 改造前最近基线 | 21/21 套入口通过，127 个单元测试；见 [启动前报告](../artifacts/v2-launch-regression.json) |
| 改造后完整离线回归 | **22/22 套入口通过、132 个单元测试通过、0 个失败套件**；见 [本轮回归报告](../artifacts/ui-regression-2026-10-13.json) |
| 新增 UI 测试 | 5/5 通过：首页草稿切页、研究方向不自动发起任务、历史报告分区、追问草稿与一次入队、恢复与预算命令 |
| 桌面浏览器 | 1440 px：草稿往返、个股/财务/报告/证据/验证视图通过 |
| 平板与手机 | 1024 / 390 px：首页无整页横向溢出；390 px 个股导航与财务图表无整页横向溢出 |
| 浏览器异常 | 5 组检查通过，`page_errors` 为空，无 Streamlit 页面异常；见 [浏览器记录](../artifacts/ui-preview/browser-checks.json) |
| 正式工作台 | 新端口 `http://127.0.0.1:8504` 返回 HTTP 200，真实工作台首页与个股页加载新版样式，无页面异常；仅浏览，未提交研究或刷新行情 |

浏览器测试使用合成行情/财务与临时数据库；虚构标识显示在页面中，不将截图值声称为真实行情或真实 API 调用结果。截图为浏览器视口，可滚动页面未被当作单张完整文档导出。

开发中曾遇到浏览器脚本等待隐藏图表的超时，以及首次截图未等待控件完全加载。已按可见 SVG 图表和脚本完成状态修正定位，并重新执行验收；上述失败没有记为通过。

截图：

- [新版首页（桌面）](../artifacts/ui-preview/home-desktop.png)
- [研究对话（桌面）](../artifacts/ui-preview/conversation-desktop.png)
- [财务图表（桌面）](../artifacts/ui-preview/finance-desktop.png)
- [首页（手机）](../artifacts/ui-preview/home-mobile.png)
- [财务图表（手机）](../artifacts/ui-preview/finance-mobile.png)

## 服务加载与安全处理记录

原 8502 服务缓存了升级前的 Python 界面模块，出现 `brand` 导入错误，需要重新加载。只读检查发现 3 条历史 `running` 任务，更新时间分别为 2026-09-13 与 2026-07-22；仅凭旧时间不能确认原进程里没有任务。

自动审批拒绝停止并重启原 8502 服务，理由是 `running` 状态任务可能受影响且没有明确授权中断。未执行停止，也未通过其他命令绕过该拒绝。改为在 **8504** 启动新版工作台，保留原进程；启动前确认启用监控数量为 0，新服务启动不会自动恢复历史任务。既有状态和 SQLite 数据保留，未把旧任务标成完成或失败。

8503 是本阶段独立虚构数据预览，使用临时数据库；与正式工作台分开。任何需要停止原 8502 服务或中断其历史任务的操作仍需用户明确授权。

## 复现与运行

正式工作台（当前新增端口）：

```powershell
.\.venv\Scripts\python.exe -m streamlit run agent_app.py --server.address 127.0.0.1 --server.port 8504
.\.venv\Scripts\python.exe -m scripts.run_offline_tests --output artifacts/ui-regression-2026-10-13.json
```

独立浏览器验收：

```powershell
# Playwright 是可选开发依赖，没有加入应用运行 requirements。
.\.venv\Scripts\python.exe -m pip install playwright
$env:PLAYWRIGHT_BROWSERS_PATH = 'G:\ResearchPilot\.venv\playwright-browsers'
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m streamlit run scripts/preview_ui.py --server.address 127.0.0.1 --server.port 8503
# 另开终端，使用同一 PLAYWRIGHT_BROWSERS_PATH：
.\.venv\Scripts\python.exe -m scripts.check_ui_browser
```

## 未完成项与维护边界

- 当前为 Streamlit 界面重构，未改为独立前后端。Tabs 内组件仍按 Streamlit 默认方式执行，不代表已经实现每个视图的按需后端加载。
- 已验证 Chromium 和上述尺寸；Safari、Firefox、屏幕阅读器及所有移动机型未验收，不能声称全面兼容。
- 部分样式依赖 Streamlit `data-testid` / BaseWeb 属性，库升级后应重跑截图验收；`use_container_width` 暂为兼容最低版本保留，当前版本会给出弃用提示。
- 草稿只保证当前浏览器会话切页保留，刷新或关闭浏览器不保证保留。旧 8502 进程的缓存问题没有通过停止进程处理，新入口以 8504 为准。
- 真实模型、检索和财务 API 的连通性及语义质量仍沿用此前未验收边界，本次 UI 重构没有扩大该结论。
- 本地链接仅在本机访问；没有云端托管、自动交易或新增付费数据源。
