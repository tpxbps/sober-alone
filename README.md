<p align="center">
  <img src="./frontend/public/project-overview.jpg" alt="独醒项目概览" width="100%" />
</p>

# 独醒（Sober Alone）

独醒是一款本地优先的 AI-Native 剧本杀应用，由两部分组成：

- **AI 剧本杀游戏**：真人玩家选择角色，与多个拥有独立剧本、记忆和立场的 AI 角色共同发言、分析线索、自由讨论、投票并复盘。
- **AI 剧本创作工坊**：从一句创意出发，经过大纲、初稿、评审和人工确认，生成可直接游玩的新剧本。

## 快速开始

环境要求：Python 3.13、Node.js 22、pnpm 10、[uv](https://docs.astral.sh/uv/)。

### 使用通用 Agent 自动部署

还没有克隆仓库也没关系。把下面整段指令复制给能够访问终端的 Codex、Claude Code、DeepSeek Harness 等现代通用 Agent，它可以从 GitHub 克隆项目并完成本地部署：

```text
请将 https://github.com/tpxbps/sober-alone 克隆到本地合适的目录并完成“独醒”的本地单用户部署；如果当前目录已经是该仓库，则直接复用，保留所有已有改动，不要执行会覆盖用户修改的 Git 操作。

进入仓库后，先完整阅读 README.md、PROJECT.md 和 backend/.env.example，再按仓库实际说明执行。请检查 Git、Python 3.13、Node.js 22、pnpm 10 和 uv；若缺少必要工具或需要系统级安装权限，先向我说明并请求确认。

不要添加 mock 模式，不要编造、下载或提交任何 API Key。复制 backend/.env.example 为仅本地使用的 backend/.env，并提示我至少配置 DEEPSEEK_API_KEY；可选的 STEPFUN_API_KEY、ZHIPUAI_API_KEY、DOUBAO_API_KEY、MIMO_API_KEY 和 QWEN_API_KEY 由我按需提供。如果你无法安全写入密钥，就暂停让我手动填写 backend/.env，且不要在回复、日志或命令输出中回显密钥。

密钥就绪后，依次完成：
1. 在 backend 中执行 uv sync --frozen、uv run python -m app.cli init、uv run pytest。
2. 在 frontend 中执行 pnpm install --frozen-lockfile、pnpm test、pnpm lint、pnpm build。
3. 启动后端和前端开发服务，验证 GET http://127.0.0.1:8000/healthz、GET http://127.0.0.1:8000/api/v1/system/capabilities 以及 http://127.0.0.1:5173 可以访问。

最后告诉我：项目克隆位置、前后端访问地址、实际通过的检查、当前启用和未启用的供应商能力，以及仍需我处理的问题。不要提交 backend/.env、临时密钥、数据库、依赖目录、缓存或生成资源。
```

如果 Agent 不能代为管理密钥，可让它先完成依赖安装，然后由你手动填写 `backend/.env`。最低可运行配置仍需要有效的 `DEEPSEEK_API_KEY`；图片、静态语音和向量检索等能力按下方表格选配。

以下是等价的手动步骤。

### 1. 启动后端

```bash
cd backend
```

复制配置文件：Windows 执行 `copy .env.example .env`，macOS / Linux 执行 `cp .env.example .env`。然后在 `backend/.env` 中至少填写：

```dotenv
DEEPSEEK_API_KEY=你的_Key
```

然后执行：

```bash
uv sync --frozen
uv run python -m app.cli init
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

`init` 会创建或升级本地数据库，并在空库中导入《零点来电》。拉取包含数据库变更的更新后，请重新执行该命令。

### 2. 启动前端

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
```

访问 `http://127.0.0.1:5173`，选择《零点来电》和一个角色开始游戏。

## 可选能力

仅配置 `DEEPSEEK_API_KEY` 即可体验纯文本游戏和纯文本剧本创作。其他能力按需在 `backend/.env` 中配置；缺少对应 Key 时会自动禁用或降级。

| 能力                           | 配置项            |
| ------------------------------ | ----------------- |
| 摘要、流式语音                 | `STEPFUN_API_KEY` |
| 角色剧本向量检索、GLM 角色模型 | `ZHIPUAI_API_KEY` |
| 图片生成                       | `DOUBAO_API_KEY`  |
| 静态语音                       | `MIMO_API_KEY`    |
| 千问角色模型                   | `QWEN_API_KEY`    |
| 混元角色模型                   | `HUNYUAN_API_KEY` |

代码结构、核心流程、数据边界和阅读顺序统一记录在 [PROJECT.md](PROJECT.md)。

## 技术栈

| 模块    | 技术                                              |
| ------- | ------------------------------------------------- |
| 前端    | React 19、TypeScript、Vite、Zustand、Tailwind CSS |
| 后端    | FastAPI、SQLAlchemy、Alembic、Pydantic            |
| AI 编排 | LangChain、LangGraph、多角色 Agent、结构化输出    |
| 数据    | SQLite、可选 Chroma 向量检索                      |
| 测试    | Pytest、Vitest、Playwright、GitHub Actions        |

## 开源协议

本项目采用 [MIT License](LICENSE)。
