import type { OutlineProgress, OutlineSession } from "./outline";
// Script Editor Types

export interface StepInfo {
  step: string;
  label: string;
  needs_review: boolean;
}

export interface QualityReport {
  report_id: string;
  content_fingerprint: string;
  status: "passed" | "warning" | "blocked" | "incomplete";
  error?: string;
  findings: Array<{ severity: "critical" | "major" | "minor"; field: string; evidence: string; impact: string; suggestion: string }>;
}

export interface EditorInterruptInfo {
  human_review?: string;
  first_draft?: string;
  quality_report?: QualityReport;
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
  workflow_mode?: "create" | "edit";
  asset_plan?: AssetPlanItem[];
  validation_errors?: string[];
}

export interface EditorWorkflowState {
  workflow_mode: "create" | "edit";
  script_title: string;
  script_id: string;
  user_idea: string;
  player_count: number;
  difficulty: number;
  num_clue_rounds: number;
  ending_mode?: "single" | "multiple";
  outline: string;
  outline_session?: OutlineSession | null;
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
  human_review?: string;
  quality_report?: QualityReport;
  final_draft: string;
  character_scripts: Record<string, string>;
  game_data_sections: GameDataSections;
  prompts: Record<string, string>;
  cover_image_url: string;
  character_avatars: Record<string, string>;
  error_message: string;
  safety_passed?: boolean;
  safety_rejection_reason?: string;
  data_validation_errors?: string[];
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

export interface EditorOperationAccepted {
  success: boolean;
  thread_id: string;
  operation_id: string;
  operation_status: 'queued' | 'running' | 'complete' | 'failed' | 'paused';
  target_step: string;
  progress?: { message?: string; percent?: number };
  error_message?: string;
}

export type EditorOperationResponse = EditorOperationAccepted &
  Partial<StartWorkflowResponse & ResumeWorkflowResponse>;

export interface WorkflowStateResponse {
  outline_progress?: OutlineProgress | null;
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
  { phase: "outline", label: "大纲共创", desc: "共同决定剧情方向，确认完整大纲", isAuto: false },
  { phase: "first_draft", label: "初稿创作", desc: "基于大纲撰写完整剧本初稿并审阅", isAuto: false },
  { phase: "review_report", label: "审稿意见", desc: "确认AI意见与真人补充", isAuto: false },
  { phase: "review_final", label: "终稿确认", desc: "编辑并确认完整终稿", isAuto: false },
  { phase: "game_data", label: "游戏数据", desc: "结构化数据确认与质量检查", isAuto: false },
  { phase: "assets", label: "资源生成", desc: "生成图片、语音、向量数据", isAuto: true },
];

export type WorkflowPhaseKey = (typeof WORKFLOW_PHASES)[number]["phase"];

// Map backend step name → display phase
export function getPhaseFromStep(step: string): WorkflowPhaseKey {
  if (!step || step === "init") return "idea";
  if (step === "generate_outline" || step === "review_outline" || step.startsWith("outline_")) return "outline";
  if (step === "generate_first_draft" || step === "review_first_draft")
    return "first_draft";
  if (step === "review_by_llm" || step === "review_report") return "review_report";
  if (
    step === "generate_final_draft" ||
    step === "review_final"
  )
    return "review_final";
  if (
    step === "convert_to_game_data" ||
    step === "review_game_data" ||
    step === "normalize_game_data" ||
    step === "check_game_quality" ||
    step === "review_quality" ||
    step === "safety_check"
  )
    return "game_data";
  if (
    step === "prepare_asset_plan" ||
    step === "review_asset_plan" ||
    step === "save_to_database" ||
    step === "generate_assets"
  )
    return "assets";
  return "idea";
}

// === Game data sections ===

export interface ClueStage {
  stage: number;
  overview: string;
  items: Array<{
    id: string;
    summary: string;
    content: string;
    stage: number;
  }>;
  free_discussion_notice: string;
}

export interface CharacterGameData {
  character_id: string;
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

export type EndingOutcome = "correct" | "incorrect" | "tie" | "no_votes";
export interface EndingConfig {
  mode: "multiple";
  culprit_character_id: string;
  branches: Array<{ when: EndingOutcome; title: string; text: string }>;
}

export interface GameDataSections {
  ending_config?: EndingConfig | null;
  title?: string;
  difficulty?: number;
  player_count?: number;
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

export interface AssetPlanItem {
  id: string;
  phase: "vectorize" | "image" | "tts";
  phase_label: string;
  label: string;
  changed: boolean;
  missing: boolean;
  available: boolean;
  unavailable_reason: string;
  default_selected: boolean;
  change_reason: string;
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
