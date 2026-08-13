# SBOM

仓库使用 `scripts/generate_sbom.py` 从 `backend/uv.lock` 和 `frontend/pnpm-lock.yaml` 生成 SPDX 2.3 JSON：

```bash
uv run --project backend python scripts/generate_sbom.py
```

输出为 `sbom.spdx.json`。GitHub Actions 会重新生成并上传构建产物；发布候选必须确保生成后 Git 状态无意外变化。

SBOM 是组件与版本清单，不是许可证意见。许可证摘要见 `THIRD_PARTY_NOTICES.md`，实际义务以各上游许可证为准。
