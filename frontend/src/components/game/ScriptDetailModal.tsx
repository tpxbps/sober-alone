import { useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import { X, Users, BookOpen, Cpu, Play, ChevronDown } from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";
import * as Select from "@radix-ui/react-select";
import * as Tooltip from "@radix-ui/react-tooltip";
import { scriptApi, gameApi, systemApi } from "@/lib/api";
import { configuredModels } from "@/lib/capabilityAdapter";
import type { Script, Character } from "@/types/game";
import { DIFFICULTY_COLORS, AI_MODELS } from "@/types/game";

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
  const [openSelectId, setOpenSelectId] = useState<string | null>(null);
  const [availableModels, setAvailableModels] = useState<typeof AI_MODELS>([]);
  const [modelCapabilityReason, setModelCapabilityReason] = useState(
    "正在检查模型能力…"
  );

  const difficultyInfo =
    DIFFICULTY_COLORS[script.difficulty] || DIFFICULTY_COLORS[1];

  // Load characters when modal opens
  useEffect(() => {
    if (open && script.script_id) {
      setIsLoading(true);
      Promise.all([
        scriptApi.getScriptCharacters(script.script_id),
        systemApi.getCapabilities(),
      ])
        .then(([response, capabilities]) => {
          const models = configuredModels(AI_MODELS, capabilities);
          setAvailableModels(models);
          setModelCapabilityReason(
            models.length > 0 ? "" : "没有已配置的主模型，请先设置 DEEPSEEK_API_KEY"
          );
          const chars = response.characters;
          setCharacters(chars);
          const defaultModels: Record<string, string> = {};
          chars.forEach((char) => {
            if (models[0]) defaultModels[char.character_id] = models[0].id;
          });
          setAiModels(defaultModels);
        })
        .catch((error) => {
          console.error(error);
          setAvailableModels([]);
          setModelCapabilityReason("无法读取后端模型能力");
        })
        .finally(() => setIsLoading(false));
    }
  }, [open, script.script_id]);

  // Handle character selection
  const handleCharacterSelect = (characterId: string) => {
    setSelectedCharacter(characterId);
  };

  // Handle AI model change
  const handleAIModelChange = (characterId: string, modelId: string) => {
    setAiModels((prev) => ({ ...prev, [characterId]: modelId }));
  };

  // Start game
  const handleStartGame = async () => {
    if (!selectedCharacter || availableModels.length === 0) return;

    setIsCreating(true);
    try {
      // Prepare AI models for non-human characters
      const aiModelConfig: Record<string, string> = {};
      characters.forEach((char) => {
        if (char.character_id !== selectedCharacter) {
          aiModelConfig[char.character_id] =
            aiModels[char.character_id] || availableModels[0]?.id;
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
      }
    } catch (error) {
      console.error("Failed to create game:", error);
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
                        className="w-full h-auto max-h-64 object-contain"
                      />
                      <span className="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-black/70 text-white text-[10px]">
                        AI 生成图片
                      </span>
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
                  <h4 className="text-lg font-semibold flex items-center gap-2">
                    <Users className="w-5 h-5 text-primary" />
                    选择你的角色
                  </h4>

                  {isLoading ? (
                    <div className="flex items-center justify-center py-12">
                      <div className="w-8 h-8 border-2 border-primary border-t-transparent rounded-full animate-spin" />
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
                                      className="w-full h-full object-cover"
                                    />
                                  ) : (
                                    char.name[0]
                                  )}
                                  {char.avatar_url && (
                                    <span className="absolute bottom-0 inset-x-0 bg-black/65 text-white text-[8px] text-center py-0.5">
                                      AI 生成
                                    </span>
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
                                    <Select.Root
                                      value={
                                        aiModels[char.character_id] ||
                                        availableModels[0].id
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
                                        onClick={(e: React.MouseEvent) =>
                                          e.stopPropagation()
                                        }
                                        onPointerDown={(e) =>
                                          e.stopPropagation()
                                        }
                                        onTouchEnd={(e) =>
                                          e.stopPropagation()
                                        }
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
                                            {availableModels.map((model) => (
                                              <Select.Item
                                                key={model.id}
                                                value={model.id}
                                                className="w-full px-3 py-2 text-sm rounded-md cursor-pointer
                                                       outline-none hover:bg-secondary/50 focus:bg-secondary/50
                                                       data-[highlighted]:bg-secondary/50"
                                              >
                                                <Select.ItemText>
                                                  {model.name}
                                                </Select.ItemText>
                                              </Select.Item>
                                            ))}
                                          </Select.Viewport>
                                        </Select.Content>
                                      </Select.Portal>
                                    </Select.Root>
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
