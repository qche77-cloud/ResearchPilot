# 电脑界面恢复记录

日期：2026-10-20。用户反馈新增验证页面风格与原电脑端差异过大，要求恢复电脑界面。本轮恢复原 Studio 的导航与使用入口，验证算法和已有研究资料保留。

## 实际修改

- 从 Studio 侧栏撤掉“研究信号验证”；`index.html` 恢复为 `379c857` 的原始导航结构，深色样式、布局与原有交互未重做。
- 删除 `studio_app.py` 中内嵌验证页的分支，继续显示原研究、自选公司、财务筛选和数据工具。
- 已打开的旧验证会话和旧导航事件自动回到研究空间，保留所选研究，不清空草稿或历史。入口兼容无需重启正式 Runner。
- 验证工具仍通过独立的 `signal_validation_app.py` 运行，代码、账本、财报版本和复盘记录未删除。
- README 区分主界面与专项工具入口；更新回归脚本及使用说明。

电脑主入口：[原 Studio](http://127.0.0.1:8528/)。独立验证页 8550 用于专项验收，不再嵌入 Studio。手机网页和微信源码本轮未修改。

## 验收

| 范围 | 实际结果 |
| --- | --- |
| 完整离线回归 | [39/39 套件、365 单元测试通过](../artifacts/desktop-restore-regression-2026-10-20.json) |
| Studio 原交互 | [21 项通过](../artifacts/desktop-restore-studio-browser/browser-checks.json)，包含悬浮、引用、历史版本、财务工具、草稿和三种宽度 |
| 独立工具与主界面分离 | [10 项通过](../artifacts/desktop-restore-signal-browser/checks.json)，验证评分仍可用、Studio 无验证入口、原导航与历史正常 |
| 新增会话兼容用例 | 旧验证会话回到研究空间，所选研究与数据库记录保持一致，不启动模型或监控 |

测试写入和截图使用临时虚构资料，完整回归阻断外网和正式数据库访问。没有付费研究调用、数据库迁移或 Git 历史重写。发布仅选择本轮文件并执行完整暂存树密钥检查；提交带 `[skip ci]`。

修改文件：`studio_app.py`、`src/studio_bridge.py`、`src/studio_component/index.html`、`scripts/test_studio.py`、`scripts/test_research_signals.py`、`scripts/check_signal_browser.py`，及 README、使用说明、索引、变更记录、今日报告和回归证据。
