import { useState, useEffect, useCallback } from "react";
import {
  Check,
  RotateCcw,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  Pencil,
} from "lucide-react";
import { WhackAMole, MoleTrigger } from "./WhackAMole";
import {
  AssetGenerationProgress,
  ConvertProgressPanel,
} from "./WorkflowProgressPanel";
import { getPhaseFromStep, WORKFLOW_PHASES } from "@/types/editor";
import type {
  EditorInterruptInfo,
  EditorWorkflowState,
  AssetProgress,
  GameDataSections,
} from "@/types/editor";
import { Markdown } from "@/components/ui/Markdown";

// === Loading message for buttons ===
function getButtonLoadingMessage(step: string): string {
  const messages: Record<string, string> = {
    generate_outline: "正在构思剧本大纲...",
    generate_first_draft: "正在撰写初稿...",
    review_by_llm: "AI正在审阅...",
    generate_final_draft: "正在生成终稿...",
    convert_to_game_data: "正在转化游戏数据...",
    safety_check: "正在进行剧本合规检查...",
    save_to_database: "正在保存...",
  };
  return messages[step] || "处理中...";
}

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
  }) => void;
  onOpenProgressStream?: () => void;
  onCloseProgressStream?: () => void;
  onBack: () => void;
  onRetryAsset: (taskId: string) => Promise<void>;
  onRetryConvert: (taskId: string) => Promise<void>;
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
  const isSafetyRejected =
    interruptInfo?.step === "safety_check" && interruptInfo?.rejected === true;
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

  // Global mole game (decoupled from buttons)
  const [showMoleGame, setShowMoleGame] = useState(false);
  const isWorking =
    (isLoading || isStarting) && !isComplete && !isSafetyRejected;
  const moleActive = isWorking && !showMoleGame;

  // Content editing state
  const [editing, setEditing] = useState(false);
  const [editedContent, setEditedContent] = useState("");

  // Review final state
  const [humanReview, setHumanReview] = useState("");
  const [finalDraftEdit, setFinalDraftEdit] = useState("");
  const [editingFinalDraft, setEditingFinalDraft] = useState(false);

  // Game data review state
  const [editedGameData, setEditedGameData] = useState<GameDataSections | null>(
    null
  );

  // Reset editing state when interrupt info changes (new step)
  /* eslint-disable react-hooks/set-state-in-effect -- checkpoint identity resets local drafts */
  useEffect(() => {
    setEditing(false);
    setEditedContent("");
    setHumanReview("");
    setFinalDraftEdit("");
    setEditingFinalDraft(false);
    setEditedGameData(null);
  }, [interruptInfo]);

  // Pre-fill idea form from workflowState (after rewind to idea phase)
  useEffect(() => {
    if (isIdeaPhase && workflowState) {
      if (workflowState.user_idea) setUserIdea(workflowState.user_idea);
      if (workflowState.player_count)
        setPlayerCount(workflowState.player_count);
      if (workflowState.difficulty) setDifficulty(workflowState.difficulty);
      if (workflowState.num_clue_rounds)
        setNumClueRounds(workflowState.num_clue_rounds);
    }
  }, [isIdeaPhase, workflowState]);

  // Initialize game data from interrupt, with fallback to workflowState
  useEffect(() => {
    if (isReviewGameData && !editedGameData) {
      const source =
        interruptInfo?.game_data_sections || workflowState?.game_data_sections;
      if (
        source &&
        (source.opening || source.character_scripts || source.game_flow?.length)
      ) {
        setEditedGameData(source);
      }
    }
  }, [isReviewGameData, interruptInfo, workflowState, editedGameData]);

  // Initialize final draft from interrupt
  useEffect(() => {
    if (isReviewFinal && interruptInfo?.generated_content && !finalDraftEdit) {
      setFinalDraftEdit(interruptInfo.generated_content);
    }
  }, [isReviewFinal, interruptInfo, finalDraftEdit]);
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
    (interruptInfo &&
      !isComplete &&
      !isSafetyRejected &&
      !isConvertProgress &&
      !isAssetGeneration);

  const content = (() => {
    // === Viewing historical checkpoint (also shown during fork loading) ===
    if (viewingCheckpoint) {
      const cpState = viewingCheckpoint.state;
      const cpInterrupt = viewingCheckpoint.interrupt;
      const cpPhase = getPhaseFromStep(viewingCheckpoint.current_step);
      const phaseLabel =
        WORKFLOW_PHASES.find((p) => p.phase === cpPhase)?.label ||
        viewingCheckpoint.current_step;

      return (
        <div className="h-full flex flex-col">
          <div className="px-4 py-2.5 border-b border-border/30 bg-primary/10">
            <span className="text-sm font-medium text-primary">
              历史记录 — {phaseLabel}
            </span>
            <p className="text-xs text-muted-foreground mt-0.5">
              查看该节点已完成的历史数据。点击当前阶段的时间线节点可返回。
            </p>
          </div>
          <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin p-4">
            {cpPhase === "idea" ? (
              <div className="space-y-3">
                {cpState?.user_idea ? (
                  <div>
                    <h4 className="text-xs font-medium text-primary mb-1">
                      创意描述
                    </h4>
                    <p className="text-sm whitespace-pre-wrap bg-secondary/30 rounded-lg p-3">
                      {cpState.user_idea}
                    </p>
                  </div>
                ) : null}
                <div className="grid grid-cols-3 gap-3">
                  <div className="bg-secondary/20 rounded-lg p-2.5">
                    <p className="text-[10px] text-muted-foreground">
                      玩家人数
                    </p>
                    <p className="text-sm font-medium">
                      {cpState?.player_count || "?"}人
                    </p>
                  </div>
                  <div className="bg-secondary/20 rounded-lg p-2.5">
                    <p className="text-[10px] text-muted-foreground">难度</p>
                    <p className="text-sm font-medium">
                      {
                        ["简单", "中等", "困难", "极难"][
                          (cpState?.difficulty || 1) - 1
                        ]
                      }
                    </p>
                  </div>
                  <div className="bg-secondary/20 rounded-lg p-2.5">
                    <p className="text-[10px] text-muted-foreground">
                      线索轮次
                    </p>
                    <p className="text-sm font-medium">
                      {cpState?.num_clue_rounds || "?"}轮
                    </p>
                  </div>
                </div>
                {cpState?.outline ? (
                  <div>
                    <h4 className="text-xs font-medium text-primary mb-1">
                      已生成大纲
                    </h4>
                    <Markdown className="text-sm">{cpState.outline}</Markdown>
                  </div>
                ) : null}
                {!cpState?.user_idea && !cpState?.outline ? (
                  <p className="text-sm text-muted-foreground">无可展示内容</p>
                ) : null}
              </div>
            ) : cpPhase === "first_draft" &&
              !cpInterrupt?.generated_content &&
              cpState?.first_draft ? (
              <>
                <h4 className="text-xs font-medium text-primary mb-2">初稿</h4>
                <Markdown className="text-sm">{cpState.first_draft}</Markdown>
              </>
            ) : cpPhase === "review_final" &&
              !cpInterrupt?.generated_content ? (
              <div className="space-y-3">
                {cpState?.review_opinion ? (
                  <div>
                    <h4 className="text-xs font-medium text-primary mb-1">
                      AI 审稿意见
                    </h4>
                    <Markdown className="text-sm">
                      {cpState.review_opinion}
                    </Markdown>
                  </div>
                ) : null}
                {cpState?.final_draft ? (
                  <div>
                    <h4 className="text-xs font-medium text-primary mb-1">
                      终稿
                    </h4>
                    <Markdown className="text-sm">
                      {cpState.final_draft}
                    </Markdown>
                  </div>
                ) : null}
                {!cpState?.review_opinion && !cpState?.final_draft ? (
                  <p className="text-sm text-muted-foreground">无可展示内容</p>
                ) : null}
              </div>
            ) : cpPhase === "game_data" &&
              !cpInterrupt?.generated_content &&
              cpState?.game_data_sections ? (
              (() => {
                const gds = cpState!.game_data_sections as GameDataSections;
                const charData = (gds.character_data || []) as Array<{
                  name?: string;
                  gender?: string;
                  age?: number;
                  occupation?: string;
                  profile?: string;
                  system_prompt?: string;
                  appearance?: string;
                }>;
                const gameFlow = gds.game_flow || [];
                return (
                  <div className="space-y-3">
                    {/* Overview & metadata */}
                    <div className="grid grid-cols-2 gap-3">
                      {gds.overview ? (
                        <div className="col-span-2">
                          <h4 className="text-sm font-semibold text-primary mb-2">
                            剧本概述
                          </h4>
                          <p className="text-sm">{gds.overview}</p>
                        </div>
                      ) : null}
                      {gds.tags ? (
                        <div>
                          <h4 className="text-sm font-semibold text-primary mb-2">
                            标签
                          </h4>
                          <p className="text-sm">{gds.tags}</p>
                        </div>
                      ) : null}
                      {gds.opening ? (
                        <div className="col-span-2">
                          <h4 className="text-sm font-semibold text-primary mb-2">
                            开场消息
                          </h4>
                          <Markdown className="text-sm">{gds.opening}</Markdown>
                        </div>
                      ) : null}
                    </div>

                    {/* Character list */}
                    {charData.length > 0 ? (
                      <div>
                        <h4 className="text-sm font-semibold text-primary mb-2">
                          角色（{charData.length}人）
                        </h4>
                        <div className="space-y-2">
                          {charData.map((cd, i) => (
                            <div
                              key={i}
                              className="bg-secondary/20 rounded-lg p-2.5"
                            >
                              <div className="flex items-center gap-2 mb-1">
                                <span className="text-sm font-medium">
                                  {cd.name}
                                </span>
                                <span className="text-[10px] text-muted-foreground">
                                  {cd.gender} · {cd.age}岁 · {cd.occupation}
                                </span>
                              </div>
                              {cd.profile ? (
                                <p className="text-xs text-muted-foreground">
                                  {cd.profile}
                                </p>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    {/* Game flow summary */}
                    {gameFlow.length > 0 ? (
                      <div>
                        <h4 className="text-sm font-semibold text-primary mb-2">
                          游戏流程（{gameFlow.length}个阶段）
                        </h4>
                        <div className="space-y-1">
                          {gameFlow.map(
                            (stage: Record<string, unknown>, i: number) => {
                              const type = stage.type as string;
                              const title =
                                (stage.stage_title as string) || type;
                              const children = stage.children as
                                | Array<Record<string, unknown>>
                                | undefined;
                              return (
                                <div
                                  key={i}
                                  className="flex items-center gap-2 text-xs"
                                >
                                  <span className="text-muted-foreground/50">
                                    {i + 1}.
                                  </span>
                                  <span className="font-medium">{title}</span>
                                  <span className="text-muted-foreground/50">
                                    ({type}
                                    {children
                                      ? ` · ${children.length}子阶段`
                                      : ""}
                                    )
                                  </span>
                                </div>
                              );
                            }
                          )}
                        </div>
                      </div>
                    ) : null}

                    {/* Character scripts */}
                    {gds.character_scripts &&
                    typeof gds.character_scripts === "object" &&
                    Object.keys(gds.character_scripts).length > 0 ? (
                      <div>
                        <h4 className="text-sm font-semibold text-primary mb-2">
                          角色个人剧本
                        </h4>
                        <div className="space-y-2">
                          {Object.entries(gds.character_scripts).map(
                            ([name, script]) => (
                              <div key={name}>
                                <span className="text-xs font-medium">
                                  {name}
                                </span>
                                <span className="text-[10px] text-muted-foreground ml-1">
                                  {typeof script === "string"
                                    ? `${script.length}字`
                                    : ""}
                                </span>
                              </div>
                            )
                          )}
                        </div>
                      </div>
                    ) : null}

                    {/* Truth */}
                    {gds.truth_reveal || gds.full_truth ? (
                      <div>
                        <h4 className="text-sm font-semibold text-primary mb-2">
                          真相揭晓
                        </h4>
                        <Markdown className="text-sm">
                          {gds.truth_reveal || gds.full_truth || ""}
                        </Markdown>
                      </div>
                    ) : null}

                    {!gds.overview &&
                    !gds.opening &&
                    charData.length === 0 &&
                    gameFlow.length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        无可展示内容
                      </p>
                    ) : null}
                  </div>
                );
              })()
            ) : cpInterrupt?.generated_content ? (
              <Markdown className="text-sm">
                {cpInterrupt.generated_content}
              </Markdown>
            ) : cpState?.outline ? (
              <>
                <h4 className="text-xs font-medium text-primary mb-2">大纲</h4>
                <Markdown className="text-sm">{cpState.outline}</Markdown>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">无可展示内容</p>
            )}
          </div>
          {error && (
            <div className="px-4 py-2 bg-red-500/10 border-t border-red-500/20 text-red-400 text-xs">
              {error}
            </div>
          )}
          <div
            className={`p-3 ${
              moleActive ? "pl-12" : ""
            } border-t border-border/30`}
          />
        </div>
      );
    }

    // === Idea Phase: Show form ===
    if (isIdeaPhase) {
      return (
        <div className="h-full flex flex-col">
          <div className="p-5 flex-1 overflow-y-auto scrollbar-thin">
            <h3 className="text-lg font-bold mb-4">构思你的剧本</h3>
            <p className="text-xs text-muted-foreground mb-4">
              描述你的剧本创意、故事背景、核心设定等。越详细，AI生成的大纲越贴合你的想法。
            </p>
            <textarea
              value={userIdea}
              onChange={(e) => setUserIdea(e.target.value)}
              placeholder="描述你想要创作的剧本杀故事构想。可以包含：故事背景、人物关系、核心冲突、悬疑元素等。例如：一所与世隔绝的山间别墅中，六位受邀而来的客人发现主人离奇失踪，暴风雪封山之夜，他们必须找出真相……"
              className="w-full h-[30vh] px-4 py-3 rounded-lg border border-border/50 bg-card text-sm resize-none focus:outline-none focus:border-primary/50 transition-colors placeholder:text-muted-foreground/50 scrollbar-thin"
            />
            <div className="grid grid-cols-3 gap-3 mt-4">
              <div>
                <label className="block text-xs font-medium mb-1">
                  玩家人数
                </label>
                <select
                  value={playerCount}
                  onChange={(e) => setPlayerCount(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg border border-border/50 bg-card text-sm focus:outline-none focus:border-primary/50"
                >
                  {[3, 4, 5, 6, 7, 8].map((n) => (
                    <option key={n} value={n}>
                      {n}人
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium mb-1">难度</label>
                <select
                  value={difficulty}
                  onChange={(e) => setDifficulty(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg border border-border/50 bg-card text-sm focus:outline-none focus:border-primary/50"
                >
                  {[
                    { v: 1, l: "简单" },
                    { v: 2, l: "中等" },
                    { v: 3, l: "困难" },
                    { v: 4, l: "极难" },
                  ].map((d) => (
                    <option key={d.v} value={d.v}>
                      {d.l}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium mb-1">
                  线索轮次
                </label>
                <select
                  value={numClueRounds}
                  onChange={(e) => setNumClueRounds(Number(e.target.value))}
                  className="w-full px-3 py-1.5 rounded-lg border border-border/50 bg-card text-sm focus:outline-none focus:border-primary/50"
                >
                  {[1, 2, 3, 4, 5].map((n) => (
                    <option key={n} value={n}>
                      {n}轮
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <p className="text-xs text-muted-foreground/60 mt-3">
              预估游戏时长：
              {estimateDuration(playerCount, difficulty, numClueRounds)}
            </p>
            {error && <p className="text-red-400 text-sm mt-3">{error}</p>}
          </div>
          <div
            className={`p-4 ${
              moleActive ? "pl-12" : ""
            } border-t border-border/30`}
          >
            <LoadingButton
              isLoading={isStarting}
              loadingText="正在构思剧本大纲..."
              onClick={() =>
                onStart({
                  user_idea: userIdea,
                  player_count: playerCount,
                  difficulty,
                  num_clue_rounds: numClueRounds,
                })
              }
              label="开始创作"
              disabled={!userIdea.trim()}
            />
          </div>
        </div>
      );
    }

    // === Complete === (but not if asset generation has failures)
    if (isComplete && !assetHasFailures) {
      return (
        <div className="h-full flex flex-col items-center justify-center gap-4 p-6">
          <div className="w-14 h-14 rounded-full bg-green-500/20 flex items-center justify-center">
            <Check className="w-7 h-7 text-green-500" />
          </div>
          <h3 className="text-lg font-bold">剧本创建完成！</h3>
          <p className="text-muted-foreground text-center text-sm max-w-sm">
            剧本「{scriptTitle}」已成功创建，你可以在剧本大厅找到它并开始游戏。
          </p>
          <button
            onClick={onBack}
            className="w-full max-w-sm mt-2 py-2.5 rounded-lg bg-primary text-primary-foreground font-medium hover:bg-primary/90 transition-colors text-sm"
          >
            创作结单，返回大厅
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

    // === Review Final Draft ===
    if (isReviewFinal) {
      return (
        <ReviewFinalStage
          interruptInfo={interruptInfo}
          workflowState={workflowState}
          humanReview={humanReview}
          setHumanReview={setHumanReview}
          finalDraftEdit={finalDraftEdit}
          setFinalDraftEdit={setFinalDraftEdit}
          editingFinalDraft={editingFinalDraft}
          setEditingFinalDraft={setEditingFinalDraft}
          isLoading={isLoading}
          currentStep={currentStep}
          onConfirm={onConfirmReviewFinal}
          onRegenerate={onRegenerateReviewFinal}
          error={error}
          moleActive={moleActive}
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

    // === Default content review/edit (outline, first draft) ===
    if (!interruptInfo) {
      return (
        <div className="h-full flex flex-col items-center justify-center gap-4 p-6">
          {isLoading ? (
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

    const displayContent = editing
      ? editedContent
      : editedContent || interruptInfo.generated_content;

    return (
      <div className="h-full flex flex-col">
        {/* Error banner */}
        {error && (
          <div className="px-4 py-2 bg-red-500/10 border-b border-red-500/20 text-red-400 text-xs">
            {error}
          </div>
        )}

        {/* Prompt section */}
        <PromptSection
          promptUsed={interruptInfo.prompt_used}
          onRegenerate={onRegenerate}
          isLoading={isLoading}
        />

        {/* Content review section */}
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border/30 bg-secondary/10">
            <span className="text-sm font-medium">
              {interruptInfo.step_label}
            </span>
            {!editing ? (
              <button
                onClick={() => {
                  setEditedContent(
                    editedContent || interruptInfo.generated_content
                  );
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
                    setEditedContent("");
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
                value={editedContent}
                onChange={(e) => setEditedContent(e.target.value)}
                className="w-full h-full bg-transparent text-sm resize-none focus:outline-none scrollbar-thin"
              />
            ) : (
              <Markdown className="text-sm">
                {displayContent || interruptInfo.generated_content}
              </Markdown>
            )}
          </div>
        </div>

        {/* Action bar */}
        <div
          className={`p-3 ${
            moleActive ? "pl-12" : ""
          } border-t border-border/30`}
        >
          <LoadingButton
            isLoading={isLoading}
            loadingText={getButtonLoadingMessage(currentStep)}
            onClick={() => onConfirm(editing ? editedContent : displayContent)}
            label="确认并继续"
          />
        </div>
      </div>
    );
  })();

  // === Shared return with mole game trigger ===
  return (
    <div className="h-full relative">
      {content}
      {isWorking && !showMoleGame && (
        <div className="absolute bottom-3 left-0 z-50 flex items-center gap-1.5 pl-3">
          <MoleTrigger onClick={() => setShowMoleGame(true)} />
          {!hasActionBar && (
            <span className="text-xs text-muted-foreground whitespace-nowrap">
              等累了？来玩打地鼠吧 ~
            </span>
          )}
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

// =============================================================================
// Shared PromptSection (reused in default review, ReviewFinal, ReviewGameData)
// =============================================================================

function PromptSection({
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

function LoadingButton({
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

// =============================================================================
// Review Final Stage (Issue 1 — added prompt section)
// =============================================================================

function ReviewFinalStage({
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
  const editedPromptRef = { current: "" };

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

// =============================================================================
// Review Game Data Stage (Issue 1 — added prompt section)
// =============================================================================

function ReviewGameDataStage({
  editedGameData,
  setEditedGameData,
  isLoading,
  currentStep,
  onConfirmGameData,
  interruptInfo,
  error,
  scriptTitle,
  workflowState,
  moleActive,
}: {
  editedGameData: GameDataSections | null;
  setEditedGameData: (v: GameDataSections | null) => void;
  isLoading: boolean;
  currentStep: string;
  onConfirmGameData: (gameDataSections: GameDataSections) => Promise<void>;
  interruptInfo: EditorInterruptInfo;
  error: string | null;
  scriptTitle: string;
  workflowState: EditorWorkflowState | null;
  moleActive: boolean;
}) {
  const [expandedSections, setExpandedSections] = useState<
    Record<string, boolean>
  >({
    metadata: false,
    flow: false,
    character_scripts: false,
    character_data: false,
  });

  const [editingCharName, setEditingCharName] = useState<number | null>(null);
  const [editedCharName, setEditedCharName] = useState("");

  const toggleSection = (key: string) => {
    setExpandedSections((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const updateField = useCallback(
    (path: string[], value: string) => {
      if (!editedGameData) return;
      const updated = JSON.parse(
        JSON.stringify(editedGameData)
      ) as GameDataSections;
      let target: unknown = updated;
      for (let i = 0; i < path.length - 1; i++) {
        target = (target as Record<string, unknown>)[path[i]];
      }
      const lastKey = path[path.length - 1];
      if (typeof target === "object" && target !== null) {
        (target as Record<string, unknown>)[lastKey] = value;
      }
      setEditedGameData(updated);
    },
    [editedGameData, setEditedGameData]
  );

  if (!editedGameData) {
    return (
      <div className="h-full flex items-center justify-center">
        <p className="text-sm text-muted-foreground">加载中...</p>
      </div>
    );
  }

  // Flatten game_flow into sequential messages
  const flowMessages: { label: string; path: string[] }[] = [];
  const gameFlow = editedGameData.game_flow || [];
  for (let i = 0; i < gameFlow.length; i++) {
    const stage = gameFlow[i] as Record<string, unknown>;
    const type = stage.type as string;
    if (type === "initial" || type === "review") {
      flowMessages.push({
        label: (stage.stage_title as string) || type,
        path: ["game_flow", String(i), "system_notice"],
      });
    } else if (type === "advancement" || type === "vote") {
      const children = (stage.children as Record<string, unknown>[]) || [];
      for (let j = 0; j < children.length; j++) {
        flowMessages.push({
          label: (children[j].stage_title as string) || `${type}-${j}`,
          path: [
            "game_flow",
            String(i),
            "children",
            String(j),
            "system_notice",
          ],
        });
      }
    }
  }

  const difficultyLabels = ["简单", "中等", "困难", "极难"];

  const resolveValue = (path: string[]): string => {
    let target: unknown = editedGameData;
    for (const key of path) {
      if (target == null || typeof target !== "object") return "";
      target = (target as Record<string, unknown>)[key];
    }
    return typeof target === "string" ? target : "";
  };

  return (
    <div className="h-full flex flex-col">
      {error && (
        <div className="px-4 py-2 bg-red-500/10 border-b border-red-500/20 text-red-400 text-xs">
          {error}
        </div>
      )}

      <div className="px-4 py-2.5 border-b border-border/30 bg-secondary/10">
        <span className="text-sm font-medium">{interruptInfo.step_label}</span>
        <p className="text-xs text-muted-foreground mt-0.5">
          检查并编辑生成的结构化游戏数据
        </p>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-thin">
        {/* Metadata section */}
        <CollapsibleSection
          title="剧本元数据"
          expanded={expandedSections.metadata ?? false}
          onToggle={() => toggleSection("metadata")}
        >
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-0.5">
                  剧本名称
                </label>
                <p className="text-xs text-foreground">
                  {scriptTitle || "未命名"}
                </p>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-0.5">
                  玩家人数
                </label>
                <p className="text-xs text-foreground">
                  {workflowState?.player_count || "?"}人
                </p>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-0.5">
                  难度
                </label>
                <p className="text-xs text-foreground">
                  {difficultyLabels[(workflowState?.difficulty || 1) - 1] ||
                    "简单"}
                </p>
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">
                概述
              </label>
              <textarea
                value={editedGameData.overview || ""}
                onChange={(e) => updateField(["overview"], e.target.value)}
                className="w-full h-16 text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                placeholder="100-200字的游戏简介"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">
                标签
              </label>
              <textarea
                value={editedGameData.tags || ""}
                onChange={(e) => updateField(["tags"], e.target.value)}
                className="w-full h-10 text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50"
                placeholder="标签1, 标签2, 标签3"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">
                详细描述
              </label>
              <textarea
                value={editedGameData.description || ""}
                onChange={(e) => updateField(["description"], e.target.value)}
                className="w-full h-50 text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                placeholder="剧本详细描述"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-muted-foreground mb-1">
                完整真相
              </label>
              <textarea
                value={editedGameData.full_truth || ""}
                onChange={(e) => updateField(["full_truth"], e.target.value)}
                className="w-full text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                style={{ minHeight: "30vh" }}
              />
            </div>
          </div>
        </CollapsibleSection>

        {/* Flow data section */}
        <CollapsibleSection
          title="剧本流程数据"
          expanded={expandedSections.flow ?? false}
          onToggle={() => toggleSection("flow")}
        >
          <div className="space-y-3">
            {flowMessages.map((msg, idx) => (
              <div key={idx}>
                <label className="block text-xs font-medium text-primary mb-1">
                  {msg.label}
                </label>
                <textarea
                  value={resolveValue(msg.path)}
                  onChange={(e) => updateField(msg.path, e.target.value)}
                  className="w-full h-50 text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                />
              </div>
            ))}
          </div>
        </CollapsibleSection>

        {/* Character scripts section */}
        <CollapsibleSection
          title="角色个人剧本"
          expanded={expandedSections.character_scripts ?? false}
          onToggle={() => toggleSection("character_scripts")}
        >
          <div className="space-y-3">
            {editedGameData.character_scripts &&
              Object.entries(editedGameData.character_scripts).map(
                ([name, script]) => (
                  <div key={name}>
                    <label className="block text-xs font-medium text-primary mb-1">
                      {name}
                    </label>
                    <textarea
                      value={script || ""}
                      onChange={(e) =>
                        updateField(["character_scripts", name], e.target.value)
                      }
                      className="w-full text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                      style={{ minHeight: "30vh" }}
                    />
                  </div>
                )
              )}
          </div>
        </CollapsibleSection>

        {/* Character data section */}
        <CollapsibleSection
          title="角色数据"
          expanded={expandedSections.character_data ?? false}
          onToggle={() => toggleSection("character_data")}
        >
          <div className="space-y-4">
            {editedGameData.character_data?.map((cd, idx) => (
              <div
                key={cd.name || idx}
                className="border border-border/20 rounded-lg p-3 space-y-2"
              >
                <div className="flex items-center gap-2">
                  {editingCharName === idx ? (
                    <input
                      type="text"
                      value={editedCharName}
                      onChange={(e) => setEditedCharName(e.target.value)}
                      onBlur={() => {
                        if (editedCharName.trim()) {
                          updateField(
                            ["character_data", String(idx), "name"],
                            editedCharName.trim()
                          );
                        }
                        setEditingCharName(null);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          if (editedCharName.trim()) {
                            updateField(
                              ["character_data", String(idx), "name"],
                              editedCharName.trim()
                            );
                          }
                          setEditingCharName(null);
                        }
                      }}
                      autoFocus
                      className="text-xs font-medium text-primary bg-transparent border-b border-primary/50 focus:outline-none px-0.5 w-20"
                    />
                  ) : (
                    <div className="flex items-center gap-1">
                      <span className="text-xs font-medium text-primary">
                        {cd.name}
                      </span>
                      <button
                        onClick={() => {
                          setEditingCharName(idx);
                          setEditedCharName(cd.name || "");
                        }}
                        className="text-muted-foreground hover:text-primary transition-colors"
                      >
                        <Pencil className="w-3 h-3" />
                      </button>
                    </div>
                  )}
                  <span className="text-[10px] text-muted-foreground">
                    {cd.gender} · {cd.age}岁 · {cd.occupation}
                  </span>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-0.5">
                    人物简介
                  </label>
                  <textarea
                    value={cd.profile || ""}
                    onChange={(e) =>
                      updateField(
                        ["character_data", String(idx), "profile"],
                        e.target.value
                      )
                    }
                    className="w-full h-24 text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-0.5">
                    外貌描述
                  </label>
                  <textarea
                    value={cd.appearance || ""}
                    onChange={(e) =>
                      updateField(
                        ["character_data", String(idx), "appearance"],
                        e.target.value
                      )
                    }
                    className="w-full h-20 text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                  />
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-0.5">
                    系统提示词
                  </label>
                  <textarea
                    value={cd.system_prompt || ""}
                    onChange={(e) =>
                      updateField(
                        ["character_data", String(idx), "system_prompt"],
                        e.target.value
                      )
                    }
                    className="w-full h-40 text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                  />
                </div>
              </div>
            ))}
          </div>
        </CollapsibleSection>
      </div>

      {/* Action bar */}
      <div
        className={`p-3 ${moleActive ? "pl-12" : ""} border-t border-border/30`}
      >
        <LoadingButton
          isLoading={isLoading}
          loadingText={getButtonLoadingMessage(currentStep)}
          onClick={() => onConfirmGameData(editedGameData)}
          label="确认并保存"
          className="w-full"
        />
      </div>
    </div>
  );
}

// =============================================================================
// Collapsible Section
// =============================================================================

function CollapsibleSection({
  title,
  expanded,
  onToggle,
  children,
}: {
  title: string;
  expanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="border-b border-border/20 bg-secondary/15">
      <button
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-2.5 hover:bg-secondary/30 transition-colors"
      >
        <span className="text-sm font-medium">{title}</span>
        {expanded ? (
          <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
        )}
      </button>
      {expanded && <div className="px-4 pb-4 bg-background/50">{children}</div>}
    </div>
  );
}

// =============================================================================
// Utilities
// =============================================================================

function estimateDuration(
  players: number,
  difficulty: number,
  rounds: number
): string {
  const base = 15 + (players - 3) * 10;
  const diffMult = [1.0, 1.2, 1.5, 1.8][difficulty - 1] ?? 1.0;
  const total = Math.round(base * diffMult + (rounds - 1) * 15);
  const hours = Math.floor(total / 60);
  const mins = total % 60;
  if (hours > 0 && mins > 0) return `约${hours}小时${mins}分钟`;
  if (hours > 0) return `约${hours}小时`;
  return `约${mins}分钟`;
}
