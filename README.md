<p align="center">
  <img src="./frontend/public/project-overview.jpg" alt="独醒 AI 剧本杀项目概览" width="100%" />
</p>

# 独醒 AI 剧本杀（Sober Alone）

## 项目概览

独醒是一款 AI-Native 剧本杀游戏。真人玩家选择一个角色，与多个由大模型驱动的角色依次发言、分析线索、自由讨论、投票并完成复盘；也可以从一句创意开始，通过带人工审核节点的工作流生成新剧本。

项目面向本地单用户体验和源码展示，重点呈现三条应用链路：

- **多角色游戏**：每个 AI 角色拥有独立剧本、记忆、立场与推理过程。
- **流式交互**：后端通过 SSE 输出思考提示、正文、反应分析和可选语音。
- **剧本创作**：LangGraph 编排大纲、初稿、评审、终稿、结构转换与可选资产生成。

仓库内置原创纯文本简单本《零点来电》，无需图片、语音或预计算向量即可体验完整游戏流程。

## 技术栈

| 模块 | 技术 |
|---|---|
| 前端 | React 19、TypeScript、Vite、Zustand、Tailwind CSS、Framer Motion |
| 后端 | FastAPI、SQLAlchemy、Alembic、Pydantic、SSE |
| AI 编排 | LangChain、LangGraph、多角色 Agent、结构化输出 |
| 数据 | SQLite；可选 Chroma 向量检索 |
| 测试 | Pytest、Vitest、Playwright、GitHub Actions |

## 快速开始

环境要求：Python 3.13、Node.js 22、pnpm 10、[uv](https://docs.astral.sh/uv/)。

### 1. 启动后端

```bash
cd backend
copy .env.example .env        # Windows
# cp .env.example .env        # macOS / Linux
```

在 `backend/.env` 中填写：

```dotenv
DEEPSEEK_API_KEY=你的_Key
```

然后执行：

```bash
uv sync --frozen
uv run python -m app.cli init
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`init` 会建库并在空库中导入《零点来电》，重复执行不会覆盖已有剧本。启动前应看到 `Database ready.`；若提示 `no such table`，停止后端并重新执行该命令。

### 2. 启动前端

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
```

访问 `http://127.0.0.1:5173`，选择《零点来电》和一个角色开始游戏。

### PS：最低运行与完整能力

最低运行版本只需要 `DEEPSEEK_API_KEY`，可完成纯文本样例游戏和纯文本剧本创作。完整版需在 `backend/.env` 手动填写对应供应商 Key；未配置的可选能力会自动禁用或跳过。

| 能力 | 手动配置 | 未配置时 |
|---|---|---|
| 主游戏、纯文本创作 | `DEEPSEEK_API_KEY` | 核心 AI 流程不可用 |
| 摘要、流式 TTS | `STEPFUN_API_KEY` | 摘要回退主模型，流式 TTS 关闭 |
| 角色剧本 RAG | `ZHIPUAI_API_KEY` | 直接注入当前角色的完整个人剧本 |
| 图片生成 | `DOUBAO_API_KEY` | 图片任务跳过 |
| 静态 TTS | `MIMO_API_KEY` | 静态语音任务跳过 |
| 千问角色模型 | `QWEN_API_KEY` | 不显示对应模型选项 |

运行时可访问 `GET /api/v1/system/capabilities` 查看实际启用状态。代码结构、核心流程、数据边界和阅读顺序统一记录在 [PROJECT.md](PROJECT.md)。

## 开源协议

本项目采用 [MIT License](LICENSE)。
