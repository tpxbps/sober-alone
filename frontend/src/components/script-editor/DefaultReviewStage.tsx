import { Markdown } from "@/components/ui/Markdown";
import type { EditorInterruptInfo } from "@/types/editor";
import { LoadingButton, PromptSection } from "./EditorControls";
import { getButtonLoadingMessage } from "./editorMessages";
import { RefineButton } from './RefineButton';

export function DefaultReviewStage({
  interruptInfo,
  editedContent,
  setEditedContent,
  editing,
  setEditing,
  isLoading,
  currentStep,
  error,
  onConfirm,
  onRegenerate,
}: {
  interruptInfo: EditorInterruptInfo;
  editedContent: string;
  setEditedContent: (value: string) => void;
  editing: boolean;
  setEditing: (value: boolean) => void;
  isLoading: boolean;
  currentStep: string;
  error: string | null;
  onConfirm: (content: string) => Promise<void>;
  onRegenerate: (prompt?: string) => Promise<void>;
}) {
  const displayContent = editedContent;

  return (
    <div className="h-full flex flex-col">
      {error && (
        <div className="px-4 py-2 bg-red-500/10 border-b border-red-500/20 text-red-400 text-xs">
          {error}
        </div>
      )}

      <PromptSection
        promptUsed={interruptInfo.prompt_used}
        onRegenerate={onRegenerate}
        isLoading={isLoading}
        hideRegenerate
      />

      <div className="flex-1 min-h-0 flex flex-col">
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/30 bg-secondary/10">
          <span className="text-sm font-medium">{interruptInfo.step_label}</span>
          {!editing ? (
            <button
              onClick={() => {
                setEditing(true);
              }}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              编辑
            </button>
          ) : (
            <div className="flex items-center gap-3">
              <button
                onClick={() => setEditing(false)}
                className="text-xs text-primary hover:text-primary/80 transition-colors font-medium"
              >
                完成
              </button>
              <button
                onClick={() => {
                  setEditedContent(interruptInfo.generated_content);
                  setEditing(false);
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
            editing ? "overflow-hidden" : "overflow-y-auto scrollbar-thin"
          } p-4`}
        >
          {editing ? (
            <textarea
              disabled={isLoading}
              aria-label="剧本正文"
              value={editedContent}
              onChange={(event) => setEditedContent(event.target.value)}
              className="w-full h-full bg-transparent text-sm resize-none focus:outline-none scrollbar-thin"
            />
          ) : (
            <Markdown className="text-sm">
              {displayContent}
            </Markdown>
          )}
        </div>
      </div>

      <div
        className={`grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] items-center gap-2 p-3  border-t border-border/30`}
      >
        <RefineButton step={interruptInfo.step} content={displayContent} disabled={isLoading} />
        <LoadingButton
          isLoading={isLoading}
          loadingText={getButtonLoadingMessage(currentStep)}
          onClick={() => onConfirm(editing ? editedContent : displayContent)}
          label="确认并继续"
          disabled={!displayContent.trim()}
        />
      </div>
    </div>
  );
}
