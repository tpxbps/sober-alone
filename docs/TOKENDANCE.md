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

`SCRIPT_EDITOR_MODEL` selects the model for writing, conversion and content review.
Optionally set `SCRIPT_REVIEW_MODEL` to use a separate model for review and safety
checks; it defaults to the creator model and uses the same operation's credential.
Long-form draft requests have a 240-second timeout, separate from gameplay.
For a confirmed provider outage, `DISABLED_LLM_MODELS` accepts comma-separated
model IDs (including legacy aliases). Disabled models are excluded from selection
and health probes, and the server rejects direct calls to them. Clear the setting
after verifying recovery; no model or billing credential is silently substituted.
