import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, ChevronDown, ChevronUp, Pencil } from "lucide-react";

import type {
  EditorInterruptInfo,
  EditorWorkflowState,
  GameDataSections,
} from "@/types/editor";
import { LoadingButton } from "./EditorControls";
import { getButtonLoadingMessage } from "./editorMessages";

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
