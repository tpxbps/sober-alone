import { describe, expect, it } from 'vitest';
import { useGameStore } from '@/stores/gameStore';
import { speechClues } from './clueScope';

const first = { id: 'c01', summary: '门锁', content: '完好', stage: 1 };
const second = { id: 'c02', summary: '日记', content: '第二轮才公开', stage: 2 };

describe('per-speech clue scope', () => {
  it('never grants introduction permission even for a stale state', () => {
    expect(speechClues('intro', [first])).toEqual([]);
  });
  it('freezes streaming and pending human scopes while later clues arrive', () => {
    useGameStore.getState().reset();
    useGameStore.setState({ stage: 'free_discussion', publicClues: [first] });
    useGameStore.getState().setStreaming(true, '发言开始', 'ai');
    useGameStore.getState().setPendingHumanSpeech('我的证据。[c01]', [first]);
    useGameStore.setState({ publicClues: [first, second] });
    useGameStore.getState().setStreaming(true, '发言继续', 'ai');
    expect(useGameStore.getState().streamingClues).toEqual([first]);
    expect(useGameStore.getState().pendingHumanClues).toEqual([first]);
    useGameStore.getState().reset();
  });
});
