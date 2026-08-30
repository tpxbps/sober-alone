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

`init` 会创建或升级数据库，并在空库中导入《零点来电》，重复执行不会覆盖已有剧本。每次拉取包含数据库迁移的更新后都应重新执行一次；启动前应看到 `Database ready.`。若提示 `schema is out of date`、`no such table` 或 `no such column`，先停止后端，再重新执行该命令。

### 2. 启动前端

```bash
cd frontend
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
```

访问 `http://127.0.0.1:5173`，选择《零点来电》和一个角色开始游戏。

### PS：最低运行与完整能力

最低运行版本只需要 `DEEPSEEK_API_KEY`，可完成纯文本样例游戏和纯文本剧本创作。完整版需在 `backend/.env` 手动填写对应供应商 Key；未配置的可选能力会自动禁用或跳过。

| 能力               | 手动配置           | 未配置时                       |
| ------------------ | ------------------ | ------------------------------ |
| 主游戏、纯文本创作 | `DEEPSEEK_API_KEY` | 核心 AI 流程不可用             |
| 摘要、流式 TTS     | `STEPFUN_API_KEY`  | 摘要回退主模型，流式 TTS 关闭  |
| 角色剧本 RAG       | `ZHIPUAI_API_KEY`  | 直接注入当前角色的完整个人剧本 |
| 图片生成           | `DOUBAO_API_KEY`   | 图片任务跳过                   |
| 静态 TTS           | `MIMO_API_KEY`     | 静态语音任务跳过               |
| 千问角色模型       | `QWEN_API_KEY`     | 不显示对应模型选项             |
| 腾讯混元角色模型   | `HUNYUAN_API_KEY`  | 不显示 Hy3 模型选项            |
| 智谱角色模型       | `ZHIPUAI_API_KEY`  | 不显示 GLM 5.3 Flash 模型选项  |

角色模型由后端能力接口统一发布；当前注册了 DeepSeek V4 Flash、Step 3.5 Flash、Qwen 3.8 Flash、Doubao Seed 2.0 Mini、MiMo V2.5、Hy3 和 GLM 5.3 Flash。打开选角窗口后，系统会在不阻塞角色数据的前提下执行一次带缓存的双通道轻量探测：发言链路记录首字时延，反应链路使用与游戏相同的 JSON Schema 和标准发言案例记录结构化结果的完整耗时。只有成功响应但超过阈值的模型才提示“当前响应稍慢”；网络波动或单次探测失败会提示“测速未完成”，不会被误判为慢模型。用户可在选角标题旁点击“模型测速”立即重测。运行时可访问 `GET /api/v1/system/model-health` 查看状态，或调用 `POST /api/v1/system/model-health/refresh` 强制刷新；也可用 `uv run python -m app.cli probe-models` 手动诊断本机已配置端点。

### 存量线索迁移

升级到结构化线索版本后，旧纯文本剧本仍可兼容游玩。需要正式转换时，先在数据库副本上执行默认 dry-run；命令会保存可恢复 manifest，并用 DeepSeek 做结构化转换和第二次事实覆盖审查：

```bash
cd backend
uv run python -m app.cli migrate-clues
uv run python -m app.cli migrate-clues --apply
uv run python -m app.cli regenerate-clue-tts
```

`--apply` 会先创建 SQLite 备份，只有审查通过的剧本会被事务性写入。语音命令只备份并替换线索阶段音频，不会改动角色语音、其他系统语音、图片或 Chroma 向量；也可重复传入 `--script-id <ID>` 做小批量验证。不要直接在唯一一份线上数据库上运行这些命令。

若升级的是带旧版作者标识的存量数据库，可在明确的迁移窗口内临时设置 `ALLOW_LEGACY_OWNER_CLAIM=true`。旧浏览器会在“设置”中自动识别本地记录并提供一键恢复；迁移结束后应重新关闭该开关。

代码结构、核心流程、数据边界和阅读顺序统一记录在 [PROJECT.md](PROJECT.md)。

## 技术栈

| 模块    | 技术                                                             |
| ------- | ---------------------------------------------------------------- |
| 前端    | React 19、TypeScript、Vite、Zustand、Tailwind CSS、Framer Motion |
| 后端    | FastAPI、SQLAlchemy、Alembic、Pydantic、SSE                      |
| AI 编排 | LangChain、LangGraph、多角色 Agent、结构化输出                   |
| 数据    | SQLite；可选 Chroma 向量检索                                     |
| 测试    | Pytest、Vitest、Playwright、GitHub Actions                       |

## 开源协议

本项目采用 [MIT License](LICENSE)。
