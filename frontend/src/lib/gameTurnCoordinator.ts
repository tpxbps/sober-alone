import type { GameRecord, GameState, GameStateResponse, GameTurn, PublicClue } from '@/types/game';
import { gameApi, speechApi } from './api';
import { adaptGameState } from './gameStateAdapter';
import { citedIds, speechClues } from './clueScope';
import { SpeechConnectionError } from './sse';

type Get = () => GameState;
type Set = (patch: Partial<GameState>) => void;
type Command = { request_id: string; expected_revision: number; kind: 'ai' | 'human'; speaker: string; content: string };
let connection: AbortController | null = null;

export function cancelTurnSubscription() {
  connection?.abort();
  connection = null;
}

export function readGameLocal<T>(session: string, key: string): T | null {
  try { return JSON.parse(sessionStorage.getItem(`game:${session}:${key}`) || 'null') as T | null; }
  catch { return null; }
}

export function saveGameLocal(session: string, key: string, value: unknown) {
  try {
    if (value === null) sessionStorage.removeItem(`game:${session}:${key}`);
    else sessionStorage.setItem(`game:${session}:${key}`, JSON.stringify(value));
  } catch { /* Storage is optional; the server owns accepted turns. */ }
}

export function mergeGameRecords(current: GameRecord[], incoming: GameRecord[]): GameRecord[] {
  const merged = [...current];
  for (const record of incoming) {
    const index = merged.findIndex(row => (record.turn_id && row.turn_id === record.turn_id) || (record.id > 0 && row.id === record.id));
    if (index >= 0) merged[index] = { ...merged[index], ...record, uiKey: merged[index].uiKey ?? `record:${record.id}` };
    else merged.push({ ...record, uiKey: record.uiKey ?? `record:${record.id}` });
  }
  return merged;
}

function flags(turn: GameTurn | null) {
  return {
    isStreaming: !!turn && ['queued', 'speaking'].includes(turn.status) && turn.kind === 'ai',
    isProcessingReactions: !!turn && (['committing', 'reacting', 'completed'].includes(turn.status) || (turn.kind === 'human' && turn.status === 'queued')),
    streamingSpeakerId: turn?.speaker_id ?? null,
    thinkingTip: turn?.thinking_tip ?? '',
  };
}

export function applyTurn(get: Get, set: Set, turn: GameTurn, record?: GameRecord | null, optimisticKey?: string) {
  const state = get();
  if (turn.session_id !== state.sessionId) return;
  if (state.activeTurn && state.activeTurn.turn_id !== turn.turn_id && turn.state_revision < state.stateRevision) return;
  if (state.activeTurn?.turn_id === turn.turn_id && turn.seq <= state.activeTurn.seq) {
    // A state snapshot can reach us before the same sequence's record acknowledgement.
    if (record && turn.seq === state.activeTurn.seq) set({ records: mergeGameRecords(state.records, [record]) });
    return;
  }
  const existing = state.records.find(row => row.turn_id === turn.turn_id || row.uiKey === optimisticKey || (turn.record_id && row.id === turn.record_id));
  let records = state.records;
  if (!existing) {
    records = [...records, {
      id: turn.record_id ?? 0, uiKey: optimisticKey ?? `turn:${turn.turn_id}`, turn_id: turn.turn_id,
      session_id: turn.session_id, stage: turn.stage, speaker_id: turn.speaker_id,
      speaker_name: state.characters.find(c => c.character_id === turn.speaker_id)?.name,
      content: turn.content, record_type: 'speech', clue_refs: turn.clue_refs, created_at: turn.created_at,
    }];
  } else if (existing.turn_id !== turn.turn_id || existing.pending || ['committing', 'reacting', 'completed', 'failed', 'blocked'].includes(turn.status)) {
    records = records.map(row => row === existing ? {
      ...row, id: turn.record_id ?? row.id, turn_id: turn.turn_id, pending: false,
      content: turn.content, clue_refs: turn.clue_refs,
    } : row);
  }
  if (record) records = mergeGameRecords(records, [record]);
  // Text batches only update activeTurn. The list and every other message keep
  // their object identity; the message body alone subscribes to the live text.
  set({ activeTurn: turn, records, ...flags(turn), isReconnecting: false,
    stateRevision: Math.max(state.stateRevision, turn.state_revision) });
}

export function applyGameSnapshot(get: Get, set: Set, state: GameStateResponse, records?: GameRecord[]) {
  if (get().sessionId !== state.session_id || (state.state_revision ?? 0) < get().stateRevision) return;
  const patch = adaptGameState(state);
  set({ ...patch, ...flags(get().activeTurn), stateRevision: state.state_revision ?? get().stateRevision,
    records: records ? mergeGameRecords(get().records, records) : get().records });
  if (state.active_turn) applyTurn(get, set, state.active_turn);
}

function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>(resolve => {
    const finish = () => { clearTimeout(timer); signal.removeEventListener('abort', finish); resolve(); };
    const timer = setTimeout(finish, ms);
    signal.addEventListener('abort', finish, { once: true });
    if (signal.aborted) finish();
  });
}

async function connect(get: Get, set: Set, first: (signal: AbortSignal) => Promise<Response>, command?: Command) {
  const session = get().sessionId;
  if (!session) return;
  cancelTurnSubscription();
  const controller = new AbortController();
  connection = controller;
  const current = () => connection === controller && !controller.signal.aborted && get().sessionId === session;
  let open = first;
  let backoff = 0;
  try {
    while (current()) {
      let terminal = false;
      try {
        const response = await open(controller.signal);
        for await (const message of speechApi.processSSEStream(response, controller.signal)) {
          if (!current()) return;
          if (message.turn) {
            if (['failed', 'blocked', 'cancelled'].includes(message.turn.status)) {
              connection = null;
              terminal = true;
            }
            const bindKey = command && message.turn.kind === command.kind && message.turn.speaker_id === command.speaker
              ? command.request_id : undefined;
            applyTurn(get, set, message.turn, message.record, bindKey);
          }
          if (message.type === 'done') {
            let state = message.state;
            let records: GameRecord[] | undefined;
            if (!state) {
              const [snapshot, history] = await Promise.all([gameApi.getGameState(session), gameApi.getGameHistory(session)]);
              if (!current()) return;
              state = snapshot;
              records = history.records;
            }
            // Release ownership before publishing idle; the next turn may start
            // immediately while this reader is still cancelling its HTTP body.
            connection = null;
            applyGameSnapshot(get, set, state, records);
            if (!state.active_turn && (state.state_revision ?? 0) >= get().stateRevision) {
              set({ activeTurn: null, ...flags(null), isReconnecting: false });
            }
            saveGameLocal(session, 'command', null);
            terminal = true;
          } else if (message.type === 'resync' && message.state) {
            if (!message.state.active_turn || ['failed', 'blocked'].includes(message.state.active_turn.status)) {
              connection = null;
              terminal = true;
            }
            applyGameSnapshot(get, set, message.state);
            if (command) {
              const accepted = message.state.active_turn?.turn_id === command.request_id;
              if (!accepted) {
                // An obsolete AI reservation is not a message. Human text goes
                // back to the queued draft with its original identity.
                if (command.kind === 'human') queueHumanSpeech(get, set, command.content, undefined, command.request_id);
                else set({ records: get().records.filter(row => row.uiKey !== command.request_id) });
              }
              saveGameLocal(session, 'command', null);
            }
            set({ activeTurn: message.state.active_turn ?? null, ...flags(message.state.active_turn ?? null) });
          } else if (message.type === 'error') {
            throw new Error(message.message || 'Speech transport interrupted');
          }
          if (terminal) return; // Business completion, not the trailing HTTP EOF.
        }
        if (terminal || !current()) return;
        // EOF without a terminal event is a lost subscription, never a lost message.
      } catch (error) {
        if (!current()) return;
        if (error instanceof SpeechConnectionError && error.status >= 400 && error.status < 500 && ![408, 409, 429].includes(error.status)) {
          const turn = get().activeTurn;
          if (turn) set({ activeTurn: { ...turn, status: 'failed', error_code: 'request_rejected', error_message: '连接请求未获接受，请恢复连接或刷新后重试' }, ...flags(null), isReconnecting: false });
          return;
        }
      }
      set({ isReconnecting: true });
      await delay(Math.min(1000 * 2 ** backoff++, 10000), controller.signal);
      if (!current()) return;
      try {
        const state = await gameApi.getGameState(session);
        if (!current()) return;
        applyGameSnapshot(get, set, state);
        const known = get().activeTurn;
        const turn = state.active_turn ?? (known && known.seq >= 0 ? known : null);
        if (turn) {
          if (state.active_turn && ['failed', 'blocked'].includes(turn.status)) return;
          open = signal => speechApi.turnEvents(session, turn.turn_id, turn.seq, signal);
        } else if (command) {
          open = signal => sendCommand(session, command, signal);
        }
      } catch { /* Offline: retain the entire message and retry the subscription. */ }
    }
  } finally {
    // Never clear shared UI from an old connection's finally block.
    if (connection === controller) connection = null;
  }
}

function sendCommand(session: string, command: Command, signal: AbortSignal) {
  return command.kind === 'ai'
    ? speechApi.aiSpeakStream(session, command.speaker, signal, command)
    : speechApi.humanSpeakStream(session, command.content, signal, command);
}

function showReservation(get: Get, set: Set, command: Command) {
  const state = get();
  const record = state.records.find(row => row.turn_id === command.request_id);
  applyTurn(get, set, {
    turn_id: command.request_id, session_id: state.sessionId!, speaker_id: command.speaker,
    kind: command.kind, stage: record?.stage ?? state.stage, status: record ? 'completed' : 'queued',
    attempt: 1, seq: -1, state_revision: state.stateRevision, content: record?.content ?? command.content,
    thinking_tip: '', clue_refs: record?.clue_refs ?? citedIds(command.content, speechClues(state.stage, state.publicClues)),
    record_id: record && record.id > 0 ? record.id : null, error_code: '', error_message: '',
    created_at: record?.created_at ?? new Date().toISOString(),
  }, null, command.request_id);
}

export function queueHumanSpeech(get: Get, set: Set, content: string | null, clues?: PublicClue[], requestId?: string) {
  const state = get();
  const id = content ? requestId ?? state.pendingHumanRequestId ?? crypto.randomUUID() : null;
  const selected = content ? speechClues(state.stage, clues ?? state.publicClues) : [];
  let records = state.records;
  if (content && id) {
    const existing = records.find(row => row.uiKey === id);
    const queued: GameRecord = { id: 0, uiKey: id, turn_id: id, session_id: state.sessionId!, stage: state.stage,
      speaker_id: state.humanCharacterId ?? undefined,
      speaker_name: state.characters.find(c => c.character_id === state.humanCharacterId)?.name,
      content, record_type: 'speech', clue_refs: citedIds(content, selected), pending: true,
      created_at: new Date().toISOString() };
    records = existing ? records.map(row => row === existing ? { ...row, ...queued } : row) : [...records, queued];
  } else if (state.pendingHumanRequestId) {
    records = records.filter(row => row.uiKey !== state.pendingHumanRequestId);
  }
  set({ pendingHumanSpeech: content, pendingHumanRequestId: id, pendingHumanClues: selected, records });
  if (state.sessionId) saveGameLocal(state.sessionId, 'pending', content ? { content, id, clues: selected } : null);
}

export async function startSpeech(get: Get, set: Set, kind: 'ai' | 'human', speaker: string, content = '') {
  const state = get();
  if (!state.sessionId || state.activeTurn || connection || state.isAdvancingStage) return;
  const requestId = kind === 'human' && state.pendingHumanRequestId ? state.pendingHumanRequestId : crypto.randomUUID();
  const command: Command = { request_id: requestId, expected_revision: state.stateRevision, kind, speaker, content };
  const turn: GameTurn = {
    turn_id: requestId, session_id: state.sessionId, speaker_id: speaker, kind, stage: state.stage,
    status: 'queued', attempt: 1, seq: -1, state_revision: state.stateRevision, content, thinking_tip: '',
    clue_refs: citedIds(content, speechClues(state.stage, state.publicClues)), record_id: null,
    error_code: '', error_message: '', created_at: new Date().toISOString(),
  };
  saveGameLocal(state.sessionId, 'command', command);
  if (kind === 'human') {
    set({ pendingHumanSpeech: null, pendingHumanRequestId: null, pendingHumanClues: [] });
    saveGameLocal(state.sessionId, 'pending', null);
  }
  applyTurn(get, set, turn, null, requestId);
  await connect(get, set, signal => sendCommand(state.sessionId!, command, signal), command);
}

export async function resumeSpeech(get: Get, set: Set) {
  const state = get();
  if (!state.sessionId || connection) return;
  const pending = readGameLocal<{ content: string; id: string; clues: PublicClue[] }>(state.sessionId, 'pending');
  if (pending) queueHumanSpeech(get, set, pending.content, pending.clues, pending.id);
  if (state.activeTurn && state.activeTurn.seq >= 0) {
    const turn = state.activeTurn;
    if (['failed', 'blocked', 'cancelled'].includes(turn.status)) return;
    return connect(get, set, signal => speechApi.turnEvents(state.sessionId!, turn.turn_id, turn.seq, signal));
  }
  const command = readGameLocal<Command>(state.sessionId, 'command');
  if (command) {
    showReservation(get, set, command);
    return connect(get, set, signal => sendCommand(state.sessionId!, command, signal), command);
  }
}

export async function retrySpeech(get: Get, set: Set) {
  const { sessionId, activeTurn } = get();
  if (!sessionId || !activeTurn || connection || !['failed', 'blocked'].includes(activeTurn.status)) return;
  set({ isReconnecting: true });
  if (activeTurn.seq < 0) {
    const command = readGameLocal<Command>(sessionId, 'command');
    if (command) return connect(get, set, signal => sendCommand(sessionId, command, signal), command);
  }
  await connect(get, set, signal => speechApi.retryTurn(sessionId, activeTurn.turn_id, activeTurn.attempt, signal));
}
