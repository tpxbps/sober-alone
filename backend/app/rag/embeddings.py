"""Versioned embedding contract shared by query and ingest."""

import math

from app.core.config import settings
from app.core.inference import gateway_client, gateway_url

DIMENSIONS = 1024
MODEL = "qwen3.7-text-embedding"


def collection_name(script_id: str) -> str:
    # Audio revisions identify a whole script; vector revisions are validated
    # against each character's exact text. Keep one current gateway collection
    # per script so existing versioned audio namespaces can use rebuilt vectors.
    if settings.INFERENCE_BACKEND == "tokendance":
        script_id = script_id.split("__", 1)[0]
    return f"script_{script_id.replace('-', '_')}"


def profile() -> str:
    return (
        f"tokendance:{MODEL}:{DIMENSIONS}:v1" if settings.INFERENCE_BACKEND == "tokendance" else ""
    )


def validate_collection(collection) -> None:
    if profile() and (collection.metadata or {}).get("embedding_profile") != profile():
        raise ValueError("Embedding index profile mismatch; rebuild before switching models")


def embed(texts: list[str]) -> list[list[float]]:
    vectors = []
    with gateway_client(timeout=90) as client:
        for start in range(0, len(texts), 10):
            batch = texts[start : start + 10]
            response = client.post(
                gateway_url("v1/embeddings"),
                json={
                    "model": MODEL,
                    "input": batch,
                    "dimensions": DIMENSIONS,
                    "encoding_format": "float",
                },
            )
            response.raise_for_status()
            items = sorted(response.json()["data"], key=lambda item: item["index"])
            if [item["index"] for item in items] != list(range(len(batch))):
                raise ValueError("Embedding response has missing or duplicate indices")
            for item in items:
                vector = item["embedding"]
                if len(vector) != DIMENSIONS or not all(math.isfinite(x) for x in vector):
                    raise ValueError("Invalid embedding dimensions or values")
                vectors.append(vector)
    return vectors
