import { createServer, type ServerResponse } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, resolve, sep } from 'node:path';
import type { GameRecord, GameStateResponse, GameTurn } from '../src/types/game';

/** A real, chunked HTTP server; route.fulfill would buffer the entire SSE body. */
export async function turnServer(stage: 'intro' | 'free_discussion' = 'intro') {
  const clients = new Set<ServerResponse>();
  const records: GameRecord[] = [];
  let active: GameTurn | null = null;
  let currentSpeaker: string | null = 'ai';
  let revision = 0;
  let posts = 0;
  let subscriptions = 0;
  let retries = 0;
  const turns = new Map<string, GameTurn>();
  const characters = [
    { character_id: 'human', name: '陆鸣', profile: '主持人', is_human: true },
    { character_id: 'ai', name: '姜芮', profile: '制作人', is_human: false },
  ];
  const state = (): GameStateResponse => ({
    success: true, session_id: 'continuity', status: 'playing', current_stage: stage, current_round: 1,
    state_revision: revision, active_turn: active, current_speaker_id: currentSpeaker,
    human_character_id: 'human', speech_queue: currentSpeaker ? [currentSpeaker] : [],
    has_all_spoken: !currentSpeaker, turn_processing: active?.status === 'reacting',
    characters, player_states: characters.map(c => ({
      character_id: c.character_id, character_name: c.name, is_human: c.is_human,
      has_spoken_this_round: false, remaining_speech_count: 3,
      suspicion_reasons: {}, suspected_by: {}, player_perspectives: {},
    })), script: { script_id: 'test', title: '回合连续性测试', difficulty: 1, player_count: 2, estimated_duration: 10 },
  });
  const frame = (turn: GameTurn) => ({
    type: turn.status === 'completed' ? 'done' : turn.status === 'committing' ? 'speech_done'
      : turn.status === 'reacting' ? 'speech_recorded' : 'turn_snapshot',
    turn, record: records.find(row => row.turn_id === turn.turn_id) ?? null,
    ...(turn.status === 'completed' ? { state: state() } : {}),
  });
  const send = (response: ServerResponse, turn: GameTurn) => response.write(`data: ${JSON.stringify(frame(turn))}\n\n`);
  const dist = resolve('dist');
  const server = createServer(async (request, response) => {
    const path = new URL(request.url!, 'http://localhost').pathname;
    const json = (data: unknown) => { response.writeHead(200, { 'content-type': 'application/json' }); response.end(JSON.stringify(data)); };
    if (path.endsWith('/state')) return json(state());
    if (path.endsWith('/records')) return json({ success: true, records });
    if (path.endsWith('/capabilities')) return json({ models: [], features: {} });
    if (path.endsWith('/retry') || path.endsWith('/events') || path.endsWith('/ai-speech/ai') || path.endsWith('/speech')) {
      let turn: GameTurn | undefined;
      if (request.method === 'POST') {
        const chunks = [];
        for await (const chunk of request) chunks.push(chunk);
        const command = JSON.parse(Buffer.concat(chunks).toString());
        if (path.endsWith('/retry')) {
          turn = turns.get(path.split('/').at(-2)!);
          if (turn && command.expected_attempt === turn.attempt) {
            retries++;
            turn = { ...turn, status: 'queued', attempt: turn.attempt + 1, seq: turn.seq + 1, content: '' };
            active = turn; turns.set(turn.turn_id, turn);
          }
        } else { posts++; turn = turns.get(command.request_id); }
        if (!turn) {
          const human = path.endsWith('/speech');
          turn = { turn_id: command.request_id, session_id: 'continuity', kind: human ? 'human' : 'ai',
            speaker_id: human ? 'human' : 'ai', stage, status: 'queued', attempt: 1, seq: 0,
            state_revision: ++revision, content: command.content ?? '', clue_refs: [], thinking_tip: '',
            error_code: '', error_message: '', record_id: null, created_at: new Date().toISOString() };
          turns.set(turn.turn_id, turn);
          active = turn;
        }
      } else turn = turns.get(path.split('/').at(-2)!);
      if (!turn) { response.writeHead(404); response.end(); return; }
      subscriptions++;
      response.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', 'x-accel-buffering': 'no' });
      response.flushHeaders();
      clients.add(response);
      response.on('close', () => clients.delete(response));
      send(response, turn);
      return;
    }
    if (path.startsWith('/api/')) return json({ success: true });
    const filename = path === '/' ? resolve(dist, 'index.html') : resolve(dist, '.' + path);
    if (!filename.startsWith(dist + sep)) { response.writeHead(404); response.end(); return; }
    try {
      const types: Record<string, string> = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.png': 'image/png', '.woff2': 'font/woff2' };
      response.writeHead(200, { 'content-type': types[extname(filename)] ?? 'application/octet-stream' });
      response.end(await readFile(filename));
    } catch { response.end(); }
  });
  await new Promise<void>(done => server.listen(0, '127.0.0.1', done));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Missing test server port');
  return {
    url: `http://127.0.0.1:${address.port}/?session=continuity`,
    get retries() { return retries; },
    get turn() { return active; }, get posts() { return posts; }, get subscriptions() { return subscriptions; },
    update(status: GameTurn['status'], content?: string, nextSpeaker: string | null = 'human') {
      if (!active) throw new Error('No active turn');
      active = { ...active, status, seq: active.seq + 1, content: content ?? active.content };
      if (status === 'reacting') {
        active.record_id = records.length + 1;
        active.state_revision = ++revision;
        records.push({ id: active.record_id, turn_id: active.turn_id, session_id: 'continuity', stage,
          content: active.content, speaker_id: active.speaker_id, speaker_name: active.kind === 'ai' ? '姜芮' : '陆鸣',
          record_type: 'speech', created_at: active.created_at });
        currentSpeaker = null;
      }
      const turn = active;
      if (status === 'completed') { turn.state_revision = ++revision; active = null; currentSpeaker = nextSpeaker; }
      turns.set(turn.turn_id, turn);
      for (const client of clients) send(client, turn);
    },
    duplicate() { if (active) for (const client of clients) send(client, active); },
    disconnect() { for (const client of clients) client.end(); clients.clear(); },
    async close() {
      for (const client of clients) client.destroy();
      server.closeAllConnections();
      await new Promise<void>(done => server.close(() => done()));
    },
  };
}
