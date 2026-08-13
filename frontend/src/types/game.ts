// Game types definition - matching backend API

// Game stages matching backend
export type GameStage =
  | 'loading'
  | 'intro'
  | 'clue_analysis'
  | 'free_discussion'
  | 'summary'
  | 'vote'
  | 'review'
  | 'completed';

export type GameStatus = 'waiting' | 'playing' | 'paused' | 'completed';

// Script from backend
export interface Script {
  script_id: string;
  title: string;
  description: string;
  overview: string;
  tags: string;
  difficulty: number;
  player_count: number;
  estimated_duration: number;
  cover_image_url?: string;
  game_full_process?: string;
  full_truth?: string;
  is_ai_generated?: boolean;
}

// Character from backend
export interface Character {
  script_id?: string;
  character_id: string;
  name: string;
  gender?: string;
  age?: number;
  occupation?: string;
  character_script?: string;
  character_script_summary?: string;
  profile?: string;
  appearance?: string;
  system_prompt?: string;
  avatar_url?: string;
  portrait_url?: string;
  is_human?: boolean;
  voice_id?: string; // StepFun TTS voice ID
}

// Player state from backend
export interface PlayerState {
  character_id: string;
  character_name: string;
  is_human: boolean;
  has_spoken_this_round: boolean;
  speeches_this_round?: number;
  remaining_speech_count: number;
  suspicion_reasons: Record<string, { score: number; reason: string }>;
  suspected_by: Record<string, { score: number; reason: string; need_response: boolean }>;
  player_perspectives: Record<string, string>;
}

// Game record from backend
export interface GameRecord {
  id: number;
  session_id: string;
  stage: string;
  speaker_id?: string;
  speaker_name?: string;
  content: string;
  record_type: 'system' | 'speech' | 'action';
  audio_url?: string; // TTS audio file URL
  created_at: string;
}

// Vote info
export interface VoteInfo {
  suspect_id: string;
  suspect_name: string;
  reasoning?: string;
}

// Vote results
export interface VoteResults {
  vote_count: Record<string, number>;
  total_votes: number;
  final_suspect: string | null;
  final_suspect_votes: number;
  details: Record<string, VoteInfo>;
}

// Game session state from backend
export interface GameSessionState {
  session_id: string;
  script_id: string;
  status: GameStatus;
  current_stage: GameStage;
  current_round: number;
  human_character_id: string;
  player_states: PlayerState[];
  current_speaker_id?: string;
  next_speaker_id?: string;
  speech_queue: string[];
  votes: Record<string, VoteInfo>;
  vote_result?: VoteResults;
}

// Streaming message types
export interface StreamingMessage {
  type: 'token' | 'complete' | 'done' | 'error' | 'progress' | 'tool_call' | 'tool_result' | 'thinking' | 'thinking_end' | 'speech_done' | 'reactions_done' | 'audio_delta' | 'audio_done';
  character_id?: string;
  character_name?: string;
  content?: string;
  text?: string;  // Backend sends "text" field for tokens
  message?: string;
  data?: unknown;
  next_speaker_id?: string;
  stage_complete?: boolean;
  audio?: string;    // base64 encoded audio data (for audio_delta)
  duration?: number; // audio duration in seconds (for audio_delta)
}

// AI model option
export interface AIModelOption {
  id: string;
  name: string;
  provider: string;
}

export const AI_MODELS: AIModelOption[] = [
  { id: "deepseek-v4-flash", name: "deepseek-v4-flash", provider: "deepseek" },
  { id: "step-3.5-flash", name: "step-3.5-flash", provider: "stepfun" },
  { id: "qwen3.5-flash-2026-02-23", name: "qwen3.5-flash", provider: "alibaba" },
  { id: "doubao-seed-2-0-mini-260215", name: "doubao-seed-2.0-mini", provider: "bytedance" },
];

// LLM config for backend
export interface LLMConfig {
  provider?: string;
  model?: string;
}

// Game creation request
export interface CreateGameRequest {
  script_id: string;
  human_character_id: string;
  ai_models?: Record<string, string>; // character_id -> model_id
}

// Game creation response
export interface CreateGameResponse {
  success: boolean;
  session_id: string;
  script: Script;
  characters: Character[];
  human_character_id: string;
  player_states: PlayerState[];
  agent_llm_info: Record<string, { model: string; provider: string; is_human: boolean }>;
}

// Stage transition response
export interface StageTransition {
  from_stage: GameStage;
  to_stage: GameStage;
  message?: string;
  system_notice?: string;
}

// Game state response
export interface GameStateResponse {
  success: boolean;
  session_id: string;
  status: GameStatus;
  current_stage: GameStage;
  current_round: number;
  player_states: PlayerState[];
  current_speaker_id?: string;
  next_speaker_id?: string;
  speech_queue: string[];
  has_all_spoken: boolean;
  human_character_id?: string;
  script?: {
    script_id: string;
    title: string;
    description?: string;
    overview?: string;
    tags?: string;
    difficulty?: number;
    player_count?: number;
    estimated_duration?: number;
    cover_image_url?: string;
    is_ai_generated?: boolean;
  };
  characters?: Array<{
    character_id: string;
    name: string;
    gender?: string;
    age?: number;
    occupation?: string;
    profile?: string;
    avatar_url?: string;
    is_human?: boolean;
    character_script?: string;
    character_script_summary?: string;
    system_prompt?: string;
  }>;
  agent_llm_info?: Record<string, AgentLlmInfo>;
  llm_configs?: Record<string, { model: string; provider: string }>;
  votes?: Record<string, VoteInfo>;
  vote_results?: VoteResults | null;
}

// Agent LLM info type
export interface AgentLlmInfo {
  model: string;
  provider: string;
  is_human: boolean;
}

// Frontend game store state
export interface GameState {
  // Session info
  sessionId: string | null;
  scriptId: string;
  humanCharacterId: string | null;
  humanCharacterScript: string; // 玩家个人剧本

  // Game state
  status: GameStatus;
  stage: GameStage;
  currentRound: number;

  // Data
  script: Script | null;
  characters: Character[];
  playerStates: PlayerState[];
  records: GameRecord[];
  currentSpeakerId: string | null;
  speechQueue: string[];
  agentLlmInfo: Record<string, AgentLlmInfo>; // character_id -> LLM info

  // Voting
  votes: Record<string, VoteInfo>;
  voteResults: VoteResults | null;
  isFinalizingVotes: boolean;

  // UI state
  isLoading: boolean;
  isStreaming: boolean;
  isProcessingReactions: boolean; // 正在处理玩家反应（广播发言）
  isAdvancingStage: boolean; // 正在推进阶段
  streamingContent: string;
  streamingSpeakerId: string | null;
  thinkingTip: string; // 工具调用时的提示信息（显示在流式消息上方）
  showStageTransition: boolean;
  stageTransitionMessage: string;
  pendingHumanSpeech: string | null; // 自由发言阶段待发送的真人发言
}

// Stage display names in Chinese
export const STAGE_NAMES: Record<GameStage, string> = {
  loading: '加载中',
  intro: '自我介绍',
  clue_analysis: '搜证阶段',
  free_discussion: '自由讨论',
  summary: '总结发言',
  vote: '投票阶段',
  review: '复盘揭晓',
  completed: '游戏结束',
};

// Difficulty colors
export const DIFFICULTY_COLORS: Record<number, { bg: string; text: string; label: string }> = {
  1: { bg: 'bg-green-500/20', text: 'text-green-400', label: '简单' },
  2: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: '中等' },
  3: { bg: 'bg-orange-500/20', text: 'text-orange-400', label: '困难' },
  4: { bg: 'bg-red-500/20', text: 'text-red-400', label: '极难' },
};
