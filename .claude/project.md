# Sober Alone - AI Murder Mystery Game (剧本杀)

## Tech Stack

- **Backend**: Python 3.13 / FastAPI / SQLAlchemy (async aiosqlite) / LangChain + LangGraph
- **Frontend**: React 19 / TypeScript / Zustand / Vite / TailwindCSS / Framer Motion
- **Storage**: SQLite (game state) + ChromaDB (vector embeddings)
- **LLM**: Multiple providers (deepseek/stepfun/alibaba/bytedance...), configurable per-character

## Directory Structure

```
backend/app/
  main.py              # FastAPI entry, CORS, router mount at /api/v1
  core/
    config.py          # pydantic-settings, API keys/base URLs for 5 LLM providers
    llm_factory.py     # create_llm() by model name, create_summary_llm() via init_chat_model
  api/routes/
    game.py            # 12 REST+SSE endpoints (create, state, speech, ai-speech, vote, etc.)
  services/
    game_service.py    # Business logic layer, SSE streaming, session lifecycle (~1100 lines)
  game/
    flow_controller.py # Game stage machine, speech processing, reaction persistence (~1089 lines)
    speech_scheduler.py # Free discussion weighted scoring + round-robin priority
  agents/
    agent_manager.py   # Multi-agent lifecycle, broadcast, global cache by session_id
    agent_player.py    # Dual-agent architecture (main agent + reaction agent), tools, streaming
    state.py           # GameAgentState (LangGraph agent state schema)
    context.py         # ContextVar for passing db_session to tools
    middleware/
      clean_history.py # SummarizationMiddleware (triggers at 100k tokens)
    tools/
      recall_memory.py # RAG retrieval from ChromaDB (all stages)
      reaction.py      # Update suspicion graph (clue_analysis stage only)
      vote.py          # Submit final vote with per-session async lock (vote stage only)
  db/
    session.py         # AsyncSessionLocal engine
    models/
      game_session.py  # GameSession + GameStatus/GameStage enums
      player_state.py  # PlayerState: suspicion, speech stats, perspectives, vote tracking
      game_record.py   # GameRecord + RecordType enum (system/speech/vote/reaction/summary)
  rag/
    retriever.py       # ChromaDB vector retriever using zhipuai embedding-3

frontend/src/
  App.tsx              # Root routing (home/game), session restore
  screens/
    Homepage.tsx       # Script selection, character/model config, game creation
    GamePage.tsx       # Main game screen, auto-trigger AI speech, SSE orchestration
  stores/
    gameStore.ts       # Zustand store: full game state, SSE handling, pendingHumanSpeech pattern
    settingsStore.ts   # BGM settings (persisted)
  lib/
    api.ts             # Axios client + SSE stream parser (processSSEStream async generator)
  types/
    game.ts            # All TypeScript types + AI_MODELS constant (5 models)
  components/game/     # 10 game components (ChatArea, StreamingBubble, VotingModal, etc.)
  components/ui/       # shadcn/ui primitives + Markdown renderers + DynamicDot
  hooks/
    useBGM.ts          # Background music by stage
```

## Game Flow

```
Script (game_full_process JSON array) defines stage sequence
  |
  v
INTRO (sequential) -> CLUE_ANALYSIS (sequential) -> FREE_DISCUSSION (emergent)
  |                                                      |
  v                                                      v
[repeat clue rounds per script]                    advance_stage()
  |
  v
SUMMARY (sequential) -> VOTE -> REVIEW -> COMPLETED
```

### Stage Machine (`flow_controller.py`)

- `advance_stage()` reads `game_full_process[current_round]` to determine next stage type
- `advancement` type: CLUE_ANALYSIS -> FREE_DISCUSSION (sub-phase, same round)
- `vote` type: SUMMARY -> VOTE (via `transition_to_vote()`)
- Stage transitions trigger async perspective compression via LLM

### Core Loop (`process_speech`)

Every speech (human or AI) follows:
1. **Record** -> `GameRecord` (SPEECH type) to DB
2. **Update speaker** -> `PlayerState`: decrement `remaining_speech_count`, reset `wait_rounds`
3. **Broadcast** -> All other AI agents call `react_to_speech()` in parallel (60s timeout each)
4. **Save reactions** -> Merge `SpeechReaction` (suspicion, perspectives) into each listener's `PlayerState`
5. **Determine next speaker** -> Sequential pop from `speech_queue` OR `SpeechScheduler` scoring

### Free Discussion Speaker Selection (`speech_scheduler.py`)

Two-tier priority:
1. **Tier 1**: Players who haven't spoken this round (`has_spoken_this_round=false`) — always selected first
2. **Tier 2**: Players who have spoken — selected by weighted score

Score formula: `0.4 * suspected_intensity + 0.3 * active_suspicion + 0.3 * opportunity_cost`

Within each tier: top 3 candidates by score, weighted random selection.

### SSE Streaming Protocol

Backend streams events to frontend:
- `thinking` — AI is using tools, show tip message
- `token` — Streaming text chunk
- `speech_done` — AI speech complete, starting reactions
- `reactions_done` — All reactions processed
- `done` — Everything complete, includes `next_speaker_id` and `stage_complete`
- `error` — Error message

### Pending Human Speech Pattern

During free_discussion, if human sends a message while AI is streaming/processing:
1. Frontend stores message as `pendingHumanSpeech` (no API call yet)
2. When AI's `done` event arrives, the pending speech is sent inline
3. After human speech completes, `currentSpeakerId` is set from backend response (with `state.current_speaker_id` fallback)

## Agent Architecture

### AgentPlayer (dual-agent)

**Main Agent** (`_agent`):
- LangChain `create_agent()` with 3 tools (recall_memory, reaction, vote)
- Middleware: SummarizationMiddleware (100k tokens), ModelRetryMiddleware, ToolRetryMiddleware
- InMemorySaver checkpointer per session+character
- Streams tokens via `astream()`

**Reaction Agent** (`_reaction_agent`):
- Separate agent with structured output (`SpeechReaction` Pydantic model)
- Returns: `my_suspicion_graph`, `my_suspected_by`, `main_perspective`
- Uses `deepseek-chat` at temperature 0.5 for speed/stability

### AgentManager

- Global `_agent_managers` dict keyed by session_id
- Human player gets `agent=None` (no AI agent created)
- `broadcast_speech()` runs all reactions in parallel via `asyncio.gather`

## Key Implementation Details

### LLM Provider System (`config.py` + `llm_factory.py`)

- 5 providers with API keys, base URLs, default models
- `MODEL_PROVIDER_MAP` in llm_factory maps model name -> provider string
- DeepSeek uses `ChatDeepSeek`, others use `ChatOpenAI` (OpenAI-compatible APIs)
- `create_summary_llm()` uses `init_chat_model` directly, defaults to step-3.5-flash

### Concurrency Safety

- AI voting uses per-session `asyncio.Lock` in `vote.py` to serialize DB read-modify-write
- Each concurrent AI vote task uses independent `AsyncSessionLocal()` session
- Frontend uses `AbortController` map to cancel in-flight SSE streams on session change

### Scroll Behavior (ChatArea.tsx)

- Only scrolls when `records.length` actually increases (new messages)
- Replacement (optimistic -> server records, same count) does NOT trigger scroll
- StreamingBubble handles its own scroll via `scrollTop = scrollHeight`

### Frontend State Management (gameStore.ts)

- Zustand store with ~25 state fields
- `initializeGame()` does full state reset + history load
- `cancelActiveOperations()` aborts all SSE controllers and resets UI flags
- `advanceStage()` reloads state + history after backend transition

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/game/create` | Create game session |
| GET | `/game/{id}/state` | Get full game state |
| POST | `/game/{id}/speech` | Human speech (SSE) |
| POST | `/game/{id}/ai-speech/{char_id}` | AI speech (SSE) |
| POST | `/game/{id}/advance` | Advance to next stage |
| POST | `/game/{id}/vote` | Submit human vote |
| POST | `/game/{id}/finalize-voting` | Collect AI votes, tally, advance to review |
| GET | `/game/{id}/records` | Get game history |
| POST | `/game/{id}/abandon` | Abandon session |
| POST | `/game/{id}/end` | End game |
| GET | `/game/scripts` | List scripts |
| GET | `/game/scripts/{id}/characters` | Get script characters |

## Database Models

- **GameSession**: status, current_stage, current_round, speech_queue (JSON), current_speaker, votes (JSON), timestamps
- **PlayerState**: suspicion_reasons, suspected_by, player_perspectives (JSON), remaining_speech_count, has_spoken_this_round, has_voted, voted_for
- **GameRecord**: stage, record_type, speaker_character_id, speaker_name, raw_content, timestamp (immutable log)

## Environment

- Backend: `backend/.env` for API keys (gitignored)
- Frontend: `frontend/.env` for `VITE_API_URL`
- Default DB: `backend/data/game_data.db` (gitignored)
- Vector store: `backend/data/chroma/` (gitignored)