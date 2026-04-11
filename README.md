# 独醒 (Sober Alone)

[English](#english) | 中文

**众人皆醉我独醒** — AI 驱动的剧本杀游戏。

玩家扮演侦探角色，与多个 AI 角色一起阅读线索、自由讨论、投票推理，最终揭开真相。

## 架构

```
sober-alone/
├── backend/          # Python (FastAPI + LangChain)
│   └── app/
│       ├── api/      # REST/SSE 接口
│       ├── game/     # 游戏核心逻辑（发言调度、投票、阶段管理）
│       ├── agents/   # AI 角色 Agent
│       ├── rag/      # 剧本知识库检索
│       ├── services/ # 业务服务层
│       └── core/     # 配置、LLM 工厂
│
└── frontend/         # React + TypeScript + Vite
    └── src/
        ├── screens/     # 页面（大厅、游戏）
        ├── components/  # UI 组件
        ├── stores/      # Zustand 状态管理
        └── types/       # 类型定义
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

> 在 backend/.env 中配置 API Key（参考 core/config.py 中的 key 名称）

### 前端

```bash
cd frontend
npm install
npm run dev
```

访问 `http://localhost:5173`。

## 游戏流程

1. **大厅** — 浏览剧本列表，选择剧本
2. **开场** — AI 叙述故事背景，分配角色
3. **线索分析** — 玩家与 AI 角色共同分析线索
4. **自由讨论** — AI 角色按策略轮流发言，玩家可随时参与
5. **投票** — 所有人投票选出嫌疑人
6. **总结** — 公布真相与投票结果

## 支持的 LLM

通过 `.env` 配置，支持多个 LLM 提供商，可为不同 AI 角色指定不同模型。

## License

Private

---

<a id="english"></a>

# Sober Alone

[English](#english) | [中文](#)

An AI-powered murder mystery game where you play as a detective, analyzing clues, discussing with AI characters, and voting to uncover the truth.

## Architecture

```
sober-alone/
├── backend/          # Python (FastAPI + LangChain)
│   └── app/
│       ├── api/      # REST / SSE endpoints
│       ├── game/     # Core game logic (speech scheduling, voting, stage management)
│       ├── agents/   # AI character agents
│       ├── rag/      # Script knowledge base retrieval
│       ├── services/ # Business service layer
│       └── core/     # Config, LLM factory
│
└── frontend/         # React + TypeScript + Vite
    └── src/
        ├── screens/     # Pages (lobby, game)
        ├── components/  # UI components
        ├── stores/      # Zustand state management
        └── types/       # Type definitions
```

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.11+
- At least one LLM API Key

### Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

> Configure API Keys in `backend/.env` (see `core/config.py` for key names).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173`.

## Game Flow

1. **Lobby** — Browse and select a script
2. **Intro** — AI narrates the story background and assigns roles
3. **Clue Analysis** — Players and AI characters analyze clues together
4. **Free Discussion** — AI characters speak in turns; the player can join anytime
5. **Vote** — Everyone votes for the prime suspect
6. **Summary** — Truth revealed with voting results

## Supported LLMs

Configure via `.env`. Multiple LLM providers are supported — assign different models to different AI characters.

## License

Private
