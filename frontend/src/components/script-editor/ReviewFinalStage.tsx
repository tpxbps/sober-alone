import { useRef } from "react";
import { RotateCcw } from "lucide-react";

import { Markdown } from "@/components/ui/Markdown";
import type { EditorInterruptInfo, EditorWorkflowState } from "@/types/editor";
import { LoadingButton, PromptSection } from "./EditorControls";
import { getButtonLoadingMessage } from "./editorMessages";

export function ReviewFinalStage({
  interruptInfo,
  workflowState,
  humanReview,
  setHumanReview,
  finalDraftEdit,
  setFinalDraftEdit,
  editingFinalDraft,
  setEditingFinalDraft,
  isLoading,
  currentStep,
  onConfirm,
  onRegenerate,
  error,
  moleActive,
}: {
  interruptInfo: EditorInterruptInfo;
  workflowState: EditorWorkflowState | null;
  humanReview: string;
  setHumanReview: (v: string) => void;
  finalDraftEdit: string;
  setFinalDraftEdit: (v: string) => void;
  editingFinalDraft: boolean;
  setEditingFinalDraft: (v: boolean) => void;
  isLoading: boolean;
  currentStep: string;
  onConfirm: (content: string, humanReview: string) => Promise<void>;
  onRegenerate: (humanReview: string, prompt?: string) => Promise<void>;
  error: string | null;
  moleActive: boolean;
}) {
  const reviewOpinion =
    interruptInfo.review_opinion || workflowState?.review_opinion || "";
  const editedPromptRef = useRef("");

  return (
    <div className="h-full flex flex-col">
      {error && (
        <div className="px-4 py-2 bg-red-500/10 border-b border-red-500/20 text-red-400 text-xs">
          {error}
        </div>
      )}

      {/* Prompt section (隐藏重新生成按钮，使用底部操作栏的重试) */}
      <PromptSection
        promptUsed={interruptInfo.prompt_used}
        onRegenerate={(prompt) => onRegenerate(humanReview, prompt)}
        isLoading={isLoading}
        hideRegenerate
        editedPromptRef={editedPromptRef}
      />

      {/* AI Review + Human Review — side by side, compact */}
      <div
        className="shrink-0 border-b border-border/30"
        style={{ maxHeight: "25vh" }}
      >
        <div className="grid grid-cols-2 divide-x divide-border/30 h-full">
          <div className="flex flex-col min-h-0 overflow-hidden">
            <div className="shrink-0 px-4 py-2 bg-primary/5 border-b border-border/20">
              <span className="text-xs font-medium text-primary">
                AI 审稿意见
              </span>
            </div>
            <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin p-4">
              {reviewOpinion ? (
                <Markdown className="text-xs text-muted-foreground">
                  {reviewOpinion}
                </Markdown>
              ) : (
                <p className="text-xs text-muted-foreground/50">暂无审稿意见</p>
              )}
            </div>
          </div>
          <div className="flex flex-col min-h-0 overflow-hidden">
            <div className="shrink-0 px-4 py-2 bg-secondary/10 border-b border-border/20">
              <span className="text-xs font-medium">我的审稿意见</span>
            </div>
            <div className="flex-1 min-h-0 p-3">
              <textarea
                value={humanReview}
                onChange={(e) => setHumanReview(e.target.value)}
                placeholder={
                  "评审结果：[通过/小修/大修/拒绝]\n\n逐条关键意见：\n1. ...\n2. ..."
                }
                className="w-full h-full text-xs bg-transparent resize-none focus:outline-none placeholder:text-muted-foreground/40 scrollbar-thin"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Final Draft */}
      <div className="flex-1 min-h-0 flex flex-col">
        <div className="flex items-center justify-between px-4 py-2 border-b border-border/30 bg-secondary/10">
          <span className="text-sm font-medium">终稿</span>
          {!editingFinalDraft ? (
            <button
              onClick={() => setEditingFinalDraft(true)}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              编辑
            </button>
          ) : (
            <div className="flex items-center gap-3">
              <button
                onClick={() => setEditingFinalDraft(false)}
                className="text-xs text-primary hover:text-primary/80 transition-colors font-medium"
              >
                完成
              </button>
              <button
                onClick={() => {
                  setFinalDraftEdit(interruptInfo.generated_content);
                  setEditingFinalDraft(false);
                }}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
              >
                取消
              </button>
            </div>
          )}
        </div>
        <div
          className={`flex-1 min-h-0 ${
            editingFinalDraft
              ? "overflow-hidden"
              : "overflow-y-auto scrollbar-thin"
          } p-4`}
        >
          {editingFinalDraft ? (
            <textarea
              value={finalDraftEdit}
              onChange={(e) => setFinalDraftEdit(e.target.value)}
              className="w-full h-full bg-transparent text-sm resize-none focus:outline-none scrollbar-thin"
            />
          ) : (
            <Markdown className="text-sm">
              {finalDraftEdit || interruptInfo.generated_content}
            </Markdown>
          )}
        </div>
      </div>

      {/* Action bar */}
      <div
        className={`p-3 ${
          moleActive ? "pl-12" : ""
        } border-t border-border/30 flex gap-2`}
      >
        <button
          onClick={() =>
            onRegenerate(humanReview, editedPromptRef.current || undefined)
          }
          disabled={isLoading}
          className="flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoading ? (
            <>
              <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
              处理中...
            </>
          ) : (
            <>
              <RotateCcw className="w-3.5 h-3.5" />
              重新生成
            </>
          )}
        </button>
        <LoadingButton
          isLoading={isLoading}
          loadingText={getButtonLoadingMessage(currentStep)}
          onClick={() =>
            onConfirm(
              editingFinalDraft
                ? finalDraftEdit
                : finalDraftEdit || interruptInfo.generated_content,
              humanReview
            )
          }
          label="确认并继续"
          className="flex-1"
        />
      </div>
    </div>
  );
}
