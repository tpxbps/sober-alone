# Sober Alone - AI Murder Mystery Game (剧本杀)

## Tech Stack

- **Backend**: Python 3.13 / FastAPI / SQLAlchemy (async aiosqlite) / LangChain + LangGraph
- **Frontend**: React 19 / TypeScript / Zustand / Vite / TailwindCSS / Framer Motion
- **Storage**: SQLite (game state) + ChromaDB (vector embeddings for RAG)
- **LLM**: Multiple providers (deepseek/stepfun/alibaba/bytedance), configurable per-character
- **TTS**: mimo-v2.5-tts (static, script pre-generation) + step-tts-mini (real-time streaming via WebSocket)
- **Image Gen**: doubao-seedream-4-0 (cover images + character avatars)
- **Embedding**: zhipuai embedding-3 (1024 dims, for ChromaDB RAG)

## Directory Structure

```
backend/
  app/
    main.py                # FastAPI entry, CORS, static file mounts (/audio, /images)
    core/
      config.py            # pydantic-settings, API keys/base URLs for 5+ LLM providers
      llm_factory.py       # create_llm() by model name, create_summary_llm()
    api/routes/
      game.py              # Game REST+SSE endpoints (~12), including TTS streaming
      script_editor.py     # Script Editor REST+SSE endpoints (~16), checkpoint history
    services/
      game_service.py      # Game business logic, SSE streaming, session lifecycle (~1100 lines)
      tts_service.py       # Static TTS (mimo) + on-demand TTS (step), WAV/MP3 concat, chunking
      streaming_tts.py     # WebSocket-based streaming TTS session (step-tts-mini)
    game/
      flow_controller.py   # Game stage machine, speech processing, reaction persistence (~900 lines)
      speech_scheduler.py  # Free discussion weighted scoring + round-robin priority
    agents/
      agent_manager.py     # Multi-agent lifecycle, broadcast, global cache by session_id
      agent_player.py      # Dual-agent (main + reaction), tools, streaming, error handling
      state.py             # GameAgentState (LangGraph agent state schema)
      context.py           # ContextVar for passing db_session to tools
      middleware/
        clean_history.py   # SummarizationMiddleware (200k tokens, keeps last 20 messages)
      tools/
        recall_memory.py   # RAG retrieval from ChromaDB (all stages)
        reaction.py        # Update suspicion graph (clue_analysis stage only)
        vote.py            # Submit final vote with per-session async lock (vote stage only)
    script_editor/
      graph.py             # LangGraph StateGraph workflow definition, 13 nodes, 5 conditional edges
      state.py             # ScriptGenState TypedDict, step constants, interrupt steps
      nodes/
        init_node.py       # UUID generation, prompt merging, defaults
        outline.py         # Structured outline generation (deepseek-v4-flash)
        first_draft.py     # Full first draft, regex character extraction
        review.py          # LLM-as-judge review (automatic, no interrupt)
        final_draft.py     # Final draft incorporating AI + human feedback
        convert.py         # Multi-parallel LLM: clues, scenes, metadata, per-character data
        review_nodes.py    # 5 interrupt nodes (LangGraph interrupt() mechanism)
        safety_check.py    # Content safety compliance (Chinese law + core values)
        save.py            # DB persistence + parallel asset generation (vectors/images/TTS)
        utils.py           # LLM creation, retry logic with exponential backoff
      services/
        chroma_ingest.py   # Chunk + embed character scripts into ChromaDB
        image_gen.py       # Cover image (1280x768) + avatars (1024x1024) via doubao-seedream
        tts_gen.py         # Batch TTS for all system messages + character scripts
        progress_bus.py    # Pub/sub SSE progress bus (convert + asset phases)
        chat_service.py    # AI creative assistant chat, 6 workflow-aware tools
      prompts/
        defaults.py        # 5 default prompt templates (outline, first_draft, review, final_draft, convert)
        templates.py       # Template variable formatting (player_count, difficulty, etc.)
    db/
      session.py           # AsyncSessionLocal engine
      models/
        game_session.py    # GameSession + GameStatus/GameStage enums
        player_state.py    # PlayerState: suspicion, perspectives, speech stats, vote tracking
        game_record.py     # GameRecord + RecordType enum
    rag/
      retriever.py         # ChromaDB vector retriever (zhipuai embedding-3, top_k=2)
  data/
    game_data.db           # SQLite (gitignored)
    chroma/                # ChromaDB persistent data (gitignored)
    audio/scripts/         # Pre-generated TTS audio (.wav)
    images/scripts/        # Generated cover images + avatars (.png)
  scripts/
    regen_chroma.py        # Wipe + re-vectorize a specific script
    generate_bgm.py        # BGM generation utility

frontend/src/
  App.tsx                  # Root routing (home/game/editor), session restore
  screens/
    Homepage.tsx           # Script selection grid, character/model config, game creation
    GamePage.tsx           # Main game screen, auto-trigger AI speech, SSE orchestration
    ScriptEditorPage.tsx   # Script editor: timeline, content panel, chat panel
  stores/
    gameStore.ts           # Game state: SSE handling, pendingHumanSpeech, RAF batching
    editorStore.ts         # Editor workflow state, optimistic UI, checkpoint history
    settingsStore.ts       # BGM/TTS settings (persisted to localStorage)
  lib/
    api.ts                 # Axios client + SSE stream parser (processSSEStream async generator)
    audioPlayerManager.ts  # Global singleton: static (HTMLAudioElement) + streaming (MediaSource)
    editorApi.ts           # Script editor API client
    clickSound.ts          # Global delegated click sound on <button>
  types/
    game.ts                # Game types + AI_MODELS constant
    editor.ts              # Editor types, WORKFLOW_PHASES, step mapping
  components/game/
    ChatArea.tsx           # Message list, TTS playback (static/SSE), system audio with seek bar
    ChatInputArea.tsx      # React.memo input component (extracted for perf), multi-line pending
    StreamingBubble.tsx    # Isolated streaming display (direct store subscription, RAF-throttled scroll)
    VotingModal.tsx        # Character selection, vote confirmation, results display, auto-finalize
    CharacterPanel.tsx     # Side panels with speaking indicator, status icons
    DraftNotebook.tsx      # Player notepad (localStorage persisted)
    GameHeader.tsx         # Stage indicator, controls, timer
    StageTransitionOverlay.tsx  # Full-screen animated overlay between stages (Framer Motion)
    ScriptCard.tsx         # Script listing card with difficulty, tags, hover animation
    ScriptDetailModal.tsx  # Script info + character selection + AI model assignment
    PlayerScriptTooltip.tsx # Human player's personal script viewer
  components/script-editor/
    ContentPanel.tsx       # Multi-view content panel (~1877 lines), phase-specific rendering
    ChatPanel.tsx          # AI assistant chat with streaming, model selector, markdown
    HorizontalTimeline.tsx # 6-phase visual timeline with completion status
    WhackAMole.tsx         # Easter egg mini-game during loading states
  components/ui/           # shadcn/ui primitives + custom: Markdown, SpeakerIcon, AudioSpeedButton, DynamicDot
  hooks/
    useBGM.ts              # Stage-based BGM with crossfade, global singleton pattern
```

## Game Flow

### Stage Sequence

```
Script (game_full_process JSON array) defines stage sequence per round
  |
  v
INTRO (sequential, all players introduce themselves)
  |
  v
CLUE_ANALYSIS (sequential) -> FREE_DISCUSSION (emergent scheduling)  [repeat N rounds]
  |
  v
SUMMARY (sequential) -> VOTE (parallel AI + human) -> REVIEW (truth reveal) -> COMPLETED
```

Stage mapping from script `game_full_process`:

- `initial` -> intro
- `advancement` -> clue_analysis then free_discussion (two sub-phases per round)
- `vote` -> summary then vote
- `review` -> review

### Core Loop: `process_speech` (flow_controller.py)

**Execution order (critical — must persist state BEFORE slow operations):**

1. **Clear consumed perspectives** — `_clear_consumed_perspectives(character_id)` resets `player_perspectives` to `{}`
2. **Record speech** — `GameRecord` (SPEECH type) to DB
3. **Update speaker state** — decrement `remaining_speech_count`, reset `wait_rounds`, increment totals
4. **Record in scheduler** + update speech queue + determine next speaker + **PERSIST TO DB** (raw SQL UPDATE)
5. **THEN broadcast reactions** — parallel `react_to_speech()` for all other AI agents (60s timeout each)

This ordering ensures game state survives page refresh or crash during the slow reaction phase.

### Free Discussion Speaker Selection (speech_scheduler.py)

Score: `0.4 * suspected_intensity + 0.3 * active_suspicion + 0.3 * opportunity_cost`

Two-tier priority:

1. Players who haven't spoken this round (`has_spoken_this_round=false`)
2. Players who have — selected by weighted score from top 3 candidates

Human player excluded from AI scheduling; human can speak independently.

### SSE Streaming Protocol

Backend streams events to frontend per-request (no persistent EventSource):

- `thinking` — AI is using tools (RAG recall, reaction update, vote submit)
- `token` — Streaming text chunk from LLM
- `speech_done` — AI speech complete, reactions starting (transitions UI to `isProcessingReactions`)
- `reactions_done` — All reactions processed (human speech stream only)
- `done` — Complete. Includes `next_speaker_id`, `next_speaker_name`, `stage_complete`
- `error` — Error with message

### Pending Human Speech Pattern (free_discussion)

1. Human submits while AI is streaming/processing → stored as `pendingHumanSpeech` (no API call)
2. UI shows "你的发言将在 AI 发言结束后发送" indicator + pending message bubble
3. When AI's `done` event arrives → store auto-sends queued human speech via `humanSpeakStream`
4. After human speech completes → `currentSpeakerId` from backend response

### Error Handling

- **Agent LLM failure**: LangGraph `astream()` silently completes (no exception). Backend detects empty `full_content` and records fallback message: "（系统提示：AI 角色出现未知错误，暂时无法正常发言。）". Reactions are skipped (`skip_reactions=True`).
- **Reaction timeout**: Individual 60s timeout per agent. Failed reactions recorded as `{"error": "..."}` and skipped.
- **AI voting**: Per-agent 90s timeout, overall 120s timeout. Failed votes recorded as abstentions.

### Player Perspectives: Inject-then-Clear

Prevents unbounded prompt growth:

1. **Accumulate**: After each speech, reactions append `main_perspective` to `PlayerState.player_perspectives[speaker_id]` (list)
2. **Inject**: Before agent speaks, `_build_knowledge_context()` reads accumulated perspectives into prompt
3. **Clear**: After speech completes, `_clear_consumed_perspectives()` resets to `{}`
4. Result: Each agent only sees NEW perspectives since last speech. Old perspectives preserved in LangGraph checkpointer history.

## TTS System

### Architecture: Two-Tier TTS

```
Static TTS (Script Pre-generation)          Streaming TTS (Live Gameplay)
    |                                              |
    v                                              v
mimo-v2.5-tts                              step-tts-mini
(HTTP REST, WAV output)                    (WebSocket, MP3 output)
    |                                              |
    v                                              v
Files on disk:                              SSE to frontend:
data/audio/scripts/{id}/                    audio_delta events (base64 MP3)
  system_messages/{stage}.wav
  character_scripts/{char_id}.wav
    |                                              |
    +--------------------+-------------------------+
                         |
                    Frontend audioPlayerManager
                    - Static: HTMLAudioElement.play(url)
                    - Streaming: MediaSource + SourceBuffer (audio/mpeg)
                    - Blob cache after stream end for replay
```

### Static TTS (Script Pre-generation)

**Engine**: mimo-v2.5-tts via HTTP REST (`/v1/chat/completions` format)
**API**: `https://api.xiaomimimo.com/v1`
**Output**: WAV (PCM, 44-byte header)

Voice configuration:

- System messages: "Bingtang" (冰糖) with stage-specific style prompts (suspenseful/solemn/revealing)
- Female characters: "Moli" (茉莉) with "Narrate in character's voice, emotionally immersed"
- Default/male: "Suda" (苏打) with same character-immersed style

Key features:

- Auto-chunking at sentence boundaries (max 4000 chars per chunk)
- WAV concatenation with 300ms silence gaps between chunks
- Idempotent generation: skips if file exists with valid duration
- Duration validation: rejects audio >4x expected or >30s (guards against hallucinated silence)
- Markdown preprocessing: strips all formatting before TTS

### Streaming TTS (Live Gameplay)

**Engine**: step-tts-mini via WebSocket (`wss://api.stepfun.com/v1/realtime/audio`)
**Output**: MP3 (24kHz, sentence mode)

Flow:

1. Frontend calls `POST /game/{session_id}/tts/stream` with `record_id`
2. Backend resolves voice_id from character table (or gender-based defaults: "lengyanyujie" for female, "cixingnansheng" for male)
3. `StreamingTTSSession` connects WebSocket, sends text, flushes, finishes
4. Audio chunks arrive as `tts.response.audio.delta` (base64 MP3)
5. Backend re-emits as SSE `audio_delta` events
6. Frontend `audioPlayerManager.appendChunk()` feeds `SourceBuffer` in `sequence` mode
7. First chunk triggers playback start
8. `endStream(recordId)` caches as Blob URL for replay

### On-demand TTS

**Engine**: step-tts-mini via HTTP REST (`/v1/audio/speech`)
**Output**: MP3
**Use case**: Quick single-shot generation (not currently used in main flow, available via TTSService)

### Frontend Audio Player (audioPlayerManager.ts)

Global singleton managing all audio playback:

- **Static mode**: `play(url)` — creates `HTMLAudioElement`, preloads, plays
- **Streaming mode**: `startStream()` → `appendChunk(base64)` → `endStream(recordId)` — `MediaSource` API
- **Blob cache**: After stream ends, chunks are concatenated into a Blob URL and cached by `recordId` for instant replay
- **State tracking**: `onStateChange(callback)` with RAF-based progress loop
- **Controls**: `togglePause()`, `seekTo(time)`, `setPlaybackRate(rate)`, `stop()`
- Only one audio plays at a time (mutual exclusion between static and streaming)

### TTS Scope in UI

- **`ttsEnabled` toggle** (settingsStore, default false, Beta): Controls AI speech TTS only
  - When disabled: `SpeakerIcon` renders as `disabled` state for AI records
  - When disabled mid-playback: active audio is stopped
  - Does NOT affect pre-generated system message audio (always playable if `audio_url` exists)
- **System audio**: Always available via `SpeakerIcon` on system messages. Includes seek bar, time display, `AudioSpeedButton` (1x/1.5x/2x). Supports pause/resume toggle.
- **AI speech audio**: Three sources checked in order: (1) Blob cache, (2) `record.audio_url`, (3) SSE streaming

## Script Editor Workflow

### Overview

AI-native LangGraph workflow for generating complete murder mystery game content. 13 nodes, 5 conditional edges, 5 human-in-the-loop interrupts.

```
START -> init -> generate_outline -> [REVIEW] <-> generate_outline
  -> generate_first_draft -> [REVIEW] <-> generate_first_draft
  -> review_by_llm (auto) -> generate_final_draft -> [REVIEW] <-> generate_final_draft
  -> convert_to_game_data -> [REVIEW] <-> convert_to_game_data
  -> safety_check -> (pass) -> save_to_database -> generate_assets -> END
               +-- (fail) -> review_game_data
```

`[REVIEW]` = interrupt for human review. User can confirm (advance) or regenerate (loop back).

### Nodes

| Node                   | Purpose                                                             | Model                         | Key Output                                                 |
| ---------------------- | ------------------------------------------------------------------- | ----------------------------- | ---------------------------------------------------------- |
| `init_workflow`        | UUIDs, defaults, merge prompts                                      | —                             | script_id, owner_uuid                                      |
| `generate_outline`     | Structured outline + title                                          | deepseek-v4-flash (temp 0.85) | outline, script_title                                      |
| `review_outline`       | **INTERRUPT**: user reviews outline                                 | —                             | confirm/regenerate                                         |
| `generate_first_draft` | Full draft from outline                                             | deepseek-v4-flash             | first_draft, characters (regex)                            |
| `review_first_draft`   | **INTERRUPT**: user reviews draft                                   | —                             | confirm/regenerate                                         |
| `review_by_llm`        | Auto AI review (5 dimensions)                                       | deepseek-v4-flash             | review_opinion                                             |
| `generate_final_draft` | Draft + AI + human feedback                                         | deepseek-v4-flash             | final_draft                                                |
| `review_final`         | **INTERRUPT**: user reviews with AI opinion                         | —                             | human_review, confirm/regenerate                           |
| `convert_to_game_data` | **Parallel LLM calls**: clues, scenes, metadata, per-character data | deepseek-v4-flash             | game_full_process, game_data_sections, character_voice_ids |
| `review_game_data`     | **INTERRUPT**: user edits all structured data                       | —                             | edited game_data_sections                                  |
| `safety_check`         | Content compliance (Chinese law)                                    | deepseek-v4-flash (temp 0.1)  | safety_passed/rejection_reason                             |
| `save_to_database`     | Persist scripts + characters to SQLite                              | —                             | DB rows                                                    |
| `generate_assets`      | **Parallel**: ChromaDB vectors + images + TTS                       | Multiple                      | cover, avatars, audio files                                |

### convert_to_game_data Details

Runs multiple parallel LLM calls via `asyncio.gather`:

1. **Character Discovery** (if empty): Extracts exactly `player_count` characters from final draft
2. **Game Flow (clues)**: N rounds of clue analysis + free discussion system messages
3. **Game Scenes**: Opening, summary, vote, truth reveal notices, full truth text
4. **Metadata**: Overview (100-200 chars), tags, description
5. **Per-character data** (staggered 0.3s): character_script (first-person 1500-3000 chars), profile, appearance, system_prompt, script_summary, voice_id

Progress tracked per-task, published via SSE `convert_progress` events.

### generate_assets Details

Three parallel phases:

1. **Vectorize**: Chunk + embed character scripts into ChromaDB (zhipuai embedding-3, 500 char chunks, 100 overlap)
2. **Images**: Cover (1280x768) + per-character avatars (1024x1024) via doubao-seedream-4-0
3. **TTS**: All system messages + character scripts via mimo-v2.5-tts (parallel with 200ms stagger)

Progress tracked per-task, published via SSE `asset_progress` events. Failed tasks support individual retry.

### Frontend-Backend Communication

**REST API** (prefix: `/script-editor`):

- `POST /start` — Start workflow (runs to first interrupt)
- `GET /{thread_id}/state` — Current workflow state
- `POST /{thread_id}/resume` — Resume from interrupt (confirm/regenerate)
- `PUT /{thread_id}/prompt/{step}` — Update prompt for a step
- `GET /{thread_id}/progress-stream` — SSE progress stream
- `POST /{thread_id}/fork` — Time-travel from historical checkpoint
- `POST /chat` — AI creative assistant (SSE)

**SSE Events**: `convert_progress`, `asset_progress`, `connected`, heartbeat every 30s

**Frontend State** (editorStore.ts):

- Optimistic UI: timeline advances immediately on confirm
- Session restore from localStorage (thread_id + owner_uuid)
- Pre-opens SSE stream BEFORE POST for progress-heavy steps
- Checkpoint history + fork for time-travel

### AI Chat Assistant

Context-aware creative assistant with 6 tools that read workflow state:

- `get_script_outline`, `get_script_characters`, `get_script_first_draft`
- `get_script_review_opinion`, `get_script_final_draft`, `get_game_data_overview`
- Tools are gated by step progress (only available after relevant content generated)
- Streaming response via SSE (token/thinking/done/error)
- Per-model agent instances with InMemorySaver checkpointer

## Agent Architecture

### AgentPlayer (dual-agent)

**Main Agent**:

- LangChain `create_agent()` with 3 tools (recall_memory, reaction, vote)
- Tools are stage-gated: `recall_personal_script_memory` (all stages), `update_role_reaction` (clue_analysis only), `submit_final_vote` (vote only)
- Middleware: SummarizationMiddleware (200k tokens), ModelRetryMiddleware (3 retries), ToolRetryMiddleware (3 retries)
- InMemorySaver checkpointer with thread*id = `{session_id}*{character_id}`
- System prompt: character personality + background + secrets + tool instructions + speaking style
- User prompt: stage-specific instruction + knowledge context (suspicion graph, suspected_by, player_perspectives) + dynamic system_notice

**Reaction Agent**:

- Separate structured-output LLM (temperature 0.5)
- Returns `SpeechReaction`: `my_suspicion_graph`, `my_suspected_by`, `main_perspective`
- Uses same model provider as main agent (configured per-character)

### AgentManager

- Global `_agent_managers` dict keyed by session_id
- Human player gets `agent=None`
- `broadcast_speech()` runs all reactions in parallel via `asyncio.gather`

### RAG Retrieval

- ChromaDB `PersistentClient` at `./data/chroma/`
- Collection naming: `script_{uuid_with_underscores}`
- ZhipuAI embedding-3 (1024 dims), top_k=2
- Filtered by `character_id` metadata
- Async wrapper via `asyncio.to_thread()`

## Frontend Architecture

### Game Page Component Hierarchy

```
GamePage (h-screen)
  |-- GameHeader (sticky top)
  |-- Main Area (flex row)
  |     |-- CharacterPanel (left, w-64, hidden mobile)
  |     |-- ChatArea (flex-1)
  |     |     |-- Message list (AnimatePresence + motion.div)
  |     |     |-- StreamingBubble (isolated, direct store subscription)
  |     |     |-- Pending human message bubble
  |     |     |-- ChatInputArea (React.memo, bottom)
  |     |-- CharacterPanel (right, w-64, hidden mobile)
  |-- StageTransitionOverlay (fixed z-50)
  |-- VotingModal (Radix Dialog z-50)
  |-- DraftNotebook (localStorage persisted)
  |-- PlayerScriptTooltip
  |-- SettingsModal
```

### ChatInputArea (React.memo)

Extracted from ChatArea for performance isolation. Input state changes don't trigger ChatArea/message list re-renders.

Conditional rendering priority:

1. `stage === "review"` — End game button
2. `stage === "vote"` — Wait message
3. `isAdvancingStage` — Spinner
4. `isProcessingReactions && stage !== "free_discussion"` — Thinking message
5. `stage === "free_discussion" || isHumanTurn` — Full input form
6. `currentSpeakerId === null && !isProcessingReactions && !isStreaming && !isAdvancingStage` — "进入下一阶段" button
7. `isStreaming` — AI speaking indicator
8. Default — "等待 {currentSpeakerName} 发言"

Multi-line input: Enter adds to pending lines, Ctrl+Enter submits all lines as one speech.

### StreamingBubble

Isolated component with direct Zustand store selectors (not receiving via props). Only this component re-renders on token updates. RAF-throttled auto-scroll with user scroll priority (10s pause on scroll up).

### Frontend Performance Patterns

- **RAF batching**: Token updates in `triggerAISpeak` batch via `requestAnimationFrame` — at most one store update per frame
- **React.memo**: ChatInputArea prevents re-renders from streaming state
- **Direct store subscription**: StreamingBubble subscribes to individual selectors, not parent props
- **Optimistic updates**: Human speech added to records before API confirmation; replaced with server data after

### Audio System

- **BGM** (useBGM.ts): Global singleton, stage-based track selection, crossfade (0.6s out / 1.2s in), autoplay unlock via user gesture
- **Click sound** (clickSound.ts): Global delegated listener on `<button>`, singleton Audio, volume 0.25
- **TTS**: Managed in ChatArea via `audioPlayerManager`, per-record state tracking (`ttsStates`, `sysAudioStates`)

### Settings (settingsStore.ts)

Persisted to localStorage (`sober_alone_settings`):

- `bgmEnabled`: boolean (default true)
- `bgmVolume`: number 0-1 (default 0.15)
- `ttsEnabled`: boolean (default false, Beta)

## Key Implementation Details

### LLM Provider System (config.py + llm_factory.py)

5 providers with API keys, base URLs, default models:

- deepseek (deepseek-v4-flash) — **default provider**
- stepfun (step-3.5-flash)
- alibaba (qwen3.5-flash)
- bytedance (doubao-seed-2-0-mini)

DeepSeek uses `ChatDeepSeek`, others use `ChatOpenAI` (OpenAI-compatible protocol).
DeepSeek thinking must be disabled (`disable_thinking=True`) for tool-calling and structured output (multi-turn `reasoning_content` causes API 400 errors).

Per-character LLM config: `AgentManager.initialize_agents()` accepts `llm_configs: Dict[str, Dict]`, allowing different model per AI character.

### Concurrency Safety

- AI voting: per-session `asyncio.Lock` in `vote.py` + independent `AsyncSessionLocal()` per vote task
- Frontend: `AbortController` map per stream type (`'human-speak'`, `'ai-speak-{charId}'`)
- Reactions: 60s per-agent timeout, parallel `asyncio.gather`

### DB Persistence (Critical Gotchas)

- SQLAlchemy detached ORM objects: `db_session.commit()` does NOT persist changes on detached objects
- Raw SQL UPDATE required when flow_controller updates game_session state after operations
- `finalize_voting()` uses raw SQL to persist stage/status after `advance_stage()` because session is a detached ORM object

### API Endpoints

| Method | Path                                   | Purpose                                    |
| ------ | -------------------------------------- | ------------------------------------------ |
| POST   | `/game/create`                         | Create game session                        |
| GET    | `/game/{id}/state`                     | Get full game state                        |
| POST   | `/game/{id}/speech`                    | Human speech (SSE)                         |
| POST   | `/game/{id}/ai-speech/{char_id}`       | AI speech (SSE)                            |
| POST   | `/game/{id}/advance`                   | Advance to next stage                      |
| POST   | `/game/{id}/vote`                      | Submit human vote                          |
| POST   | `/game/{id}/finalize-voting`           | Collect AI votes, tally, advance to review |
| POST   | `/game/{id}/tts/stream`                | Streaming TTS audio (SSE)                  |
| GET    | `/game/{id}/records`                   | Get game history                           |
| POST   | `/game/{id}/abandon`                   | Abandon session                            |
| POST   | `/game/{id}/end`                       | End game                                   |
| GET    | `/game/scripts`                        | List scripts                               |
| GET    | `/game/scripts/{id}/characters`        | Get script characters                      |
| POST   | `/script-editor/start`                 | Start editor workflow                      |
| GET    | `/script-editor/{tid}/state`           | Get workflow state                         |
| POST   | `/script-editor/{tid}/resume`          | Resume from interrupt                      |
| PUT    | `/script-editor/{tid}/prompt/{step}`   | Update step prompt                         |
| GET    | `/script-editor/{tid}/progress-stream` | SSE progress                               |
| POST   | `/script-editor/{tid}/fork`            | Time-travel                                |
| POST   | `/script-editor/chat`                  | AI assistant chat (SSE)                    |

### Database Models

- **GameSession**: status, current_stage, current_round, speech_queue (JSON), current_speaker, votes (JSON), vote_result (JSON), player_threads (JSON), player_types (JSON), timestamps
- **PlayerState**: suspicion_reasons (JSON), suspected_by (JSON), suspected_intensity (float), player_perspectives (JSON list), wait_rounds, remaining_speech_count, has_spoken_this_round, has_voted, voted_for
- **GameRecord**: stage, record_type, speaker_character_id, speaker_name, raw_content, audio_url, timestamp

## Environment

- Backend: `backend/.env` for API keys (gitignored): DEEPSEEK_API_KEY, STEPFUN_API_KEY, QWEN_API_KEY, DOUBAO_API_KEY, MIMO_API_KEY, ZHIPUAI_API_KEY
- Frontend: `frontend/.env` for `VITE_API_URL`
- Default DB: `backend/data/game_data.db` (gitignored)
- Vector store: `backend/data/chroma/` (gitignored)
- Audio files: `backend/data/audio/` (gitignored)
- Image files: `backend/data/images/` (gitignored)
