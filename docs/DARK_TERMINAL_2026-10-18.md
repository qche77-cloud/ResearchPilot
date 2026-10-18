# 深色研究终端界面 · 2026-10-18

按用户选择的“深色金融终端：紧凑、有质感、数据感更强”调整现有 Studio。

## 实际变化

- **首页重新组织**：研究记录、自选公司和财务筛选成为可点击入口；记录数来自真实本地元数据。左侧输入研究问题，右侧继续最近研究，下方为研究切入点及标题/日期/状态分层的历史列表。没有模拟行情或装饰性收益数字。
- **统一导航与操作**：收紧侧栏和顶部高度，调整任务行间距，增加可用的全局研究搜索按钮，保留键盘快捷键、悬停提示、页面过渡及减少动态效果设置。
- **财务信息层级**：版本、记录数和截止日整合为分隔式概览；图表筛选区独立，财务图表网格、坐标、折线及利润变化图适配深色背景；关键指标使用等宽数字，负数使用独立颜色。没有改变数值、来源或计算规则。
- **表单与表格**：统一输入控件和操作按钮尺寸，PDF/同业表单采用明确的网格排列；手机上转为单列，宽表格在自己的容器内横向滚动。
- **报告阅读**：正文保持 15px，调整标题、目录、引用及辅助说明层级；右侧对话/证据区使用独立的表面颜色，保留版本范围及原始证据查看。
- **状态显示修正**：历史列表的状态圆点重新使用原始状态 CSS 类，避免把展示翻译当作 class；没有改写数据库状态。

## 范围和兼容

改动仅限静态前端及浏览器验收脚本，无新生产依赖、数据库迁移、付费 API 调用或交易。
保留既有事件名、元素编号、数据字段和研究执行逻辑；历史报告及用户观点原文不变。
原生高级“数据工具”保留原布局和入口，本轮重做的是 Studio 的首页、公司研究、财务检查、导入/比较、报告与证据界面。

`design.css` 提供排版、间距和组件结构，`terminal.css` 覆盖为用户选定的深色风格及紧凑密度。
脚本缓存版本已更新，现有正式 Studio 刷新即可加载，无需停止后台服务。

## 修改文件

- 新增 `src/studio_component/design.css`、`terminal.css`。
- 修改 `src/studio_component/index.html`、`studio.js`、`cockpit.js`。
- 新增 `scripts/check_visual_redesign.py`；更新 README、本文和隔离验收产物。

## 验证

- 开始前：原 Studio 桥接 **14 项单元测试**通过；原浏览器 **21 项**通过，截图在 `artifacts/visual-redesign-before/`。
- 完整离线回归：**33/33 套件、252 项单元测试**通过，禁止网络及生产数据库访问。
- 最终深色界面：**51 项浏览器检查通过**。包括视觉/阅读 9、Studio 21、公司研究 14、PDF/同业 7；页面无 JavaScript 错误。
- 1440、1024、390 三种宽度：核查首页、财务图表、同业表单、研究报告及页面宽度，复查最终截图。
- 新视觉验收覆盖：原生深色控件、真实记录计数、最近研究打开入口、全局搜索、模板填入草稿、导航及报告 15px 正文。
- 首页说明文字对比度为 **8.85:1**，三种宽度字体均为 **13px**。只证明这一检查项，不宣称全界面通过无障碍认证。
- `node --check` 与 `git diff --check` 通过。外观好坏仍需用户判断，自动验收不代表审美认可。

截图复查修正了最近研究标题与日期挤在同一行的问题。最终截图与指标均来自用户选定的深色版本，不将中间预览当作最终验收。

证据：[离线回归](../artifacts/visual-redesign-regression-2026-10-18.json)、[视觉与可读性](../artifacts/visual-redesign/browser-checks.json)、[Studio](../artifacts/visual-redesign-studio/browser-checks.json)、[公司研究](../artifacts/visual-redesign-company/browser-checks.json)、[PDF/同业](../artifacts/visual-redesign-peers/browser-checks.json)。

截图全部为隔离虚构数据：[首页](../artifacts/visual-redesign/home-desktop.png)、[财务页](../artifacts/visual-redesign/company-desktop.png)、[报告](../artifacts/visual-redesign/report-desktop.png)、[手机首页](../artifacts/visual-redesign/home-mobile.png)。

正式入口继续使用 `http://127.0.0.1:8528/`。已只读确认该入口加载深色主题及新版首页，页面无异常，没有创建研究或截图真实档案，记录为 `artifacts/visual-redesign-live-2026-10-18.json`。8530 临时预览在验收后已按脚本与父进程核对身份并停止，原正式服务与其他既有服务未停止。

## GitHub 验收

- 功能提交 `6d84926007231da248e416a4270f73b56ef635a2` 已推送 main。
- [GitHub CI 39139705810](https://github.com/qche77-cloud/ResearchPilot/actions/runs/39139705810) 实际 **success**，已核对完整 SHA、作业与步骤状态；元数据存档 `artifacts/terminal-cloud-6d84926.json`。
- 原始 CI 压缩产物下载仍遇到网络错误。本地 33/33 套件、252 单元测试与 51 浏览器检查有上述原始报告；未把未下载的云端报告计数描述为已核实，也未绕过证书检查。
- Actions 的 Node 20 弃用提示仍存在，本次回归成功。本轮没有修改 CI 工作流或运行依赖。
- 验收元数据、临时预览清理和 README 排版通过后续 `[skip ci]` 文档提交补录，不将其当作另一次代码 CI。
