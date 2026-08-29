"""Single source of truth for selectable chat models."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime

from app.core.config import LOCAL_DATA_DIR


@dataclass(frozen=True, slots=True)
class ModelSpec:
    id: str
    name: str
    provider: str
    provider_name: str
    disable_thinking_extra: str = ""


MODEL_SPECS = (
    ModelSpec("deepseek-v4-flash", "deepseek-v4-flash", "deepseek", "DeepSeek"),
    ModelSpec("step-3.5-flash", "step-3.5-flash", "stepfun", "StepFun"),
    ModelSpec(
        "qwen3.8-flash",
        "qwen3.8-flash",
        "alibaba",
        "Qwen",
        disable_thinking_extra="qwen",
    ),
    ModelSpec(
        "doubao-seed-2-0-mini-260215",
        "doubao-seed-2.0-mini",
        "bytedance",
        "Doubao",
    ),
    ModelSpec("mimo-v2.5", "mimo-v2.5", "mimo", "Xiaomi MiMo"),
    ModelSpec("hy3", "hy3", "hunyuan", "Tencent Hunyuan"),
    ModelSpec("glm-5.3-flash", "glm-5.3-flash", "zhipuai", "Zhipu GLM"),
)
MODEL_BY_ID = {spec.id: spec for spec in MODEL_SPECS}
DEFAULT_MODELS = {
    "deepseek": "deepseek-v4-flash",
    "stepfun": "step-3.5-flash",
    "alibaba": "qwen3.8-flash",
    "bytedance": "doubao-seed-2-0-mini-260215",
    "mimo": "mimo-v2.5",
    "hunyuan": "hy3",
    "zhipuai": "glm-5.3-flash",
}
PROBE_FILE = LOCAL_DATA_DIR / "model-probes.json"


def get_model_spec(model_id: str) -> ModelSpec:
    try:
        return MODEL_BY_ID[model_id.lower()]
    except KeyError as exc:
        raise ValueError(
            f"不支持的模型: {model_id}。支持的模型: {', '.join(sorted(MODEL_BY_ID))}"
        ) from exc


def public_model_spec(spec: ModelSpec) -> dict:
    return asdict(spec)


def load_probe_results() -> dict[str, dict]:
    try:
        data = json.loads(PROBE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_probe_result(model_id: str, *, ok: bool, error: str = "") -> None:
    PROBE_FILE.parent.mkdir(parents=True, exist_ok=True)
    results = load_probe_results()
    results[model_id] = {
        "ok": ok,
        "error": error[:500],
        "checked_at": datetime.now().isoformat(),
    }
    temporary = PROBE_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(PROBE_FILE)
