import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { GameRecord, GameStateResponse, GameTurn } from '@/types/game';
import { decodeSpeechEvents } from './sse';

const api = vi.hoisted(() => ({
  aiSpeakStream: vi.fn(), humanSpeakStream: vi.fn(), turnEvents: vi.fn(), retryTurn: vi.fn(),
  getGameState: vi.fn(), getGameHistory: vi.fn(),
}));
vi.mock('./api', () => ({
  gameApi: api, voteApi: {}, speechApi: { ...api, processSSEStream: (...args: Parameters<typeof decodeSpeechEvents>) => decodeSpeechEvents(...args) },
}));
import { useGameStore } from '@/stores/gameStore';

function channel(cancel?: () => Promise<void>) {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({ start(value) { controller = value; }, cancel });
  return {
    response: new Response(body, { headers: { 'content-type': 'text/event-stream' } }),
    send(event: unknown) { controller.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`)); },
    end() { controller.close(); },
  };
}
function turn(patch: Partial<GameTurn> = {}): GameTurn {
  return { turn_id: 'turn', session_id: 'game', kind: 'ai', speaker_id: 'ai', stage: 'intro', status: 'speaking',
    attempt: 1, seq: 1, state_revision: 1, content: '逐步输出', thinking_tip: '', clue_refs: [], record_id: null,
    error_code: '', error_message: '', created_at: '2026-09-30T00:00:00', ...patch };
}
function snapshot(patch: Partial<GameStateResponse> = {}): GameStateResponse {
  return { success: true, session_id: 'game', status: 'playing', current_stage: 'intro', current_round: 0,
    state_revision: 0, active_turn: null, current_speaker_id: 'ai', speech_queue: ['ai', 'human'], player_states: [],
    has_all_spoken: false, ...patch };
}
function record(value: GameTurn): GameRecord {
  return { id: 1, turn_id: value.turn_id, session_id: 'game', stage: 'intro', speaker_id: value.speaker_id,
    record_type: 'speech', content: value.content, created_at: value.created_at };
}
const state = () => useGameStore.getState();

beforeEach(() => {
  const saved = new Map<string, string>();
  vi.stubGlobal('sessionStorage', { getItem: (key: string) => saved.get(key) ?? null,
    setItem: (key: string, value: string) => saved.set(key, value), removeItem: (key: string) => saved.delete(key) });
  vi.clearAllMocks();
  state().reset();
  useGameStore.setState({ sessionId: 'game', stage: 'intro', currentSpeakerId: 'ai', humanCharacterId: 'human' });
});
afterEach(() => { state().reset(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('durable turn coordination', () => {
  it('restores a response-lost human command with its text before the new response arrives', async () => {
    const original = channel(); const resumed = channel();
    api.humanSpeakStream.mockResolvedValueOnce(original.response).mockResolvedValueOnce(resumed.response);
    const first = state().humanSpeak('刷新不能丢的原话');
    const id = state().activeTurn!.turn_id;
    await Promise.resolve();
    state().reset(); await first;
    api.getGameState.mockResolvedValue(snapshot({ current_speaker_id: 'human' }));
    api.getGameHistory.mockResolvedValue({ records: [], success: true });
    await state().initializeGame('game');
    expect(state().activeTurn).toMatchObject({ turn_id: id, content: '刷新不能丢的原话', seq: -1 });
    expect(state().records).toHaveLength(1);
    expect(api.humanSpeakStream).toHaveBeenCalledTimes(2);
    state().cancelActiveOperations();
  });

  it('accepts the record acknowledgement even when its sequence arrived in a state snapshot first', async () => {
    const stream = channel(); api.aiSpeakStream.mockResolvedValue(stream.response);
    const work = state().triggerAISpeak('ai');
    const value = turn({ turn_id: state().activeTurn!.turn_id, status: 'reacting', record_id: 1 });
    state().updateFromAPI(snapshot({ state_revision: 1, active_turn: value }));
    stream.send({ type: 'speech_recorded', turn: value, record: record(value) });
    await vi.waitFor(() => expect(state().records[0].id).toBe(1));
    stream.send({ type: 'done', turn: { ...value, status: 'completed', seq: 2 }, record: record(value), state: snapshot({ state_revision: 1 }) });
    await work;
    expect(state().records).toHaveLength(1);
    expect(state().records[0].content).toBe(value.content);
  });

  it('keeps the same message through streaming, old polling, commit and completion', async () => {
    const stream = channel(); api.aiSpeakStream.mockResolvedValue(stream.response);
    const work = state().triggerAISpeak('ai');
    const key = state().records[0].uiKey;
    const value = turn({ turn_id: state().activeTurn!.turn_id });
    stream.send({ type: 'turn_snapshot', turn: value });
    await vi.waitFor(() => expect(state().activeTurn?.content).toBe(value.content));
    state().updateFromAPI(snapshot({ turn_processing: false, current_speaker_id: 'other' }));
    expect(state().isStreaming).toBe(true);
    expect(state().activeTurn?.content).toBe(value.content);
    stream.send({ type: 'speech_done', turn: { ...value, status: 'committing', seq: 2 } });
    await vi.waitFor(() => expect(state().isProcessingReactions).toBe(true));
    expect(state().records[0].uiKey).toBe(key);
    stream.send({ type: 'done', turn: { ...value, status: 'completed', seq: 4, record_id: 1, state_revision: 3 },
      record: record(value), state: snapshot({ state_revision: 3, current_speaker_id: 'human' }) });
    await work;
    expect(state().records).toHaveLength(1);
    expect(state().records[0]).toMatchObject({ uiKey: key, id: 1, content: value.content });
    expect(state().activeTurn).toBeNull();
  });

  it('old HTTP cancellation cannot clear the next turn', async () => {
    let release!: () => void;
    const old = channel(() => new Promise<void>(resolve => { release = resolve; }));
    const next = channel();
    api.aiSpeakStream.mockResolvedValueOnce(old.response).mockResolvedValueOnce(next.response);
    const first = state().triggerAISpeak('ai');
    const value = turn({ turn_id: state().activeTurn!.turn_id });
    old.send({ type: 'done', turn: { ...value, status: 'completed', record_id: 1 }, record: record(value),
      state: snapshot({ state_revision: 1, current_speaker_id: 'ai2' }) });
    await vi.waitFor(() => expect(state().activeTurn).toBeNull());
    const second = state().triggerAISpeak('ai2');
    const nextId = state().activeTurn!.turn_id;
    next.send({ type: 'turn_snapshot', turn: turn({ turn_id: nextId, speaker_id: 'ai2', content: '新的流式内容', state_revision: 2 }) });
    await vi.waitFor(() => expect(state().activeTurn?.content).toBe('新的流式内容'));
    release(); await first;
    expect(state().activeTurn?.turn_id).toBe(nextId);
    expect(state().isStreaming).toBe(true);
    state().cancelActiveOperations(); await second;
  });

  it('detached optimistic reservation resends its idempotent command instead of subscribing to an unaccepted turn', async () => {
    const first = channel(); const resumed = channel();
    api.aiSpeakStream.mockResolvedValueOnce(first.response).mockResolvedValueOnce(resumed.response);
    const work = state().triggerAISpeak('ai');
    const id = state().activeTurn!.turn_id;
    state().cancelActiveOperations(); await work;
    const recovery = state().resumeActiveTurn();
    await vi.waitFor(() => expect(api.aiSpeakStream).toHaveBeenCalledTimes(2));
    expect(api.aiSpeakStream.mock.calls[1][3].request_id).toBe(id);
    expect(api.turnEvents).not.toHaveBeenCalled();
    state().cancelActiveOperations(); await recovery;
  });

  it('EOF without done retains text and reconnects without generating again', async () => {
    vi.useFakeTimers();
    const lost = channel(); const resumed = channel();
    api.aiSpeakStream.mockResolvedValue(lost.response);
    api.turnEvents.mockResolvedValue(resumed.response);
    const work = state().triggerAISpeak('ai');
    const value = turn({ turn_id: state().activeTurn!.turn_id });
    api.getGameState.mockResolvedValue(snapshot({ state_revision: 1, active_turn: value }));
    lost.send({ type: 'turn_snapshot', turn: value }); lost.end();
    await vi.advanceTimersByTimeAsync(0);
    expect(state().activeTurn?.content).toBe(value.content);
    expect(state().isReconnecting).toBe(true);
    await vi.advanceTimersByTimeAsync(1000);
    expect(api.turnEvents).toHaveBeenCalledTimes(1);
    resumed.send({ type: 'done', turn: { ...value, seq: 3, status: 'completed' }, record: record(value), state: snapshot({ state_revision: 1 }) });
    await vi.advanceTimersByTimeAsync(0); await work;
    expect(api.aiSpeakStream).toHaveBeenCalledTimes(1);
    expect(state().records[0].content).toBe(value.content);
  });

  it.each(['queued', 'speaking', 'committing', 'reacting'] as const)('refresh attaches to %s without issuing another speech', async status => {
    const stream = channel();
    const value = turn({ status, content: status === 'queued' ? '' : '恢复的内容' });
    api.getGameState.mockResolvedValue(snapshot({ state_revision: 1, active_turn: value }));
    api.getGameHistory.mockResolvedValue({ success: true, records: [] });
    api.turnEvents.mockResolvedValue(stream.response);
    await state().initializeGame('game');
    await vi.waitFor(() => expect(api.turnEvents).toHaveBeenCalledTimes(1));
    expect(state().activeTurn?.content).toBe(value.content);
    expect(api.aiSpeakStream).not.toHaveBeenCalled();
    state().cancelActiveOperations();
  });

  it('human acknowledgement preserves its optimistic key and stale events cannot regress content', async () => {
    const stream = channel(); api.humanSpeakStream.mockResolvedValue(stream.response);
    const work = state().humanSpeak('真人原话');
    const key = state().records[0].uiKey;
    const value = turn({ turn_id: state().activeTurn!.turn_id, kind: 'human', speaker_id: 'human', content: '真人原话', status: 'reacting', seq: 3 });
    stream.send({ type: 'speech_recorded', turn: value, record: record(value) });
    stream.send({ type: 'turn_snapshot', turn: { ...value, seq: 1, content: '' } });
    await vi.waitFor(() => expect(state().activeTurn?.seq).toBe(3));
    expect(state().records).toHaveLength(1);
    expect(state().records[0].uiKey).toBe(key);
    expect(state().activeTurn?.content).toBe('真人原话');
    state().cancelActiveOperations(); await work;
  });
});
