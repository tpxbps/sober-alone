import { describe, expect, it } from 'vitest'

import { adaptGameState } from './gameStateAdapter'

describe('adaptGameState', () => {
  it('normalizes a server response without mutating it', () => {
    const response = {
      success: true,
      session_id: 'session',
      status: 'playing' as const,
      current_stage: 'intro' as const,
      current_round: 0,
      player_states: [],
      speech_queue: [],
      has_all_spoken: false,
      human_character_id: 'human',
      script: {
        script_id: 'script',
        title: '零点来电',
        estimated_duration: 25,
        is_ai_generated: true,
      },
      characters: [{ character_id: 'human', name: '林岚', is_human: true }],
    }

    const patch = adaptGameState(response)

    expect(patch.script?.estimated_duration).toBe(25)
    expect(patch.humanCharacterId).toBe('human')
    expect(patch.characters[0].gender).toBe('未知')
    expect(response.characters[0]).not.toHaveProperty('gender')
  })
})
