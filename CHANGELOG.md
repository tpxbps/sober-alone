# Changelog

## 0.1.0 - Unreleased

### Added

- Local-first SQLite/Alembic 数据模型、幂等初始化与旧数据库迁入命令。
- 原创纯文本样例 `雾港回声`、healthz 与 capability API。
- DeepSeek-only 回退、角色级上下文隔离、动态 RAG 工具注册。
- 可选资产 `skipped/failed` 状态、AI 标识、供应商图片水印。
- 后端关键测试、Vitest、Playwright 端到端测试和双平台 CI。

### Changed

- 默认运行数据迁入 `backend/.local-data/`，后端示例绑定 `127.0.0.1`。
- 剧本删除改为本地单用户语义，不再暴露或接受 `owner_uuid`。
- 游戏游标可在进程重启后恢复；前端异步操作支持取消与 stale-session 防护。

### Removed

- 私有 `.env`、比赛数据库、Chroma、旧剧本、生成音视频/图片、BGM、click 音效和内部 `.claude` 文档。

### Live verification status

- DeepSeek：已验证普通调用、结构化输出、工具调用、一次 AI SSE 发言以及 reaction 落库。
- StepFun：已验证摘要与最短 TTS，音频只在内存检查，未写入仓库。
- 智谱、豆包、MiMo、千问：0.1.0 普通门禁仅使用测试替身，尚未做 live 验证。
- 用户使用仅 DeepSeek Key 完成整局 `雾港回声` 与一次纯文本创作后，才可公开发布。
