import { useEffect, useState } from "react";
import {
  ArrowLeft,
  Sparkles,
  MessageCircle,
  Settings,
  Trash2,
  Pencil,
  Check,
  X,
} from "lucide-react";
import { AnimatePresence } from "framer-motion";
import { useEditorStore } from "@/stores/editorStore";
import { HorizontalTimeline } from "@/components/script-editor/HorizontalTimeline";
import { ContentPanel } from "@/components/script-editor/ContentPanel";
import { ChatPanel } from "@/components/script-editor/ChatPanel";
import { SettingsModal } from "@/components/SettingsModal";
import { editorApi } from "@/lib/editorApi";
import type { GameDataSections } from "@/types/editor";
import { WORKFLOW_PHASES, getPhaseFromStep } from "@/types/editor";

interface ScriptEditorPageProps {
  onBack: () => void;
}

export function ScriptEditorPage({ onBack }: ScriptEditorPageProps) {
  const {
    threadId,
    currentStep,
    isComplete,
    interruptInfo,
    isLoading,
    isStarting,
    error,
    scriptTitle,
    workflowState,
    assetProgress,
    convertProgress,
    startWorkflow,
    resumeWorkflow,
    restoreSession,
    openProgressStream,
    closeProgressStream,
    retryConvert,
    retryAsset: retryAssetStore,
    viewingCheckpoint,
    history,
    fetchHistory,
    viewCheckpoint,
    scriptId,
    reset,
    updateTitle,
  } = useEditorStore();

  const [showMobileChat, setShowMobileChat] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitleValue, setEditTitleValue] = useState("");

  // Restore session on mount
  useEffect(() => {
    restoreSession();
  }, [restoreSession]);

  // Fetch checkpoint history when workflow is active
  useEffect(() => {
    if (threadId) fetchHistory();
  }, [threadId, fetchHistory]);

  const handleStart = async (params: {
    user_idea: string;
    player_count: number;
    difficulty: number;
    num_clue_rounds: number;
  }) => {
    await startWorkflow(params);
  };

  const handleConfirm = async (content: string) => {
    await resumeWorkflow("confirm", content);
  };

  const handleConfirmGameData = async (gameDataSections: GameDataSections) => {
    await resumeWorkflow("confirm", undefined, undefined, gameDataSections);
  };

  const handleConfirmReviewFinal = async (
    content: string,
    humanReview: string
  ) => {
    await resumeWorkflow("confirm", content, undefined, undefined, humanReview);
  };

  const handleRegenerate = async (prompt?: string) => {
    await resumeWorkflow("regenerate", undefined, prompt);
  };

  const handleRegenerateReviewFinal = async (
    humanReview: string,
    prompt?: string
  ) => {
    await resumeWorkflow(
      "regenerate",
      undefined,
      prompt,
      undefined,
      humanReview
    );
  };

  const handleRetryAsset = async (taskId: string) => {
    await retryAssetStore(taskId);
  };

  const handleRetryConvert = async (taskId: string) => {
    await retryConvert(taskId);
  };

  const handleBackToLobby = () => {
    useEditorStore.getState().reset();
    onBack();
  };

  const handleDiscardScript = async () => {
    const sid = scriptId;
    reset();
    onBack();
    if (sid) {
      try {
        await editorApi.deleteScript(sid);
      } catch {
        // Cleanup best-effort
      }
    }
  };

  const handleTimelineNodeClick = (phaseIndex: number) => {
    const phase = WORKFLOW_PHASES[phaseIndex];
    if (!phase) return;

    // If clicking the current active phase, clear viewing to return to live state
    const currentPhase = getPhaseFromStep(currentStep || "init");
    if (phase.phase === currentPhase) {
      viewCheckpoint(null);
      return;
    }

    // Find the latest checkpoint matching this completed phase
    const cp = history.find((c) => {
      const cpPhase = getPhaseFromStep(c.current_step);
      return cpPhase === phase.phase;
    });
    if (cp) viewCheckpoint(cp);
  };

  const viewingPhase = viewingCheckpoint
    ? getPhaseFromStep(viewingCheckpoint.current_step)
    : null;

  return (
    <div className="h-screen bg-background flex flex-col overflow-hidden">
      {/* Header */}
      <header className="shrink-0 border-b border-border/50 bg-background/80 backdrop-blur-xl">
        <div className="lg:max-w-[70%] w-full mx-auto px-3 py-3 flex items-center gap-3">
          <button
            onClick={onBack}
            className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <Sparkles size={28} className="sparkles-fancy shrink-0" />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-1.5">
              {isEditingTitle ? (
                <div className="flex items-center gap-1 flex-1 min-w-0">
                  <input
                    type="text"
                    value={editTitleValue}
                    onChange={(e) => setEditTitleValue(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        const trimmed = editTitleValue.trim();
                        if (trimmed) {
                          updateTitle(trimmed);
                        }
                        setIsEditingTitle(false);
                      } else if (e.key === "Escape") {
                        setIsEditingTitle(false);
                      }
                    }}
                    autoFocus
                    maxLength={20}
                    className="text-lg font-bold bg-transparent border-b border-primary/50 outline-none w-full max-w-xs"
                  />
                  <button
                    onClick={() => {
                      const trimmed = editTitleValue.trim();
                      if (trimmed) {
                        updateTitle(trimmed);
                      }
                      setIsEditingTitle(false);
                    }}
                    className="p-1 rounded hover:bg-secondary/50 transition-colors shrink-0"
                    title="确认"
                  >
                    <Check className="w-3.5 h-3.5 text-green-500" />
                  </button>
                  <button
                    onClick={() => setIsEditingTitle(false)}
                    className="p-1 rounded hover:bg-secondary/50 transition-colors shrink-0"
                    title="取消"
                  >
                    <X className="w-3.5 h-3.5 text-muted-foreground" />
                  </button>
                </div>
              ) : (
                <>
                  <h1 className="text-lg font-bold text-glow truncate">
                    {threadId && scriptTitle ? scriptTitle : "剧本创作工坊"}
                  </h1>
                  {threadId && scriptTitle && !isComplete && (() => {
                    const phase = getPhaseFromStep(currentStep || "init");
                    return phase !== "game_data" && phase !== "assets";
                  })() && (
                    <button
                      onClick={() => {
                        setEditTitleValue(scriptTitle);
                        setIsEditingTitle(true);
                      }}
                      className="p-1 rounded hover:bg-secondary/50 transition-colors shrink-0 opacity-60 hover:opacity-100"
                      title="修改标题"
                    >
                      <Pencil className="w-3.5 h-3.5" />
                    </button>
                  )}
                </>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              AI-Native的完整游戏源数据构建工作流 · 快来创作你的专属剧本吧
            </p>
          </div>
          {threadId && !isComplete && (
            <div className="relative">
              <button
                onClick={() => setShowDiscardConfirm(!showDiscardConfirm)}
                className="p-2 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0"
                title="放弃此剧本"
              >
                <Trash2 className="w-4 h-4" />
              </button>
              {showDiscardConfirm && (
                <div className="absolute right-0 top-full mt-1 w-56 bg-background border border-border/50 rounded-lg shadow-xl p-3 z-50">
                  <p className="text-xs text-muted-foreground mb-2">
                    确认放弃此剧本？已生成的所有资源将被清除。
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setShowDiscardConfirm(false)}
                      className="flex-1 px-3 py-1.5 text-xs rounded-md bg-secondary hover:bg-secondary/80 transition-colors"
                    >
                      取消
                    </button>
                    <button
                      onClick={handleDiscardScript}
                      className="flex-1 px-3 py-1.5 text-xs rounded-md bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors font-medium"
                    >
                      确认放弃
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
          <button
            onClick={() => setShowSettings(true)}
            className="p-2 rounded-lg hover:bg-secondary/50 transition-colors shrink-0"
            title="设置"
          >
            <Settings className="w-5 h-5" />
          </button>
        </div>
      </header>

      {/* Horizontal Timeline */}
      <div className="shrink-0 border-b border-border/30 overflow-x-auto scrollbar-thin">
        <div className="lg:max-w-[70%] w-full mx-auto px-3">
          <HorizontalTimeline
            currentStep={currentStep || "init"}
            isComplete={isComplete}
            onNodeClick={handleTimelineNodeClick}
            viewingPhase={viewingPhase}
          />
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 flex min-h-0 lg:max-w-[70%] w-full mx-auto px-3">
        {/* Left: Content Panel — 60% on desktop, full on mobile */}
        <div className="lg:w-[60%] w-full min-w-0 border-r border-border/30 flex flex-col">
          <div className="flex-1 min-h-0 overflow-y-auto">
            <ContentPanel
              interruptInfo={interruptInfo}
              currentStep={currentStep || "init"}
              isComplete={isComplete}
              isLoading={isLoading}
              isStarting={isStarting}
              error={error}
              scriptTitle={scriptTitle}
              workflowState={workflowState}
              assetProgress={assetProgress}
              convertProgress={convertProgress}
              onConfirm={handleConfirm}
              onConfirmGameData={handleConfirmGameData}
              onConfirmReviewFinal={handleConfirmReviewFinal}
              onRegenerate={handleRegenerate}
              onRegenerateReviewFinal={handleRegenerateReviewFinal}
              onStart={handleStart}
              onOpenProgressStream={openProgressStream}
              onCloseProgressStream={closeProgressStream}
              onBack={handleBackToLobby}
              onRetryAsset={handleRetryAsset}
              onRetryConvert={handleRetryConvert}
              viewingCheckpoint={viewingCheckpoint}
            />
          </div>
          <div className="shrink-0 px-4 pb-2 text-sm text-muted-foreground/50 leading-relaxed">
            「不诱于誉，不恐于诽，率道而行，端然正己。」 剧本创作工作流全程由{" "}
            <code className="text-muted-foreground/70">deepseek-v4-flash</code>{" "}
            稳定执行。
          </div>
        </div>

        {/* Right: Chat Panel — 40%, desktop only */}
        <div className="w-[40%] shrink-0 hidden lg:block">
          <ChatPanel threadId={threadId} />
        </div>
      </div>

      {/* Floating AI chat button — mobile/tablet only */}
      <button
        onClick={() => setShowMobileChat(!showMobileChat)}
        className="lg:hidden fixed bottom-20 right-6 z-50 w-12 h-12 rounded-full bg-primary text-primary-foreground shadow-lg flex items-center justify-center hover:bg-primary/90 transition-colors"
      >
        <MessageCircle className="w-5 h-5" />
      </button>

      {/* Mobile chat tooltip */}
      {showMobileChat && (
        <div
          className="lg:hidden fixed right-4 z-50 w-80 rounded-xl border border-border/50 bg-background shadow-2xl overflow-hidden"
          style={{ bottom: "8.5rem", height: "420px" }}
        >
          <ChatPanel
            threadId={threadId}
            onClose={() => setShowMobileChat(false)}
          />
        </div>
      )}

      {/* Settings Modal — editor mode: only BGM */}
      <AnimatePresence>
        {showSettings && (
          <SettingsModal onClose={() => setShowSettings(false)} mode="editor" />
        )}
      </AnimatePresence>
    </div>
  );
}
