import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import {
  X,
  Users,
  BookOpen,
  Cpu,
  Play,
  ChevronDown,
  Zap,
  LoaderCircle,
} from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";
import * as Tooltip from "@radix-ui/react-tooltip";
import { scriptApi, gameApi, systemApi, subscribeModelHealth } from "@/lib/api";
import { configuredModels } from "@/lib/capabilityAdapter";
import { assignModelsToAICharacters } from "@/lib/modelAssignment";
import type { Script, Character } from "@/types/game";
import { DIFFICULTY_COLORS, type AIModelOption } from "@/types/game";
import type { ModelHealthItem } from "@/types/capabilities";

// Component for text with conditional tooltip
function TruncatedText({ text }: { text: string }) {
  const textRef = useRef<HTMLParagraphElement>(null);
  const [isTruncated, setIsTruncated] = useState(false);

  const checkTruncation = useCallback(() => {
    if (textRef.current) {
      const { scrollHeight, clientHeight, scrollWidth, clientWidth } =
        textRef.current;
      setIsTruncated(scrollHeight > clientHeight || scrollWidth > clientWidth);
    }
  }, []);

  useEffect(() => {
    const frame = requestAnimationFrame(checkTruncation);
    window.addEventListener("resize", checkTruncation);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", checkTruncation);
    };
  }, [checkTruncation, text]);

  if (isTruncated) {
    return (
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <p
            ref={textRef}
            className="text-sm text-muted-foreground mt-1 line-clamp-3 text-left cursor-help"
          >
            {text}
          </p>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content
            className="max-w-xs px-3 py-2 text-xs bg-popover/95 backdrop-blur-sm border border-border rounded-lg shadow-xl shadow-primary/10 z-50"
            sideOffset={8}
            side="top"
          >
            <p className="text-popover-foreground leading-relaxed">{text}</p>
            <Tooltip.Arrow className="fill-popover" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    );
  }

  return (
    <p
      ref={textRef}
      className="text-sm text-muted-foreground mt-1 line-clamp-3 text-left"
    >
      {text}
    </p>
  );
}

interface ScriptDetailModalProps {
  script: Script;
  open: boolean;
  onClose: () => void;
  onStartGame: (sessionId: string) => void;
}

export function ScriptDetailModal({
  script,
  open,
  onClose,
  onStartGame,
}: ScriptDetailModalProps) {
  const [characters, setCharacters] = useState<Character[]>([]);
  const [selectedCharacter, setSelectedCharacter] = useState<string | null>(
    null
  );
  const [aiModels, setAiModels] = useState<Record<string, string>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [reloadToken, setReloadToken] = useState(0);
  const [openSelectId, setOpenSelectId] = useState<string | null>(null);
  const [availableModels, setAvailableModels] = useState<AIModelOption[]>([]);
  const [modelCapabilityReason, setModelCapabilityReason] = useState(
    "正在检查模型能力…"
  );
  const [modelHealthById, setModelHealthById] = useState<
    Record<string, ModelHealthItem>
  >({});
  const [modelHealthResolved, setModelHealthResolved] = useState(false);
  const [isRefreshingModelHealth, setIsRefreshingModelHealth] = useState(false);
  const [modelHealthMessage, setModelHealthMessage] = useState("");
  const manuallySelectedModelIdsRef = useRef(new Set<string>());

  const difficultyInfo =
    DIFFICULTY_COLORS[script.difficulty] || DIFFICULTY_COLORS[1];

  // Load characters when modal opens
  useEffect(() => {
    if (!open || !script.script_id) return;

    let cancelled = false;
    setIsLoading(true);
    setLoadError("");
    setActionError("");
    setCharacters([]);
    setSelectedCharacter(null);
    setAiModels({});
    setAvailableModels([]);
    setModelHealthById({});
    setModelHealthResolved(false);
    setIsRefreshingModelHealth(false);
    setModelHealthMessage("");
    manuallySelectedModelIdsRef.current.clear();
    setModelCapabilityReason("正在检查模型能力…");

    const unsubscribeHealth = subscribeModelHealth((result) => {
      if (cancelled) return;
      setModelHealthById(Object.fromEntries(result.models.map((item) => [item.model, item])));
      setIsRefreshingModelHealth(Boolean(result.probing));
    });
    setIsRefreshingModelHealth(true);
    void systemApi
      .getModelHealth()
      .then((result) => {
        if (cancelled) return;
        setModelHealthById(
          Object.fromEntries(result.models.map((item) => [item.model, item]))
        );
        setModelHealthResolved(true);
      })
      .catch(() => {
        // Health hints are best-effort and never block model selection.
        if (!cancelled) setModelHealthResolved(true);
      })
      .finally(() => { if (!cancelled) setIsRefreshingModelHealth(false); });

    Promise.allSettled([
      scriptApi.getScriptCharacters(script.script_id),
      systemApi.getCapabilities(),
    ]).then(([characterResult, capabilityResult]) => {
      if (cancelled) return;

      let chars: Character[] = [];
      if (characterResult.status === "fulfilled") {
        const payload = characterResult.value.characters;
        chars = Array.isArray(payload)
          ? payload.filter(
              (character) =>
                typeof character?.character_id === "string" &&
                character.character_id.length > 0 &&
                typeof character.name === "string" &&
                character.name.length > 0
            )
          : [];
        setCharacters(chars);
        if (chars.length === 0) {
          setLoadError("该剧本没有可用角色，请检查剧本数据后重试。");
        }
      } else {
        console.error("Failed to load script characters:", characterResult.reason);
        setLoadError("角色加载失败，请确认后端正常运行后重试。");
      }

      let models: AIModelOption[] = [];
      if (capabilityResult.status === "fulfilled") {
        models = configuredModels(capabilityResult.value);
        setModelCapabilityReason(
          models.length > 0
            ? ""
            : "没有已配置的主模型，请先在 backend/.env 配置 DEEPSEEK_API_KEY"
        );
      } else {
        console.error("Failed to load model capabilities:", capabilityResult.reason);
        setModelCapabilityReason("无法读取后端模型能力，请检查后端连接");
      }
      setAvailableModels(models);

      setAiModels({});
      setIsLoading(false);
    });

    return () => {
      cancelled = true;
      unsubscribeHealth();
    };
  }, [open, reloadToken, script.script_id]);

  // Handle character selection
  const handleCharacterSelect = (characterId: string) => {
    setSelectedCharacter(characterId);
    manuallySelectedModelIdsRef.current.clear();
    setAiModels(
      assignModelsToAICharacters({
        characters,
        humanCharacterId: characterId,
        models: availableModels,
        healthById: modelHealthById,
      })
    );
  };

  // Handle AI model change
  const handleAIModelChange = (characterId: string, modelId: string) => {
    manuallySelectedModelIdsRef.current.add(characterId);
    setAiModels((prev) => ({ ...prev, [characterId]: modelId }));
  };

  const handleRefreshModelHealth = async () => {
    if (isRefreshingModelHealth) return;
    setIsRefreshingModelHealth(true);
    setModelHealthMessage("");
    try {
      const result = await systemApi.getModelHealth(true);
      setModelHealthById(
        Object.fromEntries(result.models.map((item) => [item.model, item]))
      );
      setModelHealthResolved(true);
      setModelHealthMessage("测速已更新");
    } catch {
      setModelHealthMessage("测速请求失败，请稍后重试");
    } finally {
      setIsRefreshingModelHealth(false);
    }
  };

  useEffect(() => {
    if (
      !selectedCharacter ||
      !modelHealthResolved ||
      availableModels.length === 0
    ) {
      return;
    }
    setAiModels((currentModels) => {
      const automaticModels = assignModelsToAICharacters({
        characters,
        humanCharacterId: selectedCharacter,
        models: availableModels,
        healthById: modelHealthById,
      });
      manuallySelectedModelIdsRef.current.forEach((characterId) => {
        if (currentModels[characterId]) {
          automaticModels[characterId] = currentModels[characterId];
        }
      });
      return automaticModels;
    });
  }, [
    availableModels,
    characters,
    modelHealthById,
    modelHealthResolved,
    selectedCharacter,
  ]);

  // Start game
  const handleStartGame = async () => {
    const defaultModel = availableModels[0];
    if (!selectedCharacter || !defaultModel) return;

    setIsCreating(true);
    setActionError("");
    try {
      const automaticModels = assignModelsToAICharacters({
        characters,
        humanCharacterId: selectedCharacter,
        models: availableModels,
        healthById: modelHealthById,
      });
      // Prepare AI models for non-human characters
      const aiModelConfig: Record<string, string> = {};
      characters.forEach((char) => {
        if (char.character_id !== selectedCharacter) {
          aiModelConfig[char.character_id] =
            aiModels[char.character_id] ||
            automaticModels[char.character_id] ||
            defaultModel.id;
        }
      });

      const result = await gameApi.createGame({
        script_id: script.script_id,
        human_character_id: selectedCharacter,
        ai_models: aiModelConfig,
      });

      if (result.success && result.session_id) {
        onStartGame(result.session_id);
        onClose();
      } else {
        setActionError(result.error || "创建游戏失败，请检查角色和模型配置。");
      }
    } catch (error) {
      console.error("Failed to create game:", error);
      setActionError("创建游戏失败，请确认后端服务和模型配置正常。");
    } finally {
      setIsCreating(false);
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/70 backdrop-blur-sm z-50"
          />
        </Dialog.Overlay>

        <Dialog.Content asChild>
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="fixed inset-4 md:inset-auto md:left-1/2 md:top-1/2 md:-translate-x-1/2 md:-translate-y-1/2
                       md:max-w-6xl md:w-[95vw] md:max-h-[90vh] overflow-hidden
                       rounded-2xl bg-card border border-border shadow-2xl z-50 flex flex-col"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-border">
              <Dialog.Title className="text-2xl font-bold text-glow">
                {script.title}
              </Dialog.Title>
              <Dialog.Close asChild>
                <button
                  className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
                  onClick={onClose}
                >
                  <X className="w-5 h-5" />
                </button>
              </Dialog.Close>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-auto p-6 scrollbar-thin">
              <div className="grid md:grid-cols-[2.5fr_3fr] gap-8">
                {/* Left: Script Info */}
                <div className="space-y-6">
                  {/* Cover Image */}
                  {script.cover_image_url && (
                    <div className="relative rounded-xl overflow-hidden bg-secondary/20">
                      <img
                        src={script.cover_image_url}
                        alt={script.title}
                        loading="lazy"
                        decoding="async"
                        className="w-full h-auto max-h-64 object-contain"
                      />
                    </div>
                  )}

                  {/* Stats */}
                  <div className="grid grid-cols-3 gap-4">
                    <div className="p-4 rounded-xl bg-secondary/30 text-center">
                      <div
                        className={`text-sm font-medium ${difficultyInfo.text}`}
                      >
                        {difficultyInfo.label}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        难度
                      </div>
                    </div>
                    <div className="p-4 rounded-xl bg-secondary/30 text-center">
                      <div className="text-sm font-medium">
                        {script.player_count}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        玩家人数
                      </div>
                    </div>
                    <div className="p-4 rounded-xl bg-secondary/30 text-center">
                      <div className="text-sm font-medium">
                        {script.estimated_duration ?? 20}
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">
                        预计时长(分钟)
                      </div>
                    </div>
                  </div>

                  {/* Description */}
                  <div>
                    <h4 className="text-sm font-medium text-muted-foreground mb-2 flex items-center gap-2">
                      <BookOpen className="w-4 h-4" />
                      剧本简介
                    </h4>
                    <p className="text-sm leading-relaxed">
                      {script.overview || script.description}
                    </p>
                  </div>

                  {/* Tags */}
                  {script.tags && (
                    <div className="flex flex-wrap gap-2">
                      {script.tags.split(",").map((tag, index) => (
                        <span
                          key={index}
                          className="px-3 py-1 text-xs rounded-full bg-primary/20 text-primary border border-primary/30"
                        >
                          {tag.trim()}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                {/* Right: Character Selection */}
                <div className="space-y-4 flex flex-col">
                  <div className="flex items-center justify-between gap-3">
                    <h4 className="text-lg font-semibold flex items-center gap-2">
                      <Users className="w-5 h-5 text-primary" />
                      选择你的角色
                    </h4>
                    <div className="flex items-center gap-2">
                      {modelHealthMessage && (
                        <span
                          role="status"
                          className={`hidden text-xs sm:inline ${
                            modelHealthMessage.includes("失败")
                              ? "text-amber-300"
                              : "text-muted-foreground"
                          }`}
                        >
                          {modelHealthMessage}
                        </span>
                      )}
                      <button
                        type="button"
                        title="测速结果保留30分钟，可手动重新测速"
                        onClick={handleRefreshModelHealth}
                        disabled={isRefreshingModelHealth || isLoading}
                        aria-label={
                          isRefreshingModelHealth ? "模型测速中" : "重新进行模型测速"
                        }
                        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-primary/25 bg-primary/10 px-2.5 py-1.5 text-xs font-medium text-primary transition-colors hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {isRefreshingModelHealth ? (
                          <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <Zap className="h-3.5 w-3.5" />
                        )}
                        {isRefreshingModelHealth ? "测速中" : "模型测速"}
                      </button>
                    </div>
                  </div>

                  {isLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                    </div>
                  ) : loadError ? (
                    <div
                      role="alert"
                      className="rounded-xl border border-destructive/30 bg-destructive/10 p-5 text-sm"
                    >
                      <p>{loadError}</p>
                      <button
                        type="button"
                        onClick={() => setReloadToken((value) => value + 1)}
                        className="mt-3 rounded-lg bg-secondary px-3 py-2 hover:bg-secondary/80"
                      >
                        重新加载
                      </button>
                    </div>
                  ) : (
                    <Tooltip.Provider delayDuration={0}>
                      <div className="space-y-3 flex-1 overflow-auto pr-2 py-1 scrollbar-thin max-h-[55vh]">
                        {characters.map((char) => (
                          <div
                            key={char.character_id}
                            className="flex justify-center"
                          >
                            <div
                              onClick={() => {
                                if (openSelectId) return;
                                handleCharacterSelect(char.character_id);
                              }}
                              className={`w-[95%] p-4 rounded-xl cursor-pointer transition-all border
                                ${
                                  selectedCharacter === char.character_id
                                    ? "bg-primary/10 border-primary glow"
                                    : "bg-secondary/20 border-transparent hover:border-border hover:bg-secondary/30"
                                }`}
                            >
                              <div className="flex items-start gap-4">
                                {/* Avatar */}
                                <div
                                  className="w-24 h-24 rounded-full bg-gradient-to-br from-primary/30 to-accent/30
                                            flex items-center justify-center text-xl font-bold shrink-0 overflow-hidden relative"
                                >
                                  {char.avatar_url ? (
                                    <img
                                      src={char.avatar_url}
                                      alt={char.name}
                                      loading="lazy"
                                      decoding="async"
                                      className="w-full h-full object-cover"
                                    />
                                  ) : (
                                    char.name[0]
                                  )}
                                </div>

                                {/* Info */}
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-2">
                                    <span className="font-medium text-base">
                                      {char.name}
                                    </span>
                                    <span className="text-xs text-muted-foreground">
                                      {char.gender} · {char.age}岁
                                    </span>
                                  </div>
                                  <TruncatedText
                                    text={
                                      char.profile ||
                                      char.character_script_summary ||
                                      "神秘角色"
                                    }
                                  />
                                </div>

                                {/* Selection indicator */}
                                {selectedCharacter === char.character_id && (
                                  <div className="w-6 h-6 rounded-full bg-primary flex items-center justify-center shrink-0">
                                    <svg
                                      className="w-4 h-4 text-primary-foreground"
                                      fill="none"
                                      viewBox="0 0 24 24"
                                      stroke="currentColor"
                                    >
                                      <path
                                        strokeLinecap="round"
                                        strokeLinejoin="round"
                                        strokeWidth={2}
                                        d="M5 13l4 4L19 7"
                                      />
                                    </svg>
                                  </div>
                                )}
                              </div>

                              {/* AI Model selector (for non-selected characters) */}
                              {selectedCharacter &&
                                selectedCharacter !== char.character_id && (
                                  <motion.div
                                    initial={{ opacity: 0, height: 0 }}
                                    animate={{ opacity: 1, height: "auto" }}
                                    className="mt-3 pt-3 border-t border-border/50"
                                    onClick={(e) => e.stopPropagation()}
                                    onPointerDown={(e) => e.stopPropagation()}
                                    onTouchEnd={(e) => e.stopPropagation()}
                                  >
                                    <label className="text-xs text-muted-foreground flex items-center gap-1.5 mb-2">
                                      <Cpu className="w-3 h-3" />
                                      AI 扮演模型
                                    </label>
                                    {availableModels.length > 0 ? (
                                      <>
                                        <Select.Root
                                          value={
                                            aiModels[char.character_id] ||
                                            availableModels[0]?.id
                                          }
                                          onValueChange={(value: string) =>
                                            handleAIModelChange(
                                              char.character_id,
                                              value
                                            )
                                          }
                                          onOpenChange={(open) => {
                                            setOpenSelectId(
                                              open ? char.character_id : null
                                            );
                                          }}
                                        >
                                        <Select.Trigger
                                          className="w-full px-3 py-2 text-sm rounded-lg bg-secondary/30 border border-border
                                               hover:bg-secondary/50 focus:outline-none focus:ring-2 focus:ring-primary/50
                                               flex items-center justify-between"
                                        >
                                          <Select.Value />
                                          <Select.Icon>
                                            <ChevronDown className="w-4 h-4 text-muted-foreground" />
                                          </Select.Icon>
                                        </Select.Trigger>
                                        <Select.Portal>
                                          <Select.Content
                                            className="w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg bg-card border border-border shadow-xl z-50"
                                            position="popper"
                                            sideOffset={4}
                                          >
                                            <Select.Viewport className="p-1">
                                              {availableModels.map((model) => {
                                                const health = modelHealthById[model.id];
                                                const hasWarning =
                                                  health?.status === "slow" ||
                                                  health?.status === "timeout" ||
                                                  health?.status === "unavailable";
                                                const isIncomplete =
                                                  health?.status === "unknown";
                                                return (
                                                  <Select.Item
                                                    key={model.id}
                                                    value={model.id}
                                                    aria-label={
                                                      health?.status === "unavailable"
                                                        ? `${model.name}，当前不可用`
                                                        : health?.status === "slow"
                                                          ? `${model.name}，响应较慢`
                                                          : health?.status === "timeout"
                                                            ? `${model.name}，测速超时`
                                                          : isIncomplete
                                                            ? `${model.name}，本次测速失败`
                                                            : model.name
                                                    }
                                                    className="w-full px-3 py-2 text-sm rounded-md cursor-pointer
                                                         outline-none hover:bg-secondary/50 focus:bg-secondary/50
                                                         data-[highlighted]:bg-secondary/50 flex items-center justify-between gap-3"
                                                  >
                                                    <Select.ItemText>
                                                      {model.name}
                                                    </Select.ItemText>
                                                    {hasWarning && (
                                                      <span
                                                        className={`shrink-0 text-[11px] ${
                                                          health.status === "unavailable"
                                                            ? "text-red-300"
                                                            : "text-amber-300"
                                                        }`}
                                                        title={health.message}
                                                      >
                                                        {health.status === "unavailable"
                                                          ? "当前不可用"
                                                          : health.status === "timeout"
                                                            ? "测速超时"
                                                            : "响应较慢"}
                                                      </span>
                                                    )}
                                                    {isIncomplete && (
                                                      <span
                                                        className="shrink-0 text-[11px] text-muted-foreground"
                                                        title={health.message}
                                                      >
                                                        测速失败
                                                      </span>
                                                    )}
                                                  </Select.Item>
                                                );
                                              })}
                                            </Select.Viewport>
                                          </Select.Content>
                                        </Select.Portal>
                                        </Select.Root>
                                        {(() => {
                                          const selectedModelId =
                                            aiModels[char.character_id] ||
                                            availableModels[0]?.id;
                                          const health = selectedModelId
                                            ? modelHealthById[selectedModelId]
                                            : undefined;
                                          if (
                                            health?.status !== "slow" &&
                                            health?.status !== "timeout" &&
                                            health?.status !== "unavailable" &&
                                            health?.status !== "unknown"
                                          ) {
                                            return null;
                                          }
                                          return (
                                            <p
                                              role="status"
                                              className="mt-2 text-xs text-amber-300"
                                            >
                                              {health.status === "unavailable"
                                                ? "模型暂不可用，请选择其他模型"
                                                : health.message}
                                            </p>
                                          );
                                        })()}
                                      </>
                                    ) : (
                                      <p
                                        role="status"
                                        className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
                                      >
                                        暂不可分配 AI 模型：{modelCapabilityReason}
                                      </p>
                                    )}
                                  </motion.div>
                                )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </Tooltip.Provider>
                  )}
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="p-6 border-t border-border bg-secondary/10">
              {actionError && (
                <p role="alert" className="mb-3 text-sm text-destructive">
                  {actionError}
                </p>
              )}
              <Tooltip.Provider delayDuration={300}>
              <Tooltip.Root>
                <Tooltip.Trigger asChild>
                  <button
                    onClick={handleStartGame}
                    disabled={
                      !selectedCharacter || isCreating || availableModels.length === 0
                    }
                    className="w-full py-4 rounded-xl bg-primary text-primary-foreground font-medium
                             hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed
                             transition-all flex items-center justify-center gap-2 glow"
                  >
                    {isCreating ? (
                      <>
                        <div className="w-5 h-5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
                        创建游戏中...
                      </>
                    ) : (
                      <>
                        <Play className="w-5 h-5" />
                        开始游戏
                      </>
                    )}
                  </button>
                </Tooltip.Trigger>
                {(!selectedCharacter || availableModels.length === 0) && !isCreating && (
                  <Tooltip.Portal>
                    <Tooltip.Content
                      className="px-3 py-2 text-xs bg-popover/95 backdrop-blur-sm border border-border rounded-lg shadow-xl shadow-primary/10 z-50"
                      sideOffset={8}
                      side="top"
                    >
                      <p className="text-popover-foreground">
                        {availableModels.length === 0
                          ? modelCapabilityReason
                          : "请先选择你要扮演的角色"}
                      </p>
                      <Tooltip.Arrow className="fill-popover" />
                    </Tooltip.Content>
                  </Tooltip.Portal>
                )}
              </Tooltip.Root>
              </Tooltip.Provider>
            </div>
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
