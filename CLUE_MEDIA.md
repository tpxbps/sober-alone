# 线索引用与阶段演出

发言支持 `[c01]`（点名线索）和 `[推理文字][c01,c02]`（给推理附证据）。标准分隔符是英文逗号；解析兼容中文逗号、顿号、分号及空白，ID 不区分大小写，按首次出现顺序去重。旧 `clue-xxxxxxxxxxxx` ID 继续有效，`[c01][c02]` 是两个直接引用。方括号和反斜杠在推理文字中使用反斜杠转义。

引用权限由该条发言持久化的 `clue_refs` 决定。后来公开的线索不会激活旧消息。AI 的未知 ID 被移除，推理文字保留；真人混入无效 ID 的引用组保留原文。普通 Markdown 链接、转义和代码块不参与引用转换，旧版单独用反引号包裹的 ID 和 `#clue-ref-` 链接保留兼容。共享协议样例在 [fixtures/clue-citations.json](fixtures/clue-citations.json)。

若模型漏写推理括号而输出 `[c01,c02]`，宿主按两条独立标签降级，并继续过滤未知 ID；不会猜测并改写前文的引用范围。这是兼容容错，标准输出仍要求两种完整语法，模型验收仍将裸 ID 组记为格式失败。

真人通过 `/` 插入线索后自动打开编辑面板。可填写多行推理、增减依据；留空则发送独立线索标签。Esc、失焦或收起保留内容，Ctrl+Enter 应用并返回主编辑器，发送包含面板当前内容。超长修改整体拒绝，避免截断引用结构。阅读时桌面悬停预览、点击固定、Esc 关闭；手机点击打开底部详情，多个证据按顺序纵向展开。详情使用 164px 高的横幅图，下面依次排布所属轮次、标题与正文；桌面浮层宽度最高 28rem，长内容统一滚动。图片失败仍保留完整文字。图片旁不叠加说明标签。

## 媒体与编排

类型定义见 [backend/app/game/clue_media.py](backend/app/game/clue_media.py) 和 [frontend/src/types/cluePresentation.ts](frontend/src/types/cluePresentation.ts)。可选字段都保存在现有 `clue_stages` JSON 和对局快照中。

- `items[].media`：`image_url`、`thumbnail_url`、`alt`、归一化的 `focus` 与可选 `mobile_focus`。
- `presentation`：`version: 1 | 2`、资源 `revision`、`template`（cinematic/dossier）、标题、可选背景和有序 `shots`。v1 保留旧分镜；v2 使用连续空间中的物证编排。
- 镜头：唯一 `id`、`duration_ms`、`clue_ids`、`title`、`caption`、`emphasis`、`motion` 和 `labels`。运动可选 push、pan、split、reveal、timeline、chain。单镜头 1–15 秒，总时长最多 90 秒；不能引用未来轮次。
- 图片必须使用本地 `/images/` 路径，不接受外部 URL 或可执行配置。正文、金额、时间、药名和关键句由页面准确排版。生成素材不能增添正文没有的证据，图片 alt 用于描述内容。
- `source_hash` 绑定对应线索或阶段正文；新资源首次规范化时自动填写。正文变更会将现有资源设为 `needs_review` 并停止自动使用。人工复核或重新生成后，清空旧 `source_hash`、设为 `ready`，再次校验以绑定新正文。不要仅修改状态绕过复核。
- 正文指纹算法不包含图片与演出，因此新增资源不使既有朗读、评分、向量失效。旧对局保留自己的快照和资源路径；不可删除仍被旧对局引用的图片。

图片只预加载当前轮次。后台暂停、减少动态效果、图片失败和无效配置都有降级。演出可暂停或跳至结尾，结束后等待玩家点击“继续推理”。没有演出的剧本沿用原流程。

v2 将每个镜头里的线索按顺序分配出现时间，组合宽景、偏轴近景与特写裁切。照片内部持续移动，遮幅逐渐打开，焦点由模糊转清晰；前后照片短暂交叠，再退至暗处。cinematic 采用横向显影与冷色光影，dossier 采用纵向揭页及轻微平面透视。结尾所有照片汇聚至中心，保留确认后开始推理的流程。图片、背景、文字、遮幅和焦点统一由可暂停时钟驱动；没有播放进度条、装饰轨迹、图片编号或脚注。手机有独立画幅与焦点。v2 的 `shots` 决定顺序、时长和短标题，`motion/labels/emphasis` 仅供 v1 使用。建议 v2 使用简短氛围文字，将详细证据留在结束页，不要求观众在播放期间阅读正文。

视觉取法参考 [True Detective 的主创访谈](https://www.artofthetitle.com/title/true-detective/) 中对照片内部镜头移动、焦点与叠加层的说明，以及 [The Night Manager 的片头分析](https://www.artofthetitle.com/title/the-night-manager/) 对精确物件运动的讨论。这里只借鉴摄影编排方法，使用项目自己的素材与 CSS/React 时间轴，不复制原片画面，也不对线索物件做会改变其含义的形变。

服务端迁移 `0013_clue_presentation` 新增可空等待状态。公开线索、记录公告和进入等待状态在同一事务完成，等待期间禁止 AI、真人发言及再次推进。确认接口：

```http
POST /api/v1/game/{session_id}/clue-presentation/ack
Content-Type: application/json

{"presentation_id": "本轮状态返回的演出 ID"}
```

相同演出重复确认幂等，过期 ID 不能确认新轮次。刷新恢复未确认演出，多标签页轮询同步确认状态；确认失败可重试。此能力沿用项目本地单用户、单进程边界。

## 资源包校验、导入与预览

私有剧本与生成图片放在忽略目录，例如 `backend/.local-data/clue-pilot/`；不要提交到公共仓库。资源包结构：

```text
package/
  manifest.json
  images/scripts/<script-id>/clues/<content-hash>.webp
  originals/                 # 原始图片，供归档
  prompts.json               # 提示词、事实边界与修订提示词
  preview.json               # title + clue_stages
```

manifest 包含 `version: 1`、`script_id`、现有 `content_fingerprint`、完整 `clue_stages`，以及 `files: [{path, sha256}]`。文件清单中的路径以 `images/` 开头。每条配置的图片必须在清单中，每个阶段的演出必须覆盖本阶段全部线索。源 JSON 是现有剧本内容加 `script_id`。

在 backend 目录运行：

```bash
uv run python -m scripts.clue_media validate --source .local-data/clue-pilot/source.json --package .local-data/clue-pilot/package
uv run python -m scripts.clue_media import --source .local-data/clue-pilot/source.json --package .local-data/clue-pilot/package --images-root .local-data/images --database .local-data/game_data.db
```

导入是显式维护操作：核对目标数据库正文指纹，先备份 SQLite，校验资源摘要，拒绝覆盖不同内容的同名文件，再更新剧本的媒体字段；不修改正文或历史对局。发布前保留资源包及 SHA-256，资源包与代码分别发布，保留旧资源以支持历史对局。

启动常规后端和前端后访问 `/clue-preview.html`，选择含 `clue_stages` 的 JSON 文件即可本地预览。也可用 `?src=/images/scripts/<script-id>/clues/preview.json`；图片需要位于后端图片目录。这是只读素材工作台，不创建游戏，也不调用模型。

普通 CI 离线运行。真实模型引用语法验收需单独执行，会将验收样例发送给配置的模型服务并产生费用：

```bash
uv run python -m scripts.clue_citation_eval --models deepseek-flash qwen3.8-flash glm-5.3-flash --output .local-data/citation-eval.json
```

默认使用 [公开虚构多场景样例](fixtures/clue-citation-eval.json)。私有源材料必须在获得相应数据传输授权后才可用于此命令。通过 `--backend`、`--env-file` 和 `--gateway-key-env` 选择现有推理配置，凭证仅从环境加载，不写入结果。模型可能忽略格式提示；脚本将双模式使用情况、未知 ID 和流式一致性分别记录，失败返回非零状态，不能用离线解析测试代替模型遵循率验收。

验收使用实际 `create_game_model(..., "speech")` 参数（当前 temperature=0.8）、角色 system prompt 及每次调用的 StagePolicy 注入；覆盖明确双模式要求、自然追问和带错误引用的旧历史。每个普通模型默认 3 次，高阶模型仅抽查明确双模式场景 1 次；`--repeats 2` 只增加普通模型重复。最多 40 次请求、并发 2、单次超时 125 秒，无自动重试或模型回退。结果记录原始输出、采样参数、token 用量、提示词摘要及流式结果。这是语法及上下文遵循测试，不执行完整 Agent 工具循环，也不评判推理结论是否正确。旧版 `clue_citation_smoke` 的 temperature=0.7 是脚本参数，不能当作实际游戏调用温度。

本轮有界抽测及失败分析见 [CLUE_CITATION_EVALUATION.md](CLUE_CITATION_EVALUATION.md)。

可选素材视觉验收：设置 `CLUE_PILOT_URL` 为本地预览 URL，运行 `pnpm exec playwright test e2e/clue-pilot.visual.spec.ts --project=flows --workers=1`。未设置时跳过，不影响普通离线 CI。
