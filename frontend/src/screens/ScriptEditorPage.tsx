import { useEffect, useRef, useState } from "react";
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
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { Dialog, DialogTrigger, DialogContent, DialogTitle, DialogDescription, DialogClose } from "@/components/ui/dialog";
import { OutlineWorkspace } from "@/components/script-editor/OutlineWorkspace";
import { useEditorStore } from "@/stores/editorStore";
import { HorizontalTimeline } from "@/components/script-editor/HorizontalTimeline";
import { ContentPanel } from "@/components/script-editor/ContentPanel";
import { WorkflowFooterMessage } from "@/components/script-editor/WorkflowFooterMessage";
import { ChatPanel } from "@/components/script-editor/ChatPanel";
import { SettingsModal } from "@/components/SettingsModal";
import { editorApi } from "@/lib/editorApi";
import type { GameDataSections } from "@/types/editor";
import { WORKFLOW_PHASES, getPhaseFromStep } from "@/types/editor";

interface ScriptEditorPageProps {
  onBack: () => void;
  editScriptId?: string | null;
}

export function ScriptEditorPage({ onBack, editScriptId }: ScriptEditorPageProps) {
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
    startEditWorkflow,
    resumeWorkflow,
    restoreSession,
    openProgressStream,
    closeProgressStream,
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
  const reducedMotion = useReducedMotion();
  const [desktop, setDesktop] = useState(() => window.matchMedia("(min-width: 1024px)").matches);
  const [assistantDismissed, setAssistantDismissed] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(min-width: 1024px)");
    const update = () => setDesktop(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  const ideaLayout = !threadId && !isStarting;
  const assistantDocked = ideaLayout && desktop && !assistantDismissed && !showMobileChat;
  const outlineActive = !viewingCheckpoint && !editScriptId && (
    isStarting ||
    (["init", ""].includes(currentStep) || getPhaseFromStep(currentStep) === "outline") && Boolean(workflowState?.outline_session)
  );
  const [showSettings, setShowSettings] = useState(false);
  const [showDiscardConfirm, setShowDiscardConfirm] = useState(false);
  const [isEditingTitle, setIsEditingTitle] = useState(false);
  const [editTitleValue, setEditTitleValue] = useState("");
  const initializationRef = useRef<string | null>(null);
  useEffect(() => {
    if (!showMobileChat) return;
    const close = (event: KeyboardEvent) => { if (event.key === "Escape") setShowMobileChat(false); };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [showMobileChat]);

  // Restore session on mount
  useEffect(() => {
    const target = editScriptId ? `edit:${editScriptId}` : "restore";
    if (initializationRef.current === target) return;
    initializationRef.current = target;
    if (editScriptId) void startEditWorkflow(editScriptId);
    else void restoreSession();
  }, [editScriptId, restoreSession, startEditWorkflow]);

  // Fetch checkpoint history when workflow is active
  useEffect(() => {
    if (threadId) fetchHistory();
  }, [threadId, fetchHistory]);

  const handleStart = async (params: {
    user_idea: string;
    player_count: number;
    difficulty: number;
    num_clue_rounds: number;
    ending_mode?: "single" | "multiple";
  }) => {
    setShowMobileChat(false);
    await startWorkflow(params);
  };

  const handleConfirm = async (content: string) => {
    await resumeWorkflow("confirm", content);
  };

  const handleConfirmGameData = async (gameDataSections: GameDataSections) => {
    await resumeWorkflow("confirm", undefined, undefined, gameDataSections);
  };

  const handleConfirmAssetPlan = async (selectedIds: string[]) => {
    await resumeWorkflow(
      "confirm",
      undefined,
      undefined,
      undefined,
      undefined,
      selectedIds
    );
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

  const handleRetryConvert = async () => {
    await resumeWorkflow("regenerate");
  };

  const handleBackToLobby = () => {
    // The back arrow pauses the UI only. The durable background operation and
    // local resume pointer must survive so the user can continue later.
    closeProgressStream();
    viewCheckpoint(null);
    if (!threadId || isComplete) reset();
    onBack();
  };

  const handleDiscardScript = async () => {
    const sid = scriptId;
    const editingExisting = workflowState?.workflow_mode === "edit";
    reset();
    onBack();
    if (sid && !editingExisting) {
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
        <div className="max-w-[1320px] w-full mx-auto px-3 py-3 flex items-center gap-3">
          <button
            onClick={handleBackToLobby}
            aria-label="返回剧本大厅"
            title={threadId && !isComplete ? "返回大厅，稍后可继续" : "返回剧本大厅"}
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
            <Dialog open={showDiscardConfirm} onOpenChange={setShowDiscardConfirm}>
              <DialogTrigger asChild>
                <button className="p-2 rounded-lg hover:bg-destructive/10 text-muted-foreground hover:text-destructive transition-colors shrink-0" title="放弃此剧本" aria-label="放弃此剧本">
                  <Trash2 className="w-4 h-4" />
                </button>
              </DialogTrigger>
              <DialogContent className="z-[120] sm:max-w-sm" showCloseButton={false}>
                <DialogTitle>{workflowState?.workflow_mode === "edit" ? "退出编辑" : "放弃此剧本"}</DialogTitle>
                <DialogDescription>{workflowState?.workflow_mode === "edit"
                  ? "尚未确认保存的修改将被放弃，原剧本不会被删除。"
                  : "确认放弃此剧本？已生成的所有资源将被清除。"}</DialogDescription>
                <div className="flex justify-end gap-2">
                  <DialogClose asChild><button className="rounded-md bg-secondary px-4 py-2 text-sm">取消</button></DialogClose>
                  <button onClick={() => { setShowDiscardConfirm(false); void handleDiscardScript(); }} className="rounded-md bg-destructive px-4 py-2 text-sm text-destructive-foreground">确认放弃</button>
                </div>
              </DialogContent>
            </Dialog>
          )}
          <button
            aria-label="创作小助手"
            aria-expanded={assistantDocked || showMobileChat}
            onClick={() => { if (assistantDocked) setAssistantDismissed(true); else setShowMobileChat(!showMobileChat); }}
            className="p-2 rounded-lg hover:bg-secondary/50 text-primary shrink-0"
          >
            <MessageCircle className="w-5 h-5" />
          </button>
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
        <div className="max-w-[1320px] w-full mx-auto px-3">
          <HorizontalTimeline
            currentStep={currentStep || "init"}
            isComplete={isComplete}
            onNodeClick={handleTimelineNodeClick}
            viewingPhase={viewingPhase}
            workflowMode={workflowState?.workflow_mode || "create"}
          />
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 flex min-h-0 max-w-[1320px] w-full mx-auto px-3 relative">
        {/* Left: Content Panel — 60% on desktop, full on mobile */}
        <motion.div layout transition={{ duration: reducedMotion ? 0 : 0.25 }} className={`w-full min-w-0 flex flex-col ${assistantDocked ? "lg:mr-[380px]" : ""}`}>
          <div className="flex-1 min-h-0 overflow-y-auto">
            {outlineActive ? <OutlineWorkspace key={threadId || "starting"} threadId={threadId} /> : <ContentPanel
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
              onConfirmAssetPlan={handleConfirmAssetPlan}
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
            />}
          </div>
          {!outlineActive && <div className="min-h-7 shrink-0 px-4 pb-2 text-sm text-muted-foreground/50 leading-relaxed">
            <WorkflowFooterMessage
              key={isLoading || isStarting ? `working:${currentStep}` : "idle"}
              isWorking={isLoading || isStarting}
            />
          </div>}
        </motion.div>
        <motion.aside
          initial={false}
          animate={{ opacity: assistantDocked || showMobileChat ? 1 : 0, scale: assistantDocked || showMobileChat ? 1 : 0.92,
                     y: assistantDocked || showMobileChat ? 0 : -16 }}
          transition={{ duration: reducedMotion ? 0 : 0.25 }}
          style={{ transformOrigin: "top right" }}
          aria-hidden={!assistantDocked && !showMobileChat}
          inert={!assistantDocked && !showMobileChat}
          onKeyDown={event => { if (event.key === "Escape") setShowMobileChat(false); }}
          className={`border border-border/50 bg-background overflow-hidden
            ${assistantDocked ? "hidden lg:block absolute right-3 top-0 bottom-0 w-[360px] border-y-0 border-r-0"
              : "fixed right-4 top-20 z-50 h-[min(620px,calc(100dvh-6rem))] w-[400px] max-w-[calc(100vw-2rem)] rounded-2xl shadow-2xl"}
            ${!assistantDocked && !showMobileChat ? "pointer-events-none" : ""}`}
        >
          <div role="dialog" aria-label="创作小助手" className="h-full">
            <ChatPanel threadId={threadId} onClose={() => { setShowMobileChat(false); setAssistantDismissed(true); }} />
          </div>
        </motion.aside>
      </div>

      {/* Settings Modal — editor mode: only BGM */}
      <AnimatePresence>
        {showSettings && (
          <SettingsModal onClose={() => setShowSettings(false)} mode="editor" />
        )}
      </AnimatePresence>
    </div>
  );
}
