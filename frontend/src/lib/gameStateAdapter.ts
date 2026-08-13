import type { Character, GameState, GameStateResponse, Script } from '@/types/game'

export type GameStatePatch = Pick<
  GameState,
  | 'status'
  | 'stage'
  | 'currentRound'
  | 'playerStates'
  | 'currentSpeakerId'
  | 'speechQueue'
  | 'characters'
  | 'humanCharacterId'
  | 'humanCharacterScript'
  | 'script'
  | 'scriptId'
  | 'agentLlmInfo'
  | 'votes'
  | 'voteResults'
>

export function adaptGameState(state: GameStateResponse): GameStatePatch {
  const characters: Character[] = (state.characters ?? []).map((character) => ({
    ...character,
    gender: character.gender || '未知',
    age: character.age || 0,
    occupation: character.occupation || '',
    profile: character.profile || '',
    avatar_url: character.avatar_url || '',
  }))
  const humanCharacter = state.characters?.find((character) => character.is_human)
  const humanCharacterId = state.human_character_id || humanCharacter?.character_id || null
  const script: Script | null = state.script
    ? {
        script_id: state.script.script_id,
        title: state.script.title,
        description: state.script.description || '',
        overview: state.script.overview || '',
        tags: state.script.tags || '',
        difficulty: state.script.difficulty || 1,
        player_count: state.script.player_count || 0,
        estimated_duration: state.script.estimated_duration || 0,
        cover_image_url: state.script.cover_image_url,
        is_ai_generated: state.script.is_ai_generated,
      }
    : null

  return {
    status: state.status,
    stage: state.current_stage,
    currentRound: state.current_round,
    playerStates: state.player_states || [],
    currentSpeakerId: state.current_speaker_id || null,
    speechQueue: state.speech_queue || [],
    characters,
    humanCharacterId,
    humanCharacterScript: humanCharacter?.character_script || '',
    script,
    scriptId: script?.script_id || '',
    agentLlmInfo:
      state.agent_llm_info ||
      (state.llm_configs
        ? Object.fromEntries(
            Object.entries(state.llm_configs).map(([key, value]) => [
              key,
              { ...value, is_human: false },
            ]),
          )
        : {}),
    votes: state.votes || {},
    voteResults: state.vote_results || null,
  }
}
