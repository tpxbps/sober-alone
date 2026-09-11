export interface OutlineQuestion {
  id: string;
  title: string;
  question: string;
  options: Array<{ id: string; label: string; impact: string }>;
  recommended_option_id: string;
}
export interface OutlineDecision {
  source: "user" | "ai";
  choice: string;
  other_text: string;
  question?: OutlineQuestion;
  option_id?: string;
  segment_index?: number;
}
export interface OutlineSession {
  protocol_version: 2;
  revision: number;
  status: "writing" | "directing" | "awaiting_answer" | "finalizing" | "checking" | "ready" | "needs_revision";
  segments: Array<{ id: string; content: string }>;
  decisions: OutlineDecision[];
  pending_question: OutlineQuestion | null;
  questions_asked: number;
  questions_stopped?: boolean;
  final_outline?: string;
  check?: { passed: boolean; issues: string[] } | null;
}
export interface OutlineProgress {
  operation_id: string;
  operation_created_at?: string;
  revision: number;
  seq: number;
  session: OutlineSession;
  live: { segment_id: string; attempt: string; text: string } | null;
  control: { revision?: number; paused?: boolean; questions_stopped?: boolean };
  error?: string;
  metrics?: { calls: number; first_token_ms: number | null; first_question_ms: number | null };
}
export interface OutlineDelta {
  operation_id: string;
  operation_created_at?: string;
  revision: number;
  seq: number;
  segment_id: string;
  attempt: string;
  offset: number;
  text: string;
}
export interface OutlineCommand {
  action: "answer" | "pause" | "continue" | "stop_questions" | "rewrite" | "retry";
  request_id: string;
  expected_revision: number;
  question_id?: string;
  checkpoint_id?: string;
  option_id?: string;
  other_text?: string;
}
