import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, ArrowDown, ArrowUp, ChevronDown, ChevronUp, CircleHelp, Pencil, Plus, Trash2 } from "lucide-react";
import * as Tooltip from "@radix-ui/react-tooltip";

import type {
  EditorInterruptInfo,
  EditorWorkflowState,
  GameDataSections,
} from "@/types/editor";
import { LoadingButton } from "./EditorControls";
import { getButtonLoadingMessage } from "./editorMessages";
import { STEP_VOICE_GROUPS, STEP_VOICE_OPTIONS } from "@/lib/stepVoices";
import { EndingEditor } from "./EndingEditor";

export function ReviewGameDataStage({
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
    clues: true,
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
    (path: string[], value: unknown) => {
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
  const flowMessages: { label: string; path: string[]; truthReveal?: boolean }[] = [];
  const gameFlow = editedGameData.game_flow || [];
  for (let i = 0; i < gameFlow.length; i++) {
    const stage = gameFlow[i] as Record<string, unknown>;
    const type = stage.type as string;
    if (type === "initial" || type === "review") {
      flowMessages.push({
        label: (stage.stage_title as string) || type,
        path: ["game_flow", String(i), "system_notice"],
        truthReveal: type === "review",
      });
    } else if (type === "vote") {
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

      {interruptInfo.rejected && (
        <div className="px-4 py-3 bg-amber-500/10 border-b border-amber-500/20 text-amber-300 text-xs flex gap-2">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <div>
            <p className="font-medium">内容安全审查未完成</p>
            <p className="mt-1 text-amber-200/80">
              {interruptInfo.reason || "请检查并修改内容后重新提交。"}
            </p>
          </div>
        </div>
      )}

      {!!interruptInfo.validation_errors?.length && (
        <div className="px-4 py-3 bg-red-500/10 border-b border-red-500/20 text-red-300 text-xs">
          <p className="font-medium mb-1">请修正以下结构化数据：</p>
          <ul className="list-disc pl-4 space-y-0.5">
            {interruptInfo.validation_errors.map((message) => (
              <li key={message}>{message}</li>
            ))}
          </ul>
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
                <input
                  value={editedGameData.title ?? scriptTitle ?? ""}
                  onChange={(event) => updateField(["title"], event.target.value)}
                  className="w-full text-xs bg-transparent border border-border/30 rounded-md p-2 focus:outline-none focus:border-primary/50"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-2.5">
                  玩家人数
                </label>
                <p className="text-xs text-foreground">
                  {editedGameData.player_count || workflowState?.player_count || "?"}人
                </p>
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-0.5">
                  难度
                </label>
                <select
                  value={editedGameData.difficulty ?? workflowState?.difficulty ?? 1}
                  onChange={(event) => updateField(["difficulty"], Number(event.target.value))}
                  className="w-full text-xs bg-background border border-border/30 rounded-md p-2"
                >
                  {difficultyLabels.map((label, index) => (
                    <option key={label} value={index + 1}>{label}</option>
                  ))}
                </select>
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

        <CollapsibleSection
          title="结构化公开线索"
          expanded={expandedSections.clues ?? true}
          onToggle={() => toggleSection("clues")}
        >
          <div className="space-y-4">
            {editedGameData.clue_stages.map((clueStage, stageIndex) => (
              <div key={clueStage.stage} className="rounded-lg border border-amber-300/15 bg-amber-300/[0.03] p-3">
                <div className="mb-3 flex items-center justify-between">
                  <span className="text-sm font-medium text-amber-200">第 {clueStage.stage} 轮</span>
                  <span className="text-[10px] text-muted-foreground">线索 ID 与所属轮次由系统维护</span>
                </div>
                <label className="block text-xs text-muted-foreground">
                  整体摘要总述
                  <textarea
                    value={clueStage.overview}
                    onChange={(event) => updateField(["clue_stages", String(stageIndex), "overview"], event.target.value)}
                    className="mt-1 h-20 w-full resize-none rounded-md border border-border/30 bg-transparent p-2 text-foreground focus:border-primary/50 focus:outline-none scrollbar-thin"
                  />
                </label>
                <div className="mt-3 space-y-3">
                  {clueStage.items.map((item, itemIndex) => (
                    <div key={item.id || `new-${itemIndex}`} className="rounded-md border border-border/25 bg-background/30 p-2.5">
                      <div className="mb-2 flex items-center justify-between gap-2">
                        <code className="truncate text-[10px] text-muted-foreground">{item.id || "保存时生成线索 ID"}</code>
                        <div className="flex items-center gap-1">
                          <button type="button" aria-label="上移线索" disabled={itemIndex === 0} onClick={() => {
                            const updated = JSON.parse(JSON.stringify(editedGameData)) as GameDataSections;
                            [updated.clue_stages[stageIndex].items[itemIndex - 1], updated.clue_stages[stageIndex].items[itemIndex]] = [updated.clue_stages[stageIndex].items[itemIndex], updated.clue_stages[stageIndex].items[itemIndex - 1]];
                            setEditedGameData(updated);
                          }} className="rounded p-1 hover:bg-secondary disabled:opacity-30"><ArrowUp className="h-3.5 w-3.5" /></button>
                          <button type="button" aria-label="下移线索" disabled={itemIndex === clueStage.items.length - 1} onClick={() => {
                            const updated = JSON.parse(JSON.stringify(editedGameData)) as GameDataSections;
                            [updated.clue_stages[stageIndex].items[itemIndex], updated.clue_stages[stageIndex].items[itemIndex + 1]] = [updated.clue_stages[stageIndex].items[itemIndex + 1], updated.clue_stages[stageIndex].items[itemIndex]];
                            setEditedGameData(updated);
                          }} className="rounded p-1 hover:bg-secondary disabled:opacity-30"><ArrowDown className="h-3.5 w-3.5" /></button>
                          <button type="button" aria-label="删除线索" disabled={clueStage.items.length <= 1} onClick={() => {
                            const updated = JSON.parse(JSON.stringify(editedGameData)) as GameDataSections;
                            updated.clue_stages[stageIndex].items.splice(itemIndex, 1);
                            setEditedGameData(updated);
                          }} className="rounded p-1 text-destructive hover:bg-destructive/10 disabled:opacity-30"><Trash2 className="h-3.5 w-3.5" /></button>
                        </div>
                      </div>
                      <label className="block text-xs text-muted-foreground">单条概述
                        <input value={item.summary} maxLength={48} onChange={(event) => updateField(["clue_stages", String(stageIndex), "items", String(itemIndex), "summary"], event.target.value)} className="mt-1 w-full rounded-md border border-border/30 bg-transparent p-2 text-foreground focus:border-primary/50 focus:outline-none" />
                      </label>
                      <label className="mt-2 block text-xs text-muted-foreground">完整线索细节
                        <textarea value={item.content} onChange={(event) => updateField(["clue_stages", String(stageIndex), "items", String(itemIndex), "content"], event.target.value)} className="mt-1 h-28 w-full resize-none rounded-md border border-border/30 bg-transparent p-2 text-foreground focus:border-primary/50 focus:outline-none scrollbar-thin" />
                      </label>
                    </div>
                  ))}
                </div>
                <button type="button" onClick={() => {
                  const updated = JSON.parse(JSON.stringify(editedGameData)) as GameDataSections;
                  updated.clue_stages[stageIndex].items.push({ id: "", summary: "", content: "", stage: clueStage.stage });
                  setEditedGameData(updated);
                }} className="mt-2 inline-flex items-center gap-1 rounded-md border border-border/30 px-2 py-1 text-xs hover:bg-secondary/50"><Plus className="h-3.5 w-3.5" />新增线索</button>
                <label className="mt-3 block text-xs text-muted-foreground">自由讨论引导
                  <textarea value={clueStage.free_discussion_notice} onChange={(event) => updateField(["clue_stages", String(stageIndex), "free_discussion_notice"], event.target.value)} className="mt-1 h-20 w-full resize-none rounded-md border border-border/30 bg-transparent p-2 text-foreground focus:border-primary/50 focus:outline-none scrollbar-thin" />
                </label>
              </div>
            ))}
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
                {msg.truthReveal && <div className="mt-3"><EndingEditor data={editedGameData} onChange={(value) => updateField(["ending_config"], value)} /></div>}
              </div>
            ))}
            {editedGameData.free_speech_limits?.map((limit, index) => (
              <div key={`limit-${index}`}>
                <label className="block text-xs font-medium text-primary mb-1">
                  第 {index + 1} 轮每位角色自由发言次数
                </label>
                <select
                  value={limit}
                  onChange={(event) =>
                    updateField(
                      ["free_speech_limits", String(index)],
                      Number(event.target.value)
                    )
                  }
                  className="text-xs bg-background border border-border/30 rounded-md p-2"
                >
                  {[1, 2, 3].map((value) => (
                    <option key={value} value={value}>{value} 次</option>
                  ))}
                </select>
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
            {editedGameData.character_data?.map((character, index) => (
                  <div key={character.character_id}>
                    <label className="block text-xs font-medium text-primary mb-1">
                      {character.name}
                    </label>
                    <textarea
                      value={character.character_script || ""}
                      onChange={(e) => updateField(
                        ["character_data", String(index), "character_script"],
                        e.target.value
                      )}
                      className="w-full text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50 scrollbar-thin"
                      style={{ minHeight: "30vh" }}
                    />
                  </div>
                ))}
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
                key={cd.character_id}
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
                    ID: {cd.character_id}
                  </span>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <label className="text-xs text-muted-foreground">
                    性别
                    <input
                      value={cd.gender || ""}
                      onChange={(event) => updateField(["character_data", String(idx), "gender"], event.target.value)}
                      className="mt-1 w-full bg-transparent border border-border/30 rounded p-1.5 text-foreground"
                    />
                  </label>
                  <label className="text-xs text-muted-foreground">
                    年龄
                    <input
                      type="number"
                      value={cd.age ?? ""}
                      onChange={(event) => updateField(["character_data", String(idx), "age"], event.target.value ? Number(event.target.value) : null)}
                      className="mt-1 w-full bg-transparent border border-border/30 rounded p-1.5 text-foreground"
                    />
                  </label>
                  <label className="text-xs text-muted-foreground">
                    职业
                    <input
                      value={cd.occupation || ""}
                      onChange={(event) => updateField(["character_data", String(idx), "occupation"], event.target.value)}
                      className="mt-1 w-full bg-transparent border border-border/30 rounded p-1.5 text-foreground"
                    />
                  </label>
                </div>
                <div>
                  <label className="block text-xs text-muted-foreground mb-0.5">
                    个人剧本摘要
                  </label>
                  <textarea
                    value={cd.script_summary || ""}
                    onChange={(e) => updateField(["character_data", String(idx), "script_summary"], e.target.value)}
                    className="w-full h-20 text-xs bg-transparent border border-border/30 rounded-md p-2 resize-none focus:outline-none focus:border-primary/50"
                  />
                </div>
                <div>
                  <div className="mb-0.5 flex items-center gap-1 text-xs text-muted-foreground">
                    <label htmlFor={`step-voice-${cd.character_id || idx}`}>
                      Voice ID
                    </label>
                    <Tooltip.Provider delayDuration={200}>
                      <Tooltip.Root>
                        <Tooltip.Trigger asChild>
                          <button
                            type="button"
                            aria-label="Voice ID 说明与可选音色"
                            className="rounded-full hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/50"
                          >
                            <CircleHelp className="h-3.5 w-3.5" />
                          </button>
                        </Tooltip.Trigger>
                        <Tooltip.Portal>
                          <Tooltip.Content
                            side="right"
                            align="start"
                            collisionPadding={12}
                            className="z-[80] max-h-[70vh] w-[min(28rem,calc(100vw-2rem))] overflow-y-auto rounded-xl border border-border bg-popover p-3 text-xs text-popover-foreground shadow-xl scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent"
                          >
                            <p className="font-medium">游戏实时 TTS 音色</p>
                            <p className="mt-1 text-muted-foreground">
                              Voice ID 决定该角色在游戏发言时使用的 step-tts-mini 音色。建议按角色性别、年龄和气质选择；当前支持以下音色：
                            </p>
                            <div className="mt-3 space-y-3">
                              {STEP_VOICE_GROUPS.map((group) => (
                                <div key={group.label}>
                                  <p className="mb-1 font-medium text-primary">
                                    {group.label}
                                  </p>
                                  <div className="grid gap-x-3 gap-y-1 sm:grid-cols-2">
                                    {group.voices.map((voice) => (
                                      <div key={voice.id} className="min-w-0">
                                        <span>{voice.label}</span>
                                        <code className="ml-1 break-all text-[10px] text-muted-foreground">
                                          {voice.id}
                                        </code>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              ))}
                            </div>
                            <Tooltip.Arrow className="fill-popover" />
                          </Tooltip.Content>
                        </Tooltip.Portal>
                      </Tooltip.Root>
                    </Tooltip.Provider>
                  </div>
                  <input
                    id={`step-voice-${cd.character_id || idx}`}
                    list={`step-voice-options-${idx}`}
                    value={cd.step_voice_id || ""}
                    onChange={(e) => updateField(["character_data", String(idx), "step_voice_id"], e.target.value)}
                    className="w-full text-xs bg-transparent border border-border/30 rounded-md p-2 focus:outline-none focus:border-primary/50"
                  />
                  <datalist id={`step-voice-options-${idx}`}>
                    {STEP_VOICE_OPTIONS.map((voice) => (
                      <option key={voice.id} value={voice.id}>
                        {voice.label}
                      </option>
                    ))}
                  </datalist>
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
  children: ReactNode;
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
