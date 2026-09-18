"""Per-output durable conversion cache, including dependencies inside a role task."""

import asyncio
import hashlib
import json
import time


class ConversionCache:
    def __init__(self, fingerprint, results, runtime=None):
        self.fingerprint, self.results, self.runtime = fingerprint, results, runtime
        self.pending = {}
        self.metrics = []

    async def get(self, key, schema, material, generate):
        digest = hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        entry = self.results.get(key)
        if isinstance(entry, dict) and entry.get("input_hash") == digest:
            result = schema.model_validate(entry["value"])
            self.metrics.append({"task": key, "cache_hit": True})
            return result
        identity = (key, digest)
        if identity in self.pending:
            return await self.pending[identity]

        async def run():
            started = time.monotonic()
            try:
                result = await generate()
                self.results[key] = {"input_hash": digest, "value": result.model_dump()}
                if self.runtime:
                    self.runtime.convert_cache = {
                        "fingerprint": self.fingerprint,
                        "results": self.results,
                    }
                    self.runtime.queue_progress(
                        "convert_cache", json.loads(json.dumps(self.runtime.convert_cache))
                    )
                    await self.runtime.drain_progress()
                self.metrics.append(
                    {
                        "task": key,
                        "cache_hit": False,
                        "seconds": round(time.monotonic() - started, 3),
                    }
                )
                return result
            except Exception as error:
                self.metrics.append(
                    {
                        "task": key,
                        "error": type(error).__name__,
                        "seconds": round(time.monotonic() - started, 3),
                    }
                )
                raise

        self.pending[identity] = asyncio.create_task(run())
        return await self.pending[identity]


async def cached_output(state, key, schema, material, generate):
    cache = state.get("_conversion_outputs")
    return await cache.get(key, schema, material, generate) if cache else await generate()
