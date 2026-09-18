# 线索引用与阶段演出

发言支持 `[c01]`（点名线索）和 `[推理文字][c01,c02]`（给推理附证据）。标准分隔符是英文逗号；解析兼容中文逗号、顿号、分号及空白，ID 不区分大小写，按首次出现顺序去重。旧 `clue-xxxxxxxxxxxx` ID 继续有效，`[c01][c02]` 是两个直接引用。方括号和反斜杠在推理文字中使用反斜杠转义。

引用权限由该条发言持久化的 `clue_refs` 决定。后来公开的线索不会激活旧消息。AI 的未知 ID 被移除，推理文字保留；真人混入无效 ID 的引用组保留原文。普通 Markdown 链接、转义和代码块不参与引用转换，旧版单独用反引号包裹的 ID 和 `#clue-ref-` 链接保留兼容。共享协议样例在 [fixtures/clue-citations.json](fixtures/clue-citations.json)。

真人通过 `/` 插入线索后自动打开编辑面板。可填写多行推理、增减依据；留空则发送独立线索标签。Esc、失焦或收起保留内容，Ctrl+Enter 应用并返回主编辑器，发送包含面板当前内容。超长修改整体拒绝，避免截断引用结构。阅读时桌面悬停预览、点击固定、Esc 关闭；手机点击打开底部详情，多个证据按顺序纵向展开。

## 媒体与编排

类型定义见 [backend/app/game/clue_media.py](backend/app/game/clue_media.py) 和 [frontend/src/types/cluePresentation.ts](frontend/src/types/cluePresentation.ts)。可选字段都保存在现有 `clue_stages` JSON 和对局快照中。

- `items[].media`：`image_url`、`thumbnail_url`、`alt`、归一化的 `focus` 与可选 `mobile_focus`。
- `presentation`：`version: 1`、资源 `revision`、`template`（cinematic/dossier）、标题、可选背景和有序 `shots`。
- 镜头：唯一 `id`、`duration_ms`、`clue_ids`、`title`、`caption`、`emphasis`、`motion` 和 `labels`。运动可选 push、pan、split、reveal、timeline、chain。单镜头 1–15 秒，总时长最多 90 秒；不能引用未来轮次。
- 图片必须使用本地 `/images/` 路径，不接受外部 URL 或可执行配置。正文、金额、时间、药名和关键句由页面准确排版，图片注明为场景示意。
- `source_hash` 绑定对应线索或阶段正文；新资源首次规范化时自动填写。正文变更会将现有资源设为 `needs_review` 并停止自动使用。人工复核或重新生成后，清空旧 `source_hash`、设为 `ready`，再次校验以绑定新正文。不要仅修改状态绕过复核。
- 正文指纹算法不包含图片与演出，因此新增资源不使既有朗读、评分、向量失效。旧对局保留自己的快照和资源路径；不可删除仍被旧对局引用的图片。

图片只预加载当前轮次。后台暂停、减少动态效果、图片失败和无效配置都有降级。演出可暂停或跳至结尾，结束后等待玩家点击“继续推理”。没有演出的剧本沿用原流程。

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

普通 CI 离线运行。真实模型引用语法验收需单独执行，会将输入中已公开的线索发送给配置的模型服务并产生费用：

```bash
uv run python -m scripts.clue_citation_smoke --source ../fixtures/clue-citation-smoke.json --output .local-data/citation-smoke.json
```

默认使用公开虚构样例。私有源材料必须在获得相应数据传输授权后才可用于此命令。模型可能忽略格式提示；脚本将双模式使用情况、未知 ID 和流式一致性分别记录，失败返回非零状态，不能用离线解析测试代替模型遵循率验收。

可选素材视觉验收：设置 `CLUE_PILOT_URL` 为本地预览 URL，运行 `pnpm exec playwright test e2e/clue-pilot.visual.spec.ts --project=flows --workers=1`。未设置时跳过，不影响普通离线 CI。
