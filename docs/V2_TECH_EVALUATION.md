# 现代 Agent 技术评估

2026-10-12 实际读取官方文档，经 agent-reach 网页读取路径取得页面正文。没有根据记忆声称某个模型或包是“当前最新”；未锁定 LangGraph/Deep Agents 的最新稳定包版本号，也未进行账户权限或付费端点验收。

| 技术 | 解决的实际问题与收益 | 复杂度 / 兼容性代价 | 当前决定 |
|---|---|---|---|
| OpenAI Responses API | 内置工具、工具状态及后续能力更统一；官方推荐逐步迁移 | 需要适配消息、工具 call_id、输出提取、usage 和错误；现有 Chat 解析不能直接换 URL | 不立即替换。官方明确 Chat Completions 继续支持；先保留可测试的统一 transport 边界 |
| 模型工具调用与结构化输出 | Controller 参数约束，降低错误动作/非法 JSON；工具需确定性验证 | strict 需要兼容模型和 JSON Schema；拒答/空内容仍需降级，不能代替财务口径校验 | 已实现可选严格 Controller schema；默认仍沿用原 JSON 模式。财务工具由明确逻辑调用，尚未迁移全套原生 function calling |
| MCP | 多外部工具的统一协议和连接 | 引入服务权限、远端信任、提示注入与审批边界；当前两个适配器无迫切跨服务需求 | 暂不接入，未启动远端 MCP。先保留工具契约，不因协议新而迁移 |
| LangGraph / Deep Agents | 持久执行、人机介入、多分支与更复杂长任务编排 | 需对现有 tick/SQLite/队列/快照作大量适配；长期维护依赖增加 | 不整体替换；当前有界反思、假设、图谱和记忆由现有架构可实现。跨进程任务恢复若成为瓶颈再验证候选版本 |
| Agent Evals / 可观测性 | 改变代码后发现回归、解释失败和调用成本 | 云评判需要标注、统计样本和费用；少数合成样本不能代表真实任务 | 已落地离线数据集、回归报告、trace 和费用缺失状态；不把合成命中率当真实研究准确率 |
| 浏览器工具与安全隔离 | JS/登录来源在普通 HTML/PDF 获取失败时有收益 | 浏览器会话、站点 allowlist、沙箱、资源和敏感操作隔离成本高 | 未集成 Computer Use；当前证据获取仍为现有 Reader。私网/重定向/下载限制是后续必须先验证的边界 |
| 分级模型路由 / 成本优化 | 简单决策和写作可按角色显式配置不同模型；预算与用量可审计 | 配置的模型须支持现有接口和字段；未实测不能承诺省费/质量不降 | 已实现 opt-in 角色/精确操作路由与配置费率，不改默认模型、不新增调用。没有自动选择“最新最强”模型 |

## 实际实现开关

- RESEARCHPILOT_MODEL_ROUTES_JSON：例如 `{"planner":"YOUR_PLANNER_MODEL","writer":"YOUR_WRITER_MODEL"}`。占位 ID 不是真实推荐模型；生产配置须替换为账户可用、接口兼容的模型。精确操作可覆盖角色。
- RESEARCHPILOT_STRICT_OUTPUTS=1：只将 agent.decide 的 response_format 设为 strict JSON Schema，要求 action/task/query/reason 并禁止额外属性。其他角色不强行迁移。
- RESEARCHPILOT_MODEL_PRICING_JSON：显式模型费率，必须有日期和需要的缓存费率。缺项为 unknown，工具费用不混入模型费用。

上述 API 配置有离线请求契约测试；没有真实 provider/模型逐项认证。错误路由配置保留默认模型，记录 fallback；配置的模型不兼容 API 时沿用现有错误降级。调用 trace 记录实际路由模型。暂不新增付费 Verifier，当前 Critic 的语义判断边界明确为 unknown。

## 官方依据

1. [OpenAI Responses 迁移指南](https://developers.openai.com/api/docs/guides/migrate-to-responses)：明确 Chat Completions remains supported，可逐个流程迁移，不能只替换 endpoint。
2. [Structured model outputs](https://developers.openai.com/api/docs/guides/structured-outputs)：JSON Schema 约束与拒答处理，不等于业务事实验证。
3. [MCP servers](https://developers.openai.com/api/docs/guides/tools-remote-mcp)：allowed_tools/require_approval、可信服务器与提示注入风险。
4. [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)：面向持久、长运行有状态编排；不是验证财务数据的替代品。
5. [Deep Agents overview](https://docs.langchain.com/oss/python/deepagents/overview)：文件上下文、子 Agent、长期记忆、规划及中断边界；本项目无需为多 Agent 拆服务。
6. [Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals)：trace grading、重复执行数据集和代码工作流观测。
7. [Computer use](https://developers.openai.com/api/docs/guides/tools-computer-use)：隔离环境、权限规则、执行限制和人工介入。

本轮网络只用于只读文档和工具更新检查，没有研究 API 请求。Agent Reach 更新检查因网络失败，未更新任何工具或依赖。
