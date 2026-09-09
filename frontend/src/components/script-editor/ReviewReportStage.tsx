import { useRef, useState } from "react";
import { Markdown } from "@/components/ui/Markdown";
import type { EditorInterruptInfo, EditorWorkflowState } from "@/types/editor";
import { PromptSection } from "./EditorControls";
import { useTextDraft } from "./useTextDraft";

export function ReviewReportStage({ interruptInfo, workflowState, isLoading, onConfirm, onRegenerate, error }: {
  interruptInfo: EditorInterruptInfo; workflowState: EditorWorkflowState | null; isLoading: boolean;
  onConfirm: (content: string, human: string) => Promise<void>;
  onRegenerate: (human: string, prompt?: string) => Promise<void>; error: string | null;
}) {
  const [draft, setDraft] = useTextDraft("review_report", interruptInfo.generated_content, {
    opinion: interruptInfo.generated_content, human: interruptInfo.human_review ?? workflowState?.human_review ?? "",
  });
  const [showDraft, setShowDraft] = useState(false);
  const prompt = useRef("");
  return <div className="h-full flex flex-col">
    {error && <p role="alert" className="p-3 text-sm text-red-400">{error}</p>}
    <PromptSection promptUsed={interruptInfo.prompt_used} isLoading={isLoading} hideRegenerate
      editedPromptRef={prompt} onRegenerate={(value) => onRegenerate(draft.human, value)} />
    <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
      <div className="flex items-center justify-between gap-3">
        <div><h3 className="font-medium">审稿意见</h3><p className="text-xs text-muted-foreground mt-1">修改并确认意见后，再据此生成终稿。</p></div>
        <button type="button" aria-expanded={showDraft} onClick={() => setShowDraft(!showDraft)}
          className="text-xs text-primary shrink-0">{showDraft ? "收起初稿" : "展开初稿"}</button>
      </div>
      {showDraft && <section aria-label="初稿全文" className="max-h-80 overflow-y-auto rounded-lg border border-border p-4">
        <Markdown>{interruptInfo.first_draft || workflowState?.first_draft || "暂无初稿"}</Markdown>
      </section>}
      <div className="grid grid-cols-1 xl:grid-cols-[2fr_1fr] gap-4">
        <label className="flex flex-col gap-2 text-sm">AI 审稿意见（可编辑）
          <textarea aria-label="AI 审稿意见" value={draft.opinion} disabled={isLoading}
            onChange={(e) => setDraft({ ...draft, opinion: e.target.value })}
            className="w-full min-h-80 rounded-lg border border-border bg-secondary/20 p-3 text-sm resize-y" />
        </label>
        <label className="flex flex-col gap-2 text-sm">补充审稿意见（可选）
          <textarea aria-label="补充审稿意见" value={draft.human} disabled={isLoading}
            onChange={(e) => setDraft({ ...draft, human: e.target.value })} placeholder="补充你希望保留、修正或加强的内容…"
            className="w-full min-h-40 xl:min-h-80 rounded-lg border border-border bg-secondary/20 p-3 text-sm resize-y" />
        </label>
      </div>
    </div>
    <div className="border-t border-border p-3 flex flex-wrap gap-2">
      <button disabled={isLoading} onClick={() => onRegenerate(draft.human, prompt.current || undefined)} className="px-4 py-2.5 rounded-lg bg-secondary disabled:opacity-50">重新审稿</button>
      <button disabled={isLoading || !draft.opinion.trim()} onClick={() => onConfirm(draft.opinion, draft.human)}
        className="flex-1 px-4 py-2.5 rounded-lg bg-primary text-primary-foreground disabled:opacity-50">{isLoading ? "处理中…" : "确认意见并生成终稿"}</button>
    </div>
  </div>;
}
