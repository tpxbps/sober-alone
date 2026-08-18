# 独醒项目上下文

本文档集中记录理解和继续开发独醒所需的上下文。README 只负责帮助第一次进入仓库的人快速判断项目价值并运行起来。

## 1. 产品定位

独醒是一款本地优先的 AI-Native 剧本杀应用。它不是传统剧本阅读器：每个非真人角色由独立 Agent 驱动，依据自己的个人剧本、已知线索、对他人的怀疑和当前阶段进行发言；真人玩家参与同一套阶段机，最终共同完成投票与复盘。

项目同时包含剧本创作工作流，允许用户从一句创意出发，逐步生成大纲、初稿、评审稿、终稿和可运行的结构化游戏数据。关键阶段保留人工确认、回退、历史检查点和分叉能力。

当前边界是 `local-first / single-user / single-process`。运行数据只保存在本机，不提供账号、多人在线房间或公网服务能力。
剧本创作的检查点和进度状态也仅保存在当前后端进程内，重启后不能恢复未完成的创作会话。

## 2. 核心体验

### 游戏链路

```text
剧本大厅 → 选择角色 → 自我介绍 → [线索分析 → 自由讨论] × N → 总结发言 → 投票 → 真相复盘
```

`GameFlowController` 维护阶段和发言队列；`GameService` 是 API 层使用的稳定外观；角色 Agent 只接收自己的个人剧本，并随着游戏记录更新上下文。发言通过 SSE 流式返回，结束后再执行角色反应分析和服务端状态对账。

### 创作链路

```text
创意 → 大纲 → 初稿 → AI 评审 → 终稿 → 游戏数据转换 → 安全检查 → 保存 → 可选资产
```

工作流由 LangGraph 编排。文本剧本保存成功即视为核心流程完成；图片、向量和语音都是能力驱动的可选任务，缺少 Key 时使用 `skipped + reason`，不会伪装成成功。

## 3. 技术结构

```text
frontend/src/
  components/       游戏与创作 UI
  screens/          页面级协调器
  stores/           Zustand 状态与业务动作
  lib/              API、SSE runner、状态适配器

backend/app/
  api/routes/       FastAPI 路由
  agents/           角色 Agent、提示词与反应分析
  game/             阶段机与发言队列
  services/         游戏 façade、语音、投票与运行时仓储
  script_editor/    LangGraph 创作节点、服务与进度状态
  db/               SQLAlchemy 模型、会话与就绪检查
  seed.py           内置纯文本样例

backend/migrations/ Alembic 业务表迁移
backend/tests/      后端关键特征与回归测试
frontend/e2e/       主游戏浏览器流程
```

主要数据表为 `scripts`、`characters`、`game_sessions`、`player_states` 和 `game_records`。数据库、检查点、向量和运行时媒体统一写入被 Git 忽略的 `backend/.local-data/`。

## 4. 模型与能力边界

- DeepSeek 是最低运行依赖，负责主游戏 Agent 和文本创作。
- 没有 StepFun 时，摘要回退到当前主模型。
- 没有智谱 Embedding 时，不注册 RAG 工具，只向角色注入其自己的完整剧本。
- 图片、静态 TTS、流式 TTS 和额外角色模型按配置动态启用。
- `/api/v1/system/capabilities` 是前端展示能力状态的唯一来源，不返回 Key。

提示词、角色剧本、玩家发言和待生成资产会发送给用户主动启用的云模型供应商，并可能产生费用。不要把敏感信息或无权处理的内容输入第三方模型。

## 5. 内置样例《零点来电》

样例是四人、两轮线索、约 25 分钟的原创纯文本简单本。结构重点是：

- 封闭广播站场景和明确案发时间窗；
- 四名角色分别拥有独立动机、秘密和可验证时间线；
- 第一轮公开关系与行为疑点，第二轮用死亡时间、音频拼接、门禁和物证完成收束；
- 凶手通过预录广播伪造死者存活时间，所有红鲱鱼都在最终复盘中得到解释；
- 不依赖图片、语音或向量数据，适合验证核心 Agent 游戏链路。

## 6. 推荐阅读顺序

1. `backend/app/seed.py`：先理解一局游戏需要的数据形态。
2. `backend/app/game/flow_controller.py`：理解阶段推进和发言顺序。
3. `backend/app/services/game_service.py`：理解 API 与领域流程的衔接。
4. `backend/app/agents/agent_player.py`：理解角色上下文、工具和流式发言。
5. `frontend/src/stores/gameStore.ts`：理解前端状态、取消与服务端对账。
6. `backend/app/script_editor/graph.py` 与 `frontend/src/components/script-editor/ContentPanel.tsx`：理解创作工作流。

## 7. 开发约束

- 保持 REST/SSE 事件、LangGraph state key 和阶段语义稳定。
- 新能力必须有缺失配置时的明确降级路径。
- 角色之间不得共享个人剧本或越权查询其他角色知识。
- 异步结果写入前必须校验当前 session 和 operation identity，避免旧会话污染新会话。
- 优先改善游戏体验、剧本质量、Agent 推理稳定性和创作可控性；不在项目内扩展部署平台或运维模板。
