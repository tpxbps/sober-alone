import { useEditorStore } from "@/stores/editorStore";
import { useEffect, useState } from "react";
import { AlertTriangle, Check } from "lucide-react";
import { WhackAMole, MoleTrigger } from "./WhackAMole";
import {
  AssetGenerationProgress,
  ConvertProgressPanel,
} from "./WorkflowProgressPanel";
import { getPhaseFromStep } from "@/types/editor";
import type {
  EditorInterruptInfo,
  EditorWorkflowState,
  AssetProgress,
  GameDataSections,
} from "@/types/editor";
import { getButtonLoadingMessage } from "./editorMessages";
import { ReviewReportStage } from "./ReviewReportStage";
import { QualityReviewStage } from "./QualityReviewStage";
import { ReviewFinalStage } from "./ReviewFinalStage";
import { ReviewGameDataStage } from "./ReviewGameDataStage";
import { CheckpointView } from "./CheckpointView";
import { IdeaStage } from "./IdeaStage";
import { cloneGameDataSections, workflowDraftKey } from "./contentDrafts";
import { DefaultReviewStage } from "./DefaultReviewStage";
import { AssetPlanDialog } from "./AssetPlanDialog";
import { useTextDraft } from "./useTextDraft";

// === Props ===

interface ContentPanelProps {
  interruptInfo: EditorInterruptInfo | null;
  currentStep: string;
  isComplete: boolean;
  isLoading: boolean;
  isStarting: boolean;
  error: string | null;
  scriptTitle: string;
  workflowState: EditorWorkflowState | null;
  assetProgress: AssetProgress | null;
  convertProgress: AssetProgress | null;
  viewingCheckpoint: import("@/types/editor").CheckpointInfo | null;
  onConfirm: (content: string) => Promise<void>;
  onConfirmGameData: (gameDataSections: GameDataSections) => Promise<void>;
  onConfirmAssetPlan: (selectedIds: string[]) => Promise<void>;
  onConfirmReviewFinal: (content: string, humanReview: string) => Promise<void>;
  onRegenerate: (prompt?: string) => Promise<void>;
  onRegenerateReviewFinal: (
    humanReview: string,
    prompt?: string
  ) => Promise<void>;
  onStart: (params: {
    user_idea: string;
    player_count: number;
    difficulty: number;
    num_clue_rounds: number;
    ending_mode?: "single" | "multiple";
  }) => void;
  onOpenProgressStream?: () => void;
  onCloseProgressStream?: () => void;
  onBack: () => void;
  onRetryAsset: (taskId: string) => Promise<void>;
  onRetryConvert: () => Promise<void>;
}

export function ContentPanel({
  interruptInfo,
  currentStep,
  isComplete,
  isLoading,
  isStarting,
  error,
  scriptTitle,
  workflowState,
  assetProgress,
  convertProgress,
  onConfirm,
  onConfirmGameData,
  onConfirmAssetPlan,
  onConfirmReviewFinal,
  onRegenerate,
  onRegenerateReviewFinal,
  onStart,
  onBack,
  onRetryAsset,
  onRetryConvert,
  viewingCheckpoint,
}: ContentPanelProps) {
  const draftKey = workflowDraftKey(
    currentStep,
    interruptInfo,
    viewingCheckpoint?.checkpoint_id
  );

  return (
    <ContentPanelBody
      key={draftKey}
      interruptInfo={interruptInfo}
      currentStep={currentStep}
      isComplete={isComplete}
      isLoading={isLoading}
      isStarting={isStarting}
      error={error}
      scriptTitle={scriptTitle}
      workflowState={workflowState}
      assetProgress={assetProgress}
      convertProgress={convertProgress}
      onConfirm={onConfirm}
      onConfirmGameData={onConfirmGameData}
      onConfirmAssetPlan={onConfirmAssetPlan}
      onConfirmReviewFinal={onConfirmReviewFinal}
      onRegenerate={onRegenerate}
      onRegenerateReviewFinal={onRegenerateReviewFinal}
      onStart={onStart}
      onBack={onBack}
      onRetryAsset={onRetryAsset}
      onRetryConvert={onRetryConvert}
      viewingCheckpoint={viewingCheckpoint}
    />
  );
}

function ContentPanelBody({
  interruptInfo,
  currentStep,
  isComplete,
  isLoading,
  isStarting,
  error,
  scriptTitle,
  workflowState,
  assetProgress,
  convertProgress,
  onConfirm,
  onConfirmGameData,
  onConfirmAssetPlan,
  onConfirmReviewFinal,
  onRegenerate,
  onRegenerateReviewFinal,
  onStart,
  onBack,
  onRetryAsset,
  onRetryConvert,
  viewingCheckpoint,
}: ContentPanelProps) {
  const phase = getPhaseFromStep(currentStep);
  const isIdeaPhase = phase === "idea" && !interruptInfo;
  const isReviewFinal = currentStep === "review_final" && !!interruptInfo;
  const isReviewGameData =
    currentStep === "review_game_data" && !!interruptInfo;
  const safetyProgress = useEditorStore((state) => state.safetyProgress);
  const isSafetyRejected =
    interruptInfo?.step === "safety_check" && interruptInfo?.rejected === true;
  const isReviewAssetPlan =
    currentStep === "review_asset_plan" && !!interruptInfo?.asset_plan;
  // Check if convert/asset progress has incomplete tasks (failed or running)
  const convertHasIncomplete = !!convertProgress?.phases?.some((p) =>
    p.tasks?.some((t) => !["complete", "skipped"].includes(t.status))
  );
  const assetHasIncomplete = !!assetProgress?.phases?.some((p) =>
    p.tasks?.some((t) => !["complete", "skipped"].includes(t.status))
  );
  // Check for failures specifically (used to block completion screen)
  const assetHasFailures = !!assetProgress?.phases?.some((p) =>
    p.tasks?.some((t) => t.status === "failed")
  );

  const isConvertProgress =
    (isLoading && currentStep === "convert_to_game_data") ||
    (convertHasIncomplete && currentStep === "convert_to_game_data");
  const isAssetGeneration =
    (isLoading &&
      (currentStep === "generate_assets" ||
        currentStep === "save_to_database")) ||
    (assetHasIncomplete &&
      (currentStep === "generate_assets" ||
        currentStep === "save_to_database"));

  // Idea form state
  const [userIdea, setUserIdea] = useState("");
  const [playerCount, setPlayerCount] = useState(4);
  const [difficulty, setDifficulty] = useState(1);
  const [numClueRounds, setNumClueRounds] = useState(2);
  const [endingMode, setEndingMode] = useState<"single" | "multiple">("single");

  // Global mole game (decoupled from buttons)
  const [showMoleGame, setShowMoleGame] = useState(false);
  const isWorking =
    (isLoading || isStarting) && !isComplete && !isSafetyRejected;
  const moleActive = isWorking && !showMoleGame;

  // Content editing state
  const [editing, setEditing] = useState(false);
  const [editedContent, setEditedContent] = useState("");


  // Game data review state
  const gameDataSource = interruptInfo?.game_data_sections || workflowState?.game_data_sections;
  const [editedGameData, setEditedGameData] = useTextDraft<GameDataSections | null>(
    "review_game_data", JSON.stringify(gameDataSource || null), cloneGameDataSections(gameDataSource)
  );

  // Pre-fill idea form from workflowState (after rewind to idea phase)
  /* eslint-disable react-hooks/set-state-in-effect -- workflow rewind hydrates the idea form */
  useEffect(() => {
    if (isIdeaPhase && workflowState) {
      if (workflowState.user_idea) setUserIdea(workflowState.user_idea);
      if (workflowState.player_count)
        setPlayerCount(workflowState.player_count);
      if (workflowState.difficulty) setDifficulty(workflowState.difficulty);
      setEndingMode(workflowState.ending_mode || "single");
      if (workflowState.num_clue_rounds)
        setNumClueRounds(workflowState.num_clue_rounds);
    }
  }, [isIdeaPhase, workflowState]);

  /* eslint-enable react-hooks/set-state-in-effect */

  // SSE progress stream is now managed by the store (opened before POST, closed on done/error)
  // No longer using useEffect to avoid timing gap between POST and SSE connection

  // === Main content ===
  // hasActionBar: whether current view has a bottom action bar (for mole trigger padding)
  const hasActionBar =
    !!viewingCheckpoint ||
    isIdeaPhase ||
    isReviewFinal ||
    isReviewGameData ||
    isReviewAssetPlan ||
    (interruptInfo &&
      !isComplete &&
      !isSafetyRejected &&
      !isConvertProgress &&
      !isAssetGeneration);

  const content = (() => {
    // === Viewing historical checkpoint (also shown during fork loading) ===
    if (viewingCheckpoint) {
      return (
        <CheckpointView
          viewingCheckpoint={viewingCheckpoint}
          error={error}
          moleActive={moleActive}
        />
      );
    }

    if (isLoading && currentStep === "safety_check") {
      return <div className="h-full flex flex-col items-center justify-center gap-4">
        <div className="w-10 h-10 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <p>正在审查全部剧本内容{safetyProgress ? `（${safetyProgress.completed} / ${safetyProgress.total}）` : ""}</p>
      </div>;
    }

    // === Terminal workflow error (for example, database save failure) ===
    if (workflowState?.error_message && !isLoading) {
      return (
        <div className="h-full flex flex-col items-center justify-center gap-4 p-6">
          <div className="w-14 h-14 rounded-full bg-red-500/20 flex items-center justify-center">
            <AlertTriangle className="w-7 h-7 text-red-500" />
          </div>
          <h3 className="text-lg font-bold">剧本创建失败</h3>
          <div className="w-full max-w-md p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
            <p className="text-sm text-red-400 whitespace-pre-wrap">
              {workflowState.error_message}
            </p>
          </div>
          {interruptInfo?.failed && <button onClick={() => onRegenerate()} className="px-6 py-2 rounded-lg bg-primary text-primary-foreground">重试</button>}
          <button
            onClick={onBack}
            className="mt-2 px-6 py-2.5 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-sm"
          >
            返回剧本大厅
          </button>
        </div>
      );
    }

    // === Idea Phase: Show form ===
    if (isIdeaPhase) {
      return (
        <IdeaStage
          userIdea={userIdea}
          setUserIdea={setUserIdea}
          playerCount={playerCount}
          setPlayerCount={setPlayerCount}
          difficulty={difficulty}
          setDifficulty={setDifficulty}
          endingMode={endingMode}
          setEndingMode={setEndingMode}
          numClueRounds={numClueRounds}
          setNumClueRounds={setNumClueRounds}
          error={error}
          isStarting={isStarting}
          onStart={onStart}
          moleActive={moleActive}
        />
      );
    }

    // === Complete === (but not if asset generation has failures)
    if (isComplete && !assetHasFailures) {
      return (
        <div className="h-full flex flex-col items-center justify-center gap-4 p-6">
          <div className="w-14 h-14 rounded-full bg-green-500/20 flex items-center justify-center">
            <Check className="w-7 h-7 text-green-500" />
          </div>
          <h3 className="text-lg font-bold">
            {workflowState?.workflow_mode === "edit" ? "剧本修改完成！" : "剧本创建完成！"}
          </h3>
          <p className="text-muted-foreground text-center text-sm max-w-sm">
            剧本「{scriptTitle}」已保存为最新版本，你可以返回剧本大厅开始新对局。
          </p>
          <button
            onClick={onBack}
            className="w-full max-w-sm mt-2 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors text-sm"
          >
            返回剧本大厅
          </button>
        </div>
      );
    }

    // === Safety Check Rejection ===
    if (isSafetyRejected) {
      return (
        <div className="h-full flex flex-col items-center justify-center gap-4 p-6">
          <div className="w-14 h-14 rounded-full bg-red-500/20 flex items-center justify-center">
            <AlertTriangle className="w-7 h-7 text-red-500" />
          </div>
          <h3 className="text-lg font-bold">内容安全审查未通过</h3>
          <div className="w-full max-w-md p-4 bg-red-500/10 border border-red-500/20 rounded-lg">
            <p className="text-sm text-red-400 whitespace-pre-wrap">
              {interruptInfo.reason || "内容未通过安全审查"}
            </p>
          </div>
          <p className="text-xs text-muted-foreground text-center max-w-sm">
            请注意：剧本创作的前提是符合社会主义核心价值观，内容需遵守中国法律法规。
            请修改相关内容后重新提交。
          </p>
          <button
            onClick={() => onRegenerate()}
            className="mt-2 px-6 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors text-sm"
          >
            返回修改
          </button>
        </div>
      );
    }

    // === Convert Progress (multi-step LLM calls) ===
    if (isConvertProgress) {
      return (
        <ConvertProgressPanel
          convertProgress={convertProgress}
          onRetry={onRetryConvert}
        />
      );
    }

    // === Asset Generation Progress (task tree) ===
    if (isAssetGeneration) {
      return (
        <AssetGenerationProgress
          assetProgress={assetProgress}
          onRetry={onRetryAsset}
        />
      );
    }

    if (currentStep === "review_report" && interruptInfo) {
      return <ReviewReportStage interruptInfo={interruptInfo} workflowState={workflowState}
        isLoading={isLoading} onConfirm={onConfirmReviewFinal} onRegenerate={onRegenerateReviewFinal} error={error} />;
    }
    if (currentStep === "review_quality" && interruptInfo?.quality_report) {
      return <QualityReviewStage key={interruptInfo.quality_report.report_id} report={interruptInfo.quality_report} isLoading={isLoading} error={error} />;
    }

    // === Review Final Draft ===
    if (isReviewFinal) {
      return (
        <ReviewFinalStage
          interruptInfo={interruptInfo}
          workflowState={workflowState}
          isLoading={isLoading}
          onConfirm={onConfirmReviewFinal}
          onRegenerate={onRegenerateReviewFinal}
          error={error}
        />
      );
    }

    // === Review Game Data ===
    if (isReviewGameData) {
      return (
        <ReviewGameDataStage
          editedGameData={editedGameData}
          setEditedGameData={setEditedGameData}
          isLoading={isLoading}
          currentStep={currentStep}
          onConfirmGameData={onConfirmGameData}
          interruptInfo={interruptInfo}
          error={error}
          scriptTitle={scriptTitle}
          workflowState={workflowState}
          moleActive={moleActive}
        />
      );
    }

    if (isReviewAssetPlan) {
      return (
        <AssetPlanDialog
          items={interruptInfo?.asset_plan || []}
          isLoading={isLoading}
          onConfirm={onConfirmAssetPlan}
        />
      );
    }

    // === Default content review/edit (outline, first draft) ===
    if (!interruptInfo) {
      return (
        <div className="h-full flex flex-col items-center justify-center gap-4 p-6">
          {isLoading || isStarting ? (
            <>
              <div className="w-10 h-10 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              <p className="text-sm text-muted-foreground">
                {getButtonLoadingMessage(currentStep)}
              </p>
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                流程中断，当前阶段：{currentStep || "未知"}
              </p>
              <button
                onClick={onBack}
                className="px-4 py-2 rounded-lg bg-secondary hover:bg-secondary/80 transition-colors text-sm"
              >
                返回大厅重新开始
              </button>
            </>
          )}
        </div>
      );
    }

    return (
      <DefaultReviewStage
        interruptInfo={interruptInfo}
        editedContent={editedContent}
        setEditedContent={setEditedContent}
        editing={editing}
        setEditing={setEditing}
        isLoading={isLoading}
        currentStep={currentStep}
        error={error}
        onConfirm={onConfirm}
        onRegenerate={onRegenerate}
        moleActive={moleActive}
      />
    );
  })();

  // === Shared return with mole game trigger ===
  return (
    <div className="h-full relative">
      {content}
      {isWorking && !showMoleGame && (
        <div className="absolute bottom-3 left-3 z-50 flex max-w-[calc(100%-1.5rem)] flex-col items-start gap-2">
          <div className="flex items-center gap-1.5">
            <MoleTrigger onClick={() => setShowMoleGame(true)} />
            {!hasActionBar && (
              <span className="text-xs text-muted-foreground whitespace-nowrap">
                等累了？来玩打地鼠吧 ~
              </span>
            )}
          </div>
        </div>
      )}
      {isWorking && showMoleGame && (
        <>
          <div className="hidden lg:block fixed bottom-4 left-4 z-50">
            <WhackAMole
              onClose={() => setShowMoleGame(false)}
              isModal={false}
            />
          </div>
          <div className="lg:hidden">
            <WhackAMole onClose={() => setShowMoleGame(false)} isModal={true} />
          </div>
        </>
      )}
    </div>
  );
}
