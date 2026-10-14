# Studio 悬停与页面过渡打磨记录

日期：2026-10-14。需求：保留已经认可的布局，进一步提升悬停、浮层、页面切换与操作反馈的美观和连贯性。

## 实际实现

- 卡片悬停增加轻微抬升、边框和柔和阴影；按钮有悬停、按下反馈；导航选中标记更清晰。
- 导航图标、下载按钮和任务标题停留约 380 ms 显示浮层提示。支持键盘焦点、Escape 关闭，鼠标进入浮层后仍可阅读。
- 引用停留可预览该版本保存的来源标题、日期和原文摘录，保持报告与当前对话面板；点击后仍打开完整证据并短暂强调目标。
- 主要页面用约 260 ms 的淡入和轻微位移过渡；右侧面板约 180 ms；报告版本约 200 ms。搜索弹窗和财务依据展开也有短过渡。
- 手机任务抽屉增加滑入与收起过渡；隐藏时不能点击或获得焦点。
- 等待后台确认操作时显示细进度提示，确认或超时后清除，不伪造任务进度。
- 用户选择减少动态效果时，禁用进入动画、悬停位移和点击缩放；悬停提示仍可使用。

后台状态轮询不会重复播放进入动画，也不改变财务逻辑、任务命令和数据库设计。浮层内容来自当前保存的证据，采用 DOM `textContent`，不插入来源中的原始 HTML。新增文件均为本地资源，不引入前端依赖或外部服务。

## 修改文件

| 文件 | 作用 |
| --- | --- |
| `src/studio_component/interactions.js` | 独立视觉行为：延迟浮层、焦点与鼠标优先级、过渡、证据强调及减少动态效果 |
| `src/studio_component/interactions.css` | 悬停深度、按钮反馈、浮层、导航标记和手机抽屉过渡 |
| `src/studio_component/index.html` | 加载本地交互资源及资源版本参数 |
| `src/studio_component/studio.js` | 在实际导航、版本切换与证据操作时触发动效，轮询跳过动效 |
| `scripts/check_studio_browser.py` | 在原 15 项验收上追加 6 项交互检查 |
| `README.md`、本报告 | 更新说明与复测方式 |
| `artifacts/studio-polish/` | 隔离浏览器结果与虚构数据截图 |
| `artifacts/studio-polish-regression-2026-10-14.json` | 本次全量离线回归结果 |
| `artifacts/studio-polish-live-2026-10-14.json` | 正式入口只读交互验收 |
| `artifacts/agent-evaluation.json` | 原评测脚本随回归重新生成的结果 |

## 已执行的验证

| 验证 | 结果 |
| --- | --- |
| 新交互 JS 与主 JS 的 Node 语法检查 | 通过 |
| 全量离线回归 | 25/25 组，178 个单元测试通过 |
| 隔离浏览器验收 | 21/21 项，页面错误 0 |
| 桌面、平板与手机 | 1440、1024、390 像素视口通过，页面无横向溢出 |
| 正式入口 | 原 8511 地址加载新资源、显示悬停浮层、完成导航；页面错误 0，付费命令 0 |

新增浏览器检查覆盖卡片悬停、延迟提示及 Escape 关闭、四秒轮询不重播动画、引用停留预览且不切换面板、旧版本的键盘引用预览，以及减少动态效果模式。原有草稿、报告导出、证据联动、财务筛选、数据追溯和旧工具入口同时复测通过。

验收发现并修复了页面重排时，静止鼠标可能抢占键盘引用浮层的问题。现在键盘焦点优先，实际移动鼠标后再恢复鼠标预览。验收脚本的动画计数探针也调整为不返回被浏览器自动调用的原型方法。最终无未通过项。

示例：[引用悬停预览](../artifacts/studio-polish/citation-hover.png)、[卡片悬停](../artifacts/studio-polish/home-hover.png)。全部公开截图为隔离的虚构资料，没有截取用户真实历史。

复测：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH='G:\ResearchPilot\.venv\playwright-browsers'
.\.venv\Scripts\python.exe -m scripts.check_studio_browser --url http://127.0.0.1:8510 --output artifacts/studio-polish
.\.venv\Scripts\python.exe -m scripts.run_offline_tests --output artifacts/studio-polish-regression-2026-10-14.json
```

正式入口：`http://127.0.0.1:8511`，重新加载页面即可读取新资源。动态效果仅影响 Studio，自带完整数据工具仍采用现有原生界面。新效果已在 Chromium 验证，未声称完成所有浏览器认证。

代码已推送 `main`：`e054940db24cbcc0cc5193fe22927cd724d30715`，提交说明为 `feat: polish Studio hover previews and page transitions`。

[GitHub Actions 38539319837](https://github.com/qche77-cloud/ResearchPilot/actions/runs/38539319837) 已完成且成功。下载真实 `offline-regression` 产物并核对：25/25 组、178 个单元测试通过。云端原始报告保存在 `artifacts/studio-polish-ci-e054940/`，运行状态在 `artifacts/studio-polish-cloud-run-e054940.json`。21 项浏览器验收在本地执行，未标记为云端浏览器测试。CI 成功后用 `[skip ci]` 文档提交保存本记录与云端产物，不修改已验证代码。
