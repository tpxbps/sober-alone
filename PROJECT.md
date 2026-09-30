# 项目约定

独醒面向本地单用户、单进程运行。README 负责安装使用，本文件集中保留架构、接口与开发约定。

## 核心链路

游戏：大厅 → 选择角色 → 自我介绍 → 每轮线索分析与自由讨论 → 总结 → 投票 → 复盘。
创作：创意 → 大纲 → 初稿 → 评审与人工确认 → 终稿 → 转换 → 校验与保存 → 可选资产。

- `backend/app/game/flow_controller.py` 管理阶段与发言队列，`services/game_service.py` 提供 API 外观。
- `agents/agent_player.py` 编排独立角色的发言、工具、心理状态与反应。角色只接收自己的个人稿、已发生的讨论及当前公开材料。
- 对局保存不可变剧本快照。轮次概述与线索条目共同进入发言、反应、总结和投票；恢复对局从快照和阶段重建，不读取后续材料或终局真相。
- `script_editor/` 使用 LangGraph 编排创作；后台 operation 持久化并支持刷新恢复、检查点与分叉。重启可认领未完成任务，不承诺跨进程协调。
- `frontend/src/stores/` 协调界面状态；`lib/` 管理 API、SSE 与适配。发言完整结束后落库、分析反应并对账；异步结果写入前检查 session / operation identity。
- 业务数据使用 SQLAlchemy / Alembic；检查点另存 SQLite。运行数据、向量及生成媒体位于忽略的 `backend/.local-data/`。内存回收不删除历史对局。
- `app/seed.py` 仅向空库导入 `app/data/sample.json`，重复初始化不覆盖已有剧本或对局。

## 推理与能力边界

默认游戏原则集中在 `agents/agent_prompts.py`，发言与反应共用。根据本局机制建立行为与死亡的因果关系，区分来源与推测，及时修正判断；角色保持秘密、交换信息和策略取舍须遵守知情边界。特殊规则由剧本明确设定，通用提示不硬编码某个案件答案。

模型注册在 `core/model_registry.py`，参数与结构化反应绑定在 `agents/game_model_paths.py`。保留旧对局的模型恢复映射。`/api/v1/system/capabilities` 返回配置能力，`/api/v1/system/model-health` 检查首字及反应耗时；健康结果影响自动分配，不代替行为评测。

默认直连供应商。可在私有环境设置 `INFERENCE_BACKEND=tokendance` 与 `TOKENDANCE_API_KEY` 使用网关。需要凭据隔离的宿主设置 `TOKENDANCE_REQUIRE_SCOPE=true`，在整个异步任务与流式响应中提供 `InferenceScope`；凭据在派发时解析，不进入检查点或模型缓存。恢复错误必须停止当前操作，不能切换付费来源。`DISABLED_LLM_MODELS` 可暂停指定模型。

创作默认使用 DeepSeek，`SCRIPT_EDITOR_INFERENCE_BACKEND=inherit` 跟随当前来源；显式 `deepseek_official` 仅调整创作文本路由。没有向量配置时不注册 RAG，直接注入本人的完整稿；缺少图片或语音配置时仍可纯文本运行。网关向量与旧直连向量不兼容，切换前用 `app.services.tokendance_migration` 检查、构建独立索引并保留原索引。

## 线索引用与可选媒体

`[c01]` 点名线索，`[推理文字][c01,c02]` 关联证据；旧 ID 与历史语法保留兼容。权限以该条消息落库时的 `clue_refs` 为准，后来公开的线索不激活旧引用。无 ID 的轮次概述自然说明来源，不伪造 ID。共享协议夹具由前后端测试共同消费。

媒体类型见 `game/clue_media.py`。图片使用本地 `/images/` 路径；资源 `source_hash` 绑定正文，正文改变后须重新审核。演出等待期间禁止发言和推进；`POST /api/v1/game/{session_id}/clue-presentation/ack` 携带当前 `presentation_id` 幂等确认。媒体失败可进入完整文字摘要。下一轮预加载只发布图片 URL，不发布未公开正文；图片仍可通过开发者工具查看。

资源包 manifest 包含版本、剧本 ID、正文指纹、完整 `clue_stages` 与 `files: [{path, sha256}]`。在 backend 目录用以下命令校验、备份后导入；不会改写正文与旧对局。旧资源须保留供历史快照使用。

```bash
uv run python -m scripts.clue_media validate --source .local-data/source.json --package .local-data/package
uv run python -m scripts.clue_media import --source .local-data/source.json --package .local-data/package --images-root .local-data/images --database .local-data/game_data.db
```

启动前后端后访问 `/clue-preview.html` 可只读预览本地 JSON，不创建对局或调用模型。

## 开发与验证

保持 REST/SSE 事件、阶段和 LangGraph state key 兼容。新增内部字段应兼容旧检查点；不得共享其他角色私有经历。修复推理质量应先排查信息链路，再改提示词。

```bash
uv run --project backend ruff check backend/app backend/migrations backend/tests backend/scripts scripts
uv run --project backend ruff format --check backend/app backend/migrations backend/tests backend/scripts scripts
uv run --project backend pytest -q backend/tests --disable-socket --allow-hosts=127.0.0.1,localhost
pnpm --dir frontend lint
pnpm --dir frontend test
pnpm --dir frontend build
pnpm --dir frontend test:e2e
```

CI 不访问外部模型。迁移验收在隔离库连续执行两次 `python -m app.cli init`。浏览器路由夹具验证前端流程，真实模型与完整游戏另行验收，不混淆两种结论。

可复现付费工具位于 `backend/scripts/`：`clue_citation_eval` 检验引用协议，`gameplay_eval` 采集带人工语义判分标准的合成场景，`model_game_audit` 验证完整生命周期，`model_health_diagnostic` 检查请求耗时。通过各自 `--help` 查看参数。私有材料需获授权；原始结果只写忽略目录，真实调用须限制预算，不因失败自动更换模型或付费来源。

## 公开树约定

仅保留工程实现、测试与其必需夹具、依赖锁、迁移、CI、产品资源及许可证。说明仅允许 README、PROJECT、LICENSE 与明确列出的第三方许可证。过程总结、上下文记忆、截图录屏、账单、私有剧本、运维资料和生成资源放入本地忽略目录。新增第三方许可证须在检查器中明确登记，不扩展任意文档豁免。

在本仓库安装钩子（不修改全局配置）：

```bash
git config --local core.hooksPath .githooks
python scripts/check_public_tree.py --staged
```

`pre-commit` 检查暂存树，`pre-push` 检查每个待推送提交及最终树，CI 再次检查。检查器直接读取 Git 对象，强制添加的忽略文件也会被拦截；它报告路径与整改方式，不自动删除文件。密钥扫描同时由 CI 的 Gitleaks 完整历史检查补充。本轮治理规则不要求重写已有历史。

## 8. 聊天回合与恢复

`game_turns` 保存稳定回合身份、正文快照、尝试编号、事件序号、生成完成标记和输入 checkpoint。
状态为 `queued → speaking → committing → reacting → completed`；失败和账户暂停保留正文。
单进程后台执行器拥有任务，浏览器仅订阅；离线后本轮继续，下一轮由在线客户端发起。
发言、次数扣减和待执行反应原子提交；反应完成与下一位选择也原子提交。
状态接口读取已提交数据，不读取运行中控制器的临时对象或等待模型反应。

原发言 POST 增加 `request_id` 和 `expected_revision`。重复命令返回已有操作，过期命令返回
`resync`。状态增加 `active_turn`、`state_revision`；历史记录增加可空的 `turn_id`。
`GET /api/v1/game/{session}/turns/{turn}/events?after_seq=N` 首先发送完整快照，再发送新序号的
快照。`speech_done` 表示文本生成结束，`speech_recorded` 携带已提交记录，`done` 携带最终
一致状态。慢订阅者可能跳过中间状态，因此每帧都携带完整 turn。每 10 秒心跳，禁止代理缓冲。
`POST /api/v1/game/{session}/turns/{turn}/retry` 使用 `expected_attempt` 防止重复重试。

前端将思考占位、流式正文和历史记录放在同一消息列表，使用不变的 `uiKey`；记录确认、
反应结束及历史同步不重新挂载气泡。EOF 不代表业务完成：保留内容并查询、订阅原回合。
暂停、草稿与排队真人发言按会话保存在当前标签页，排队真人优先于下一位 AI。

服务重启后，已生成完整正文继续提交，已提交发言只补做剩余反应；未完成生成保留草稿并
提供重试。重试绑定本轮输入 checkpoint，新尝试不拼接旧尝试。发言执行器与每个反应调用
最多三次尝试，SDK 和图中间件不叠加重试。格式偏差按规则降级；供应商或持久化故障暂停
当前操作，不再插入错误发言并扣次。放弃或结束对局会取消任务并禁止恢复。

增量迁移为 `0015_game_turns`，前后端须配套更新。关键测试为 `test_game_speech.py`、
`gameTurnCoordinator.test.ts` 和 `chat-continuity.spec.ts`；浏览器测试使用真实分段 HTTP SSE，
逐帧检查气泡、头像、Markdown 容器与文字连续性。显式付费验收脚本为
`backend/scripts/verify_turns_live.py`，使用隔离样例库且只输出身份、时间、长度和记录编号。
