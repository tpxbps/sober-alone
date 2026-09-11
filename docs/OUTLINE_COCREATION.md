# 大纲共创

新建创作使用协议 v2：先流式写短开篇，再由用户决定关键剧情方向，最后整理为可编辑的大纲。缺少 `outline_session.protocol_version` 的历史工作流继续使用旧节点，后续阶段仍读取 `outline`。

## 交互

- 每次只问一题，问题包含独立标题、2–4 个选项、推荐选项及各方向的影响。选项与补充输入可以同时提交，也支持只写其他想法。等待回答没有自动超时选择。
- “停止提问”持久化关闭本轮共创的提问，未回答方向由 AI 决定，回退后仍保持关闭。它不会确认大纲或开始初稿。
- “暂停创作”先保存控制状态，再取消并等待当前任务退出；完整分段保留，未完成草稿只作展示，继续时重新生成这一段。
- 回答旁的“从这里修改”会提示后续重写范围，以该决策前的检查点创建新版本。历史版本只读，不进入新版本的模型上下文。
- 完整大纲停在审阅，可全文编辑、重新整理，或确认进入初稿。两次自动修订后检查仍有问题时，明确显示“需修订”。
- 共创对话与当前大纲可切换；向上阅读时不抢滚动，提供“回到最新”。
- 创意阶段的小助手默认展开；开始创作后收起到右上角，桌面右侧浮层、窄屏抽屉继续使用同一个聊天组件，会话与输入不会因折叠丢失。助手聊天不会自动成为大纲决策。

## 图与模型边界

`generate_outline → outline_director → outline_wait → generate_outline` 构成共创循环。
调度也可以直接续写或进入 `outline_finalize → outline_check → review_outline`。
检查失败可以回到整理节点，最多自动修订两次。

- 写作节点直接 `astream` Markdown；调度和检查分别使用 Pydantic 结构化输出，不把 JSON 或内部推理混入正文。
- `outline_wait` 只处理控制与 `interrupt`，不调用模型。恢复回答不会重复此前已提交的写作节点。
- 每次调用重新组装原始创意、参数、大纲自定义提示词、有效大纲、有效决策及未决事项。用户原话保留，AI 决策单独标记；助手聊天、被弃用版本、未选中方向不混入上下文。
- 最多 5 问；关闭提问或达到上限后最多再写 4 段，并以 10 个总分段作为额外兜底。
- 完成检查结合模型一致性检查与角色数、线索轮数、结局模式、正文依据校验。依据允许 Markdown 加粗等格式差异，但不接受不存在的原文。
- 使用现有 `SCRIPT_EDITOR_MODEL` 配置。首段及本次共创调用关闭思考模式。
- 结构化结果最多修复一次，仍失败就展示可重试错误，不渲染损坏问题卡。明确的单个 `recommended: true` 可规范为推荐选项 ID；不会猜测推荐方向。

## API、持久化与重连

`POST /api/v1/script-editor/{thread_id}/outline/actions` 接受：

```json
{
  "action": "answer",
  "request_id": "client-generated-unique-id",
  "expected_revision": 1,
  "question_id": "current-question-id",
  "option_id": "chosen-option-id",
  "other_text": "可选的补充说明"
}
```

其他 action：`pause`、`continue`、`stop_questions`、`rewrite`、`retry`。
改写使用对应问题 ID，可附检查点 ID。重复 request_id 返回同一操作；过期版本、旧问题或并发变更返回 409。

迁移 `0010` 为 `editor_workflows` 增加 `outline_control` JSON。完整分段和有效决策进入 SQLite 图检查点，正文草稿最多每 500ms 写入操作进度。操作表继续承担后台任务恢复。

状态响应增加 `outline_progress`。既有 `progress-stream` 增加：
`outline_snapshot`、`outline_delta`、`outline_segment_complete`、`outline_question`、`outline_error`。

快照含操作 ID/创建时间、版本、序号、控制标记和会话；增量另含分段 ID、尝试 ID、Unicode 字符偏移和正文。重连先快照后增量，重复增量丢弃，缺口重新取状态；延迟旧操作快照不能覆盖更新操作。未产生第一个图检查点时，也能查询已受理任务和订阅进度。

恢复依据请求消费记录和问题 ID，不仅比较大阶段名。分段提交前崩溃可能重新调用模型，新的尝试替换草稿。暂停任务不会被服务启动自动继续。共创改写与阶段回退串行处理；后续阶段回到已完成大纲时生成新版本并保留停止提问控制。

这些控制沿用项目的本地、单进程后台任务范围，不构成跨服务实例的分布式锁。

## 人物展示

详情/选角弹窗保留原头像，hover、键盘聚焦或查看按钮可打开原图预览。游戏人物浮层为左侧大图、右侧简介及发言信息，优先使用 `portrait_url`，回退到 `avatar_url`，缺图显示占位。图片使用 `object-contain`，Portal 避免被滚动容器裁切，宽高受视口可用空间限制。手机有显式查看入口；原选角和引用角色功能保留。大厅列表未增加头像行。

## 本地验证

```powershell
# 后端（在 backend 目录）
uv run ruff check app migrations tests scripts
uv run ruff format --check app migrations tests scripts
uv run pytest -q --disable-socket --allow-hosts=127.0.0.1,localhost

# 前端（在 frontend 目录）
pnpm lint
pnpm test
pnpm build
$env:PLAYWRIGHT_PORT = "4177"
pnpm test:e2e
```

开发服务支持独立代理，例如：
```powershell
$env:VITE_PROXY_TARGET = "http://127.0.0.1:8017"
pnpm dev --host 127.0.0.1 --port 5177 --strictPort
```

普通测试使用测试替身与临时 SQLite，不新增产品 mock 模式。真实模型延迟和大纲质量应单独记录，不能用自动化测试通过代替人工剧情审阅或上线验收。
