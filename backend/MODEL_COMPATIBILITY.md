# Gateway game model profiles

TokenDance mode adds opt-in frontier models. Direct mode retains the original
provider configuration. Frontier models are excluded from health checks and
automatic role assignment, including when ordinary models fail their probes.

| Gateway ID | Game reasoning | Reaction format |
| --- | --- | --- |
| kimi-k3 | reasoning_effort=low; omit sampling overrides | JSON schema |
| qwen3.8-max-0902 | reasoning_effort=low | JSON schema |
| glm-5.3 | reasoning_effort=low | JSON object |
| deepseek-v4-pro-0813 | thinking enabled, reasoning_effort=low | JSON object |
| ling-3.0-flash | thinking.type=disabled | JSON schema |

These are fixed game profiles, not maximum-effort benchmark settings. Qwen low
maps to a 4096-token thinking budget. Some Kimi routes reserve 8192 thinking
tokens even at low, so Kimi's total output ceiling is 12288; the other frontier
models use 8192. A ceiling is not a target output length. Provider-side effort
mapping can vary: GLM documentation also describes low-to-high compatibility
mapping. The requested low profile was accepted by the tested gateway route.

ReasoningChatOpenAI preserves reasoning_content for streaming and non-streaming
tool turns, without exposing it as speech. A fresh credential is still resolved
at each dispatch. Funding scopes can restrict allowed gateway model IDs.

In gateway mode, existing Step games resolve to Ling; new selections and the
summary client no longer use Step. Summaries use non-thinking Qwen Flash.
Direct-mode Step support is retained. Ling's native chat_template_kwargs switch
did not suppress thinking on the tested gateway; thinking.type=disabled did.

Small live compatibility samples verified tool invocation, continuation with
reasoning history, public-clue citation and structured reactions. These checks
are not a ranking of role-play quality or a latency/cost guarantee. DeepSeek
Pro's function output produced an invalid reaction sample; JSON mode passed.
Run normal CI offline; paid compatibility audits must be explicitly requested.

Sources, checked 2026-09-16:

- [TokenDance model catalog](https://tokendance.space/gateway/v1/models)
- [TokenDance Kimi guide](https://tokendance.space/docs/kimi-thinking-models.md)
- [Kimi K3 model card](https://github.com/MoonshotAI/Kimi-K3)
- [Qwen OpenAI parameters](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)
- [GLM thinking parameters](https://docs.bigmodel.cn/cn/guide/capabilities/thinking)
- [DeepSeek thinking mode](https://api-docs.deepseek.com/guides/thinking_mode/)
- [Ling model card](https://huggingface.co/inclusionAI/Ling-3.0-flash)

DeepSeek's official API began redirecting its unversioned V4 Pro alias to Flash
on September 14. This adapter uses the requested, versioned TokenDance ID and
does not enable official fallback for frontier user-funded games. A gateway ID
alone cannot independently attest the weights deployed by its upstream route.
