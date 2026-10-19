# ResearchPilot 微信小程序：本地开发版

更新：2026-10-20。目标是本人和少量朋友使用的邀请体验版。

本轮同步新版底部面板、报告目录/字号/引用定位、搜索筛选和财务来源详情。15 项控制器检查与 27 项浏览器检查通过；原生运行限制如下。[界面交付与截图](../docs/MOBILE_UI_2026-10-20.md)。

原生页面与 Python API 已实现。本地离线流程可运行，**尚未经过微信开发者工具编译和真机验收，也未部署公网或生成体验码**。浏览器预览是单独的联调界面，不是微信运行环境。

## 先体验本地流程

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-miniprogram.txt
.\.venv\Scripts\python.exe -m scripts.serve_miniprogram --demo --port 8540
```

打开 <http://127.0.0.1:8540/preview/>，选择演示账号 A 或 B。

可操作新建演示研究、报告版本切换、证据与来源、研究过程、自选公司、财务源记录和退出登录。全部内容为虚构夹具，不调用模型、搜索、行情或微信登录 API。数据在单独临时目录中；正常结束服务后清除，演示重启不会保留。浏览器预览只由 `--demo` 模式提供。

## 在手机上使用

### 手机浏览器先体验网页

手机和电脑连接同一 Wi-Fi，查到电脑的 WLAN IPv4 后，显式开启独立的虚构局域网演示。例如本次电脑地址为 `192.168.1.2`：

```powershell
.\.venv\Scripts\python.exe -m scripts.serve_miniprogram --demo --lan-demo --host 192.168.1.2 --port 8542
```

手机 Safari/Chrome 打开 <http://192.168.1.2:8542/preview/>，选择体验 A 或 B。电脑及服务需保持运行；该地址不提供互联网访问，也不是微信小程序体验码。IP 变化后应使用新的 WLAN 地址。

默认 `--demo` 仍仅允许本机回环地址；只有显式 `--lan-demo` 才允许绑定一个 RFC1918 私有 IPv4，不允许 `0.0.0.0`、公网地址或正式模式启用此标志。局域网演示仍使用临时虚构数据，不使用真实研究 API，本次没有修改系统防火墙。

网页对局域网 HTTP 环境提供请求标识与来源复制的兼容路径，复制被浏览器禁止时可以长按页面中的来源地址。若手机连不上，先核对同一 Wi-Fi、电脑服务及 Windows 对 Python 专用网络访问的允许状态；电脑本机访问成功不替代实体手机连接验收。

### 接入微信开发者工具

1. 在微信开发者工具导入本目录。`project.config.json` 当前为 `touristappid`；正式联调请使用自己的小程序 AppID，在开发者工具的本地配置中设置。
2. `config.js` 默认显式使用 `demo` 和本机 8540 API。仅本机开发者工具调试时，按工具要求配置调试域名校验；这不代表手机可以访问开发电脑的 `127.0.0.1`。
3. 原生页面包括研究首页、任务详情、报告/证据/过程、版本选择、自选、公司财务、账号和登录。
4. 正式接入时，将 `config.js` 的 `mode` 改为 `wechat`，`apiBase` 改为自己的 HTTPS API 域名，并在微信后台配置该域名。正式模式会拒绝 HTTP，微信登录失败不会自动降级为演示账号。

客户端只包含公开的 AppID/域名配置。**不要把 AppSecret、模型或搜索密钥放入小程序、截图、Git 或聊天。**

## 配置正式后端

服务端使用现有 Python 环境，密钥在服务端环境或现有 `.env` 中设置：

| 环境变量 | 作用 |
| --- | --- |
| `WECHAT_APP_ID` | 与客户端项目一致的小程序 AppID |
| `WECHAT_APP_SECRET` | 微信服务端密钥；仅供服务端交换临时登录凭证 |
| `RP_MINI_DATA_ROOT` | 可选；默认 `data/miniprogram`，独立于桌面研究库 |
| `RP_MINI_ENABLE_RESEARCH` | 默认关闭；设为 `1` 才允许真实研究 |
| `OPENAI_API_KEY`、`TAVILY_API_KEY` | 复用现有后端配置；新建真实研究要求两项都已配置 |

```powershell
# 仅启动后端，不会自动开始研究；默认绑定本机。
.\.venv\Scripts\python.exe -m scripts.serve_miniprogram --port 8541

# 在另一个本机终端生成一次性邀请码（不要将输出写入公开记录）。
.\.venv\Scripts\python.exe -m scripts.mini_admin invite --hours 48

# 停用指定内部账号并撤销会话。
.\.venv\Scripts\python.exe -m scripts.mini_admin disable USER_ID
```

公网接入需自行准备服务器、TLS/HTTPS 与微信域名配置；API 可在 HTTPS 反向代理后使用。当前按单服务进程设计，不使用多 worker 或热重载运行真实任务。

首次微信登录需有效邀请码；已加入用户之后可直接微信登录。邀请码单人使用、有有效期，应用会话默认一天并可撤销。不读取头像、昵称、手机号或通讯录。停用账号会阻止新访问，已提交的有限任务不会因此自动取消。

## 数据和费用边界

- 每人独立研究库与工作台。默认不导入、共享或修改桌面历史和自选；**当前没有桌面自动同步或财报上传接口**。
- 默认每人每日 5 次新任务、每次最多 6 次搜索、每日最多 12 次恢复、每人同时 1 个任务、全服务同时 2 个任务，最多 20 个邀请账号。日配额按北京时间重置。
- 创建任务必须携带 `Idempotency-Key`。超时重试沿用原请求标识，不重复创建或消耗新任务配额。暂停/恢复不允许客户端扩大搜索预算。
- 研究引擎限制 40 次迭代、16 次搜索尝试；这些限制与搜索上限都不等于精确的金额硬上限。模型费用仍依赖真实用量及已有价格配置，缺失时显示未知。
- 页面离开即停止轮询，服务器在当前进程存活期间继续执行。服务重启后不自动重新发起模型调用，需手动恢复。
- 读取报告只使用该用户保存的指定版本；旧报告不拿当前证据补齐。财务缺失值或未知单位不由前端或模型填补。

## 复验

需要 Python、可选 API 依赖和 Node.js：

```powershell
.\.venv\Scripts\python.exe -m scripts.run_offline_tests --mobile --output artifacts/miniprogram-local-regression-2026-10-19.json
node scripts/check_mini_client.cjs

# 自行启动/关闭隔离虚构服务的 UI 验收，需 Playwright 与 Chromium。
python -m scripts.check_mobile_ui

# 先在另一个终端开启全新的 --demo 服务，再做有写入的虚构浏览器验收。
.\.venv\Scripts\python.exe -m scripts.check_miniprogram_browser --url http://127.0.0.1:8540
```

客户端检查使用 wx API 替身来验证真实页面控制器，**不替代微信编译器和真机测试**。浏览器检查默认只接受回环地址；显式 `--lan-demo` 可检查私有 IPv4，且后端必须标注为 LAN demo。外部微信服务、合法域名、真机、真实付费 API 与上线审核仍待配置后验收。
