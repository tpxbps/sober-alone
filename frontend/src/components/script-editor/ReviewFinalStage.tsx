import { useState } from "react";
import { Markdown } from "@/components/ui/Markdown";
import type { EditorInterruptInfo, EditorWorkflowState } from "@/types/editor";
import { useTextDraft } from "./useTextDraft";

export function ReviewFinalStage({ interruptInfo, workflowState, isLoading, onConfirm, onRegenerate, error }: {
  interruptInfo: EditorInterruptInfo; workflowState: EditorWorkflowState | null; isLoading: boolean;
  onConfirm: (content: string, human: string) => Promise<void>;
  onRegenerate: (human: string, prompt?: string) => Promise<void>; error: string | null;
}) {
  const [draft, setDraft] = useTextDraft("review_final", interruptInfo.generated_content, interruptInfo.generated_content);
  const [editing, setEditing] = useState(false);
  const human = workflowState?.human_review ?? "";
  return <div className="h-full flex flex-col">
    {error && <p role="alert" className="p-3 text-sm text-red-400">{error}</p>}
    <div className="p-4 border-b border-border flex justify-between items-center">
      <h3 className="font-medium">终稿</h3>
      <button disabled={isLoading} onClick={() => setEditing(!editing)} className="text-sm text-primary">{editing ? "预览" : "编辑终稿"}</button>
    </div>
    <div className="flex-1 min-h-0 overflow-y-auto p-4">
      {editing ? <textarea aria-label="终稿正文" value={draft} onChange={(e) => setDraft(e.target.value)} disabled={isLoading}
        className="w-full h-full min-h-64 bg-transparent resize-none text-sm focus:outline-none" /> : <Markdown className="text-sm">{draft}</Markdown>}
    </div>
    <div className="p-3 border-t border-border flex flex-wrap gap-2">
      <button disabled={isLoading} onClick={() => onRegenerate(human)} className="px-4 py-2.5 rounded-lg bg-secondary disabled:opacity-50">重新生成终稿</button>
      <button disabled={isLoading || !draft.trim()} onClick={() => onConfirm(draft, human)}
        className="flex-1 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground disabled:opacity-50">{isLoading ? "处理中…" : "确认终稿并拆分"}</button>
    </div>
  </div>;
}
