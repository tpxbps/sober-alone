// Script Editor Types

export interface StepInfo {
  step: string;
  label: string;
  needs_review: boolean;
}

export interface EditorInterruptInfo {
  step: string;
  step_label: string;
  generated_content: string;
  characters?: Array<{
    name: string;
    gender: string;
    age: number;
    occupation: string;
    profile?: string;
    appearance?: string;
  }>;
  character_scripts?: Record<string, string>;
  review_opinion?: string;
  game_data_sections?: GameDataSections;
  prompt_used: string;
  rejected?: boolean;
  reason?: string;
}

export interface EditorWorkflowState {
  script_title: string;
  script_id: string;
  user_idea: string;
  player_count: number;
  difficulty: number;
  num_clue_rounds: number;
  outline: string;
  characters: Array<{
    character_id?: string;
    name: string;
    gender?: string;
    age?: number;
    occupation?: string;
    profile?: string;
    appearance?: string;
  }>;
  first_draft: string;
  review_opinion: string;
  final_draft: string;
  character_scripts: Record<string, string>;
  game_data_sections: GameDataSections;
  prompts: Record<string, string>;
  cover_image_url: string;
  character_avatars: Record<string, string>;
  error_message: string;
  safety_passed?: boolean;
  safety_rejection_reason?: string;
}

export interface StartWorkflowResponse {
  success: boolean;
  thread_id: string;
  script_id: string;
  script_title: string;
  current_step: string;
  interrupt: EditorInterruptInfo | null;
  state: EditorWorkflowState;
}

export interface WorkflowStateResponse {
  success: boolean;
  thread_id: string;
  current_step: string;
  is_complete: boolean;
  interrupt: EditorInterruptInfo | null;
  state: EditorWorkflowState;
}

export interface ResumeWorkflowResponse {
  success: boolean;
  thread_id: string;
  current_step: string;
  is_complete: boolean;
  interrupt: EditorInterruptInfo | null;
  state: EditorWorkflowState;
}

// === Consolidated workflow phases ===

export interface WorkflowPhase {
  phase: string;
  label: string;
  desc: string;
  isAuto: boolean;
}

// Display phases
export const WORKFLOW_PHASES: WorkflowPhase[] = [
  { phase: "idea", label: "构思大纲", desc: "输入故事创意，设定基本参数", isAuto: false },
  { phase: "outline", label: "大纲审阅", desc: "审阅并修改AI生成的剧本大纲", isAuto: false },
  { phase: "first_draft", label: "初稿创作", desc: "基于大纲撰写完整剧本初稿并审阅", isAuto: false },
  { phase: "review_final", label: "审稿修订", desc: "AI审稿意见与终稿修订", isAuto: false },
  { phase: "game_data", label: "终稿定稿", desc: "结构化数据生成、审阅与保存", isAuto: false },
  { phase: "assets", label: "资源生成", desc: "生成图片、语音、向量数据", isAuto: true },
];

export type WorkflowPhaseKey = (typeof WORKFLOW_PHASES)[number]["phase"];

// Map backend step name → display phase
export function getPhaseFromStep(step: string): WorkflowPhaseKey {
  if (!step || step === "init") return "idea";
  if (step === "generate_outline" || step === "review_outline") return "outline";
  if (step === "generate_first_draft" || step === "review_first_draft")
    return "first_draft";
  if (
    step === "review_by_llm" ||
    step === "generate_final_draft" ||
    step === "review_final"
  )
    return "review_final";
  if (
    step === "convert_to_game_data" ||
    step === "review_game_data" ||
    step === "safety_check"
  )
    return "game_data";
  if (step === "save_to_database" || step === "generate_assets")
    return "assets";
  return "idea";
}

// === Game data sections ===

export interface ClueStage {
  round_number: number;
  stage_title: string;
  system_notice: string;
  discussion_notice: string;
  clues: Array<{
    description: string;
    pointing_to: string;
    is_misleading: boolean;
  }>;
  free_speech_limit: number;
}

export interface CharacterGameData {
  name: string;
  gender?: string;
  age?: number;
  occupation?: string;
  character_script?: string;
  profile: string;
  appearance: string;
  system_prompt: string;
  mimo_voice_id?: string;
  step_voice_id?: string;
  script_summary?: string;
}

export interface GameDataSections {
  opening: string;
  clue_stages: ClueStage[];
  truth_reveal: string;
  full_truth: string;
  game_flow: Record<string, unknown>[];
  free_speech_limits: number[];
  character_scripts: Record<string, string>;
  character_data: CharacterGameData[];
  overview?: string;
  tags?: string;
  description?: string;
}

// === Asset progress (granular task tree) ===

export type AssetTaskStatus = "pending" | "running" | "complete" | "failed" | "skipped";

export interface AssetTask {
  id: string;
  label: string;
  status: AssetTaskStatus;
  reason?: string;
}

export interface AssetPhase {
  id: string;
  label: string;
  tech: string;
  model?: string;
  tasks: AssetTask[];
}

export interface AssetProgress {
  phases: AssetPhase[];
  isComplete: boolean;
}

// === Chat types ===

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  thinkingTip?: string;
}

// === Checkpoint / Time-travel types ===

export interface CheckpointInfo {
  checkpoint_id: string;
  current_step: string;
  next: string[];
  interrupt: EditorInterruptInfo | null;
  timestamp: string | null;
  state: EditorWorkflowState;
}
