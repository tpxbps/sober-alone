import { Markdown } from "@/components/ui/Markdown";
import { getPhaseFromStep, WORKFLOW_PHASES } from "@/types/editor";
import type { CheckpointInfo, GameDataSections } from "@/types/editor";

export function CheckpointView({
  viewingCheckpoint,
  error,
  moleActive,
}: {
  viewingCheckpoint: CheckpointInfo;
  error: string | null;
  moleActive: boolean;
}) {
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

