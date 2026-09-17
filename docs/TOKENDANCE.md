# Optional TokenDance gateway

The local single-user application keeps its direct provider mode by default.
To use TokenDance, set `INFERENCE_BACKEND=tokendance` and `TOKENDANCE_API_KEY`
in the private backend environment. `TOKENDANCE_APP_URL` is an optional stable
application attribution URL. Never put credentials in source or browser code.

Chat aliases are mapped independently of the model brand. Images use the Ark
endpoint with Seedream 5.0 Lite and `watermark=false`; static narration keeps MiMo;
game speech uses MiniMax 2.8 Turbo HTTP SSE. Browser playback buffers the complete
MP3 when MediaSource MP3 is unavailable.

Embedding queries and ingestion use Qwen3.7, 1024 dimensions. Old vectors are not
compatible despite having the same dimensions. After applying database migrations,
use `python -m app.services.tokendance_migration --database DATABASE --output NEW_INDEX`
to inspect the scope, then add `--build` to build and verify a separate index.
Review its manifest before running `--apply-voices`. Set `CHROMA_PERSIST_DIR` to
the new index only after verification. Keep the old index and database backup
for rollback. Source changes require rebuilding before applying the manifest.

Hosts that manage multiple credentials must set `TOKENDANCE_REQUIRE_SCOPE=true`
and supply an `InferenceScope` around the complete operation, including streaming
responses and background work. Scope resolvers must validate ownership and current
credential validity. HTTP authentication resolves the key at dispatch; no raw key
belongs in graph state, checkpoints, model caches, or metrics. This extension point
does not itself add public-host authentication or multi-user billing to the local app.

`TokenDance-Recovery-Action` becomes `InferenceRecoveryError`; hosts must display
recovery and stop the affected operation rather than falling back to another payer.
Ordinary CI uses offline protocol fixtures. Real provider verification is separate.

Workshop writing, conversion, review and its assistant all use `deepseek-flash`.
The old `SCRIPT_EDITOR_MODEL` / `SCRIPT_REVIEW_MODEL` values are accepted for
configuration compatibility but no longer select workshop models. By default
`SCRIPT_EDITOR_INFERENCE_BACKEND=inherit` follows `INFERENCE_BACKEND` and the
operation credential. An explicit `deepseek_official` override routes only
workshop text to `DEEPSEEK_API_KEY` / `DEEPSEEK_API_BASE_URL`; media and embeddings
keep their existing route. This override is never an automatic fallback.
Long-form draft requests have a 240-second timeout, separate from gameplay.
Structured calls share a limit of four concurrent requests per worker and at
most one corrective retry; truncation splits the fact task instead of repeating
an oversized response. See [workshop validation](SCRIPT_WORKSHOP_STABILITY.md).
For a confirmed provider outage, `DISABLED_LLM_MODELS` accepts comma-separated
model IDs (including legacy aliases). Disabled models are excluded from selection
and health probes, and the server rejects direct calls to them. Clear the setting
after verifying recovery; no model or billing credential is silently substituted.
