# 独醒 (Sober Alone)

**众人皆醉我独醒** — AI 驱动的剧本杀游戏。

玩家扮演侦探角色，与多个 AI 角色一起阅读线索、自由讨论、投票推理，最终揭开真相。

## 功能特性

- **AI 剧本创作** — 从一句话创意到完整可玩游戏剧本的全自动生成流程，支持人工审核与迭代修改
- **多 AI 角色** — 每个 AI 角色拥有独立人格、记忆和推理能力，基于 LangGraph Agent 架构
- **RAG 知识检索** — ChromaDB 向量化剧本内容，角色可随时回忆剧本细节
- **实时 TTS** — AI 角色发言实时语音合成（流式 WebSocket），剧本预生成静态语音
- **智能发言调度** — 自由讨论阶段基于嫌疑度和发言机会的加权策略调度
- **AI 美术** — 自动生成剧本封面和角色头像（豆包 Seedream）
- **移动端适配** — 响应式布局，手机可玩

## 架构

```
sober-alone/
├── backend/          # Python 3.13 (FastAPI + LangChain + LangGraph)
│   └── app/
│       ├── api/          # REST/SSE 接口
│       │   └── routes/
│       │       ├── game.py            # 游戏接口（12 endpoints）
│       │       └── script_editor.py   # 剧本编辑器接口（16 endpoints）
│       ├── game/         # 游戏核心逻辑
│       │   ├── flow_controller.py     # 阶段状态机、发言处理、反应广播
│       │   └── speech_scheduler.py    # 自由讨论加权调度
│       ├── agents/       # AI 角色 Agent
│       │   ├── agent_player.py        # 双 Agent 架构（主 Agent + 反应 Agent）
│       │   ├── agent_manager.py       # 多 Agent 生命周期管理
│       │   └── tools/                 # RAG 检索、嫌疑更新、投票
│       ├── script_editor/ # AI 剧本创作工作流
│       │   ├── graph.py              # LangGraph 13 节点工作流
│       │   ├── nodes/                # 大纲→初稿→评审→终稿→结构化→安全检查→保存
│       │   ├── services/             # 图片生成、TTS、向量化、进度推送
│       │   └── prompts/              # 可自定义的提示词模板
│       ├── rag/           # ChromaDB 向量检索（zhipuai embedding-3）
│       ├── services/      # 业务服务层
│       │   ├── game_service.py       # 游戏逻辑、SSE 流式推送
│       │   ├── tts_service.py        # 静态/按需 TTS
│       │   └── streaming_tts.py      # 流式 TTS（WebSocket）
│       └── core/          # 配置、LLM 工厂（5+ 提供商）
│
└── frontend/         # React 19 + TypeScript + Vite + Zustand
    └── src/
        ├── screens/
        │   ├── Homepage.tsx           # 剧本选择、角色配置
        │   ├── GamePage.tsx           # 游戏主界面、SSE 编排
        │   └── ScriptEditorPage.tsx   # 剧本创作界面
        ├── components/
        │   ├── game/                  # 聊天、投票、角色面板等 12 组件
        │   ├── script-editor/         # 时间线、内容面板、AI 助手聊天
        │   └── ui/                    # 通用 UI 组件
        ├── stores/                    # Zustand 状态管理
        ├── lib/                       # 音频管理器、API 客户端
        └── types/                     # TypeScript 类型定义
```

## 快速开始

### 环境要求

- Node.js 18+
- Python 3.11+
- 至少一个 LLM API Key

### 后端

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

在 `backend/.env` 中配置 API Key：

```
DEEPSEEK_API_KEY=...
STEPFUN_API_KEY=...
QWEN_API_KEY=...
DOUBAO_API_KEY=...
MIMO_API_KEY=...
ZHIPUAI_API_KEY=...
```

### 前端

```bash
cd frontend
pnpm install
pnpm dev
```

访问 `http://localhost:5173`。

## 游戏流程

```
大厅 → 开场（AI 叙述背景）→ 线索分析 ⇄ 自由讨论 [多轮] → 总结陈词 → 投票 → 揭晓真相
```

1. **大厅** — 浏览剧本列表，选择角色和 AI 模型
2. **开场** — AI 叙述故事背景，玩家阅读个人剧本
3. **线索分析** — 玩家与 AI 角色轮流分析线索
4. **自由讨论** — AI 角色按嫌疑度策略调度发言，玩家可随时参与
5. **总结陈词** — 最后的陈述机会
6. **投票** — 所有人投票选出嫌疑人
7. **揭晓** — 公布真相与投票结果

## 剧本创作

内置 AI 剧本创作工作流，从一句话创意到完整可玩游戏：

```
创意输入 → 大纲生成 → 初稿 → AI 评审 → 终稿 → 结构化数据 → 安全检查 → 保存
                                                                    ↓
                                                            自动生成：封面图、角色头像、语音、向量索引
```

- **5 个人工审核点** — 大纲、初稿、终稿、结构化数据均可编辑修改
- **可自定义提示词** — 每个生成步骤的提示词都可调整
- **时间旅行** — 支持从历史检查点分叉，重新生成
- **AI 创作助手** — 上下文感知的 AI 聊天，可查看当前工作流内容

## 技术栈

| 层级     | 技术                                        |
| -------- | ------------------------------------------- |
| 后端框架 | FastAPI + SQLAlchemy (async)                |
| AI Agent | LangChain + LangGraph                       |
| 前端框架 | React 19 + TypeScript + Vite                |
| 状态管理 | Zustand                                     |
| 样式     | TailwindCSS + Framer Motion                 |
| 数据库   | SQLite + ChromaDB                           |
| TTS      | mimo-v2.5-tts (静态) + step-tts-mini (流式) |
| 图片生成 | doubao-seedream-4-0                         |
| 向量嵌入 | zhipuai embedding-3                         |

## 支持的 LLM

通过 `.env` 配置，支持多个 LLM 提供商，可为不同 AI 角色指定不同模型：

- DeepSeek (deepseek-v4-flash) — 默认
- 阶跃星辰 (step-3.5-flash)
- 通义千问 (qwen3.5-flash)
- 豆包 (doubao-seed-2-0-mini)

## License

Private
