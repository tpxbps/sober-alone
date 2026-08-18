import { useEffect, useState } from "react";
import { Check, ChevronDown, ChevronUp, RotateCcw } from "lucide-react";

export function PromptSection({
  promptUsed,
  onRegenerate,
  isLoading,
  hideRegenerate = false,
  editedPromptRef,
}: {
  promptUsed?: string;
  onRegenerate: (prompt?: string) => Promise<void>;
  isLoading: boolean;
  hideRegenerate?: boolean;
  editedPromptRef?: { current: string };
}) {
  const [showPrompt, setShowPrompt] = useState(true);
  const [promptEditing, setPromptEditing] = useState(false);
  const [promptDraft, setPromptDraft] = useState("");
  const [savedPrompt, setSavedPrompt] = useState<string | null>(null);

  // Sync edited prompt to ref so parent can access it
  useEffect(() => {
    if (editedPromptRef) {
      editedPromptRef.current = savedPrompt || "";
    }
  }, [savedPrompt, editedPromptRef]);

  if (!promptUsed) return null;

  return (
    <div className="border-b border-border/30">
      <div className="flex items-center justify-between px-4 py-2.5 bg-secondary/10">
        <button
          onClick={() => {
            if (!promptEditing) setShowPrompt(!showPrompt);
          }}
          className="flex items-center gap-2 text-sm font-medium hover:text-primary transition-colors"
        >
          <span>查看提示词</span>
          {showPrompt ? (
            <ChevronUp className="w-3.5 h-3.5" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5" />
          )}
        </button>
        {!promptEditing ? (
          <button
            onClick={() => {
              setPromptDraft(savedPrompt || promptUsed);
              setPromptEditing(true);
              setShowPrompt(true);
            }}
            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            编辑
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <button
              onClick={() => {
                setSavedPrompt(promptDraft);
                setPromptEditing(false);
              }}
              className="text-xs text-primary hover:text-primary/80 transition-colors font-medium"
            >
              完成
            </button>
            <button
              onClick={() => setPromptEditing(false)}
              className="text-xs text-muted-foreground hover:text-foreground transition-colors"
            >
              取消
            </button>
          </div>
        )}
      </div>
      {showPrompt && (
        <div className="h-48 flex flex-col">
          <div className="flex-1 min-h-0 px-4 pt-2">
            {promptEditing ? (
              <textarea
                value={promptDraft}
                onChange={(e) => setPromptDraft(e.target.value)}
                className="w-full h-full bg-transparent text-xs text-muted-foreground resize-none focus:outline-none border border-border/30 rounded-md p-2 scrollbar-thin"
              />
            ) : (
              <pre className="w-full h-full text-xs text-muted-foreground whitespace-pre-wrap break-words overflow-y-auto scrollbar-thin">
                {savedPrompt || promptUsed}
              </pre>
            )}
          </div>
          {!promptEditing && !hideRegenerate && (
            <div className="px-4 py-2">
              <button
                onClick={() => onRegenerate(savedPrompt || undefined)}
                disabled={isLoading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-xs disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <RotateCcw className="w-3 h-3" />
                重新生成
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// =============================================================================
// Shared LoadingButton
// =============================================================================

export function LoadingButton({
  isLoading,
  loadingText,
  onClick,
  label,
  className = "",
  disabled = false,
}: {
  isLoading: boolean;
  loadingText: string;
  onClick: () => void;
  label: string;
  className?: string;
  disabled?: boolean;
}) {
  return (
    <div className={className}>
      <button
        onClick={onClick}
        disabled={isLoading || disabled}
        className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors text-sm font-medium disabled:opacity-70 disabled:cursor-not-allowed"
      >
        {isLoading ? (
          <>
            <div className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
            {loadingText}
          </>
        ) : (
          <>
            <Check className="w-3.5 h-3.5" />
            {label}
          </>
        )}
      </button>
    </div>
  );
}
