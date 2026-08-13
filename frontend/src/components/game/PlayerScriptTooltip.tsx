import { useState, useEffect, useCallback, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { BookOpen, X, Lightbulb, Zap } from "lucide-react";
import { SpeakerIcon, type SpeakerState } from "@/components/ui/SpeakerIcon";
import { AudioSpeedButton } from "@/components/ui/AudioSpeedButton";
import { Markdown } from "@/components/ui/Markdown";
import { audioPlayerManager } from "@/lib/audioPlayerManager";
import { systemApi } from "@/lib/api";
import { ttsCapability } from "@/lib/capabilityAdapter";

interface PlayerScriptTooltipProps {
  scriptContent: string;
  scriptSummary?: string;
  keyInfo?: string;
  characterName?: string;
  sessionId?: string;
  scriptId?: string;
  characterId?: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function PlayerScriptTooltip({
  scriptContent,
  scriptSummary,
  keyInfo,
  characterName,
  sessionId,
  scriptId,
  characterId,
  open,
  onOpenChange,
}: PlayerScriptTooltipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [hasOpenedBefore, setHasOpenedBefore] = useState(
    () => !!sessionId && localStorage.getItem(`script_opened_${sessionId}`) === "true",
  );
  const [showQuickOverview, setShowQuickOverview] = useState(false);
  const [speakerState, setSpeakerState] = useState<SpeakerState>("off");
  const [audioCapability, setAudioCapability] = useState({
    enabled: false,
    reason: "正在检查语音能力…",
  });
  const audioCapabilityEnabled = audioCapability.enabled;
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const isSeeking = useRef(false);
  const isScriptAudio = useRef(false); // 标记当前播放的是否为剧本音频
  const unsubRef = useRef<(() => void) | null>(null);

  const handleOpenScript = () => {
    setIsOpen(true);
    if (sessionId) {
      const key = `script_opened_${sessionId}`;
      localStorage.setItem(key, "true");
      setHasOpenedBefore(true);
    }
  };
  const visible = isOpen || !!open;

  useEffect(() => {
    systemApi
      .getCapabilities()
      .then((capabilities) => setAudioCapability(ttsCapability(capabilities)))
      .catch(() =>
        setAudioCapability({ enabled: false, reason: "无法读取后端语音能力" })
      );
  }, []);

  // Subscribe to audio player state changes — only track script audio
  useEffect(() => {
    const unsub = audioPlayerManager.onStateChange(
      (playing, currentTime, dur) => {
        if (isSeeking.current) return;
        if (!isScriptAudio.current) return;
        setProgress(currentTime);
        setDuration(dur);
        // Only treat as ended when the audio source is actually gone (ended/error/stopped),
        // NOT when merely paused. isAudioActive() returns false only after onended/onerror/stop
        // clears the audio element reference.
        if (!playing && !audioPlayerManager.isAudioActive()) {
          isScriptAudio.current = false;
          setSpeakerState("off");
        }
      }
    );
    unsubRef.current = unsub;
    return unsub;
  }, []);

  // Handle script audio playback
  const handlePlayScriptAudio = useCallback(async () => {
    if (!audioCapabilityEnabled) return;
    // If script audio is active (playing or paused) → toggle pause
    if (isScriptAudio.current && audioPlayerManager.isAudioActive()) {
      const resumed = audioPlayerManager.togglePause();
      setSpeakerState(resumed ? "playing" : "off");
      return;
    }

    // Something else is playing → stop it
    if (audioPlayerManager.getIsPlaying()) {
      audioPlayerManager.stop();
    }

    if (!scriptId || !characterId) {
      setSpeakerState("error");
      return;
    }

    const audioUrl = `/audio/scripts/${scriptId}/character_scripts/${characterId}.wav`;
    isScriptAudio.current = true;
    setSpeakerState("loading");

    try {
      await audioPlayerManager.play(audioUrl);
      setSpeakerState("playing");
      setProgress(0);
    } catch {
      isScriptAudio.current = false;
      setSpeakerState("error");
    }
  }, [scriptId, characterId, audioCapabilityEnabled]);

  const handleClose = useCallback(() => {
    if (isScriptAudio.current) {
      audioPlayerManager.stop();
      isScriptAudio.current = false;
    }
    setSpeakerState("off");
    setProgress(0);
    setDuration(0);
    setIsOpen(false);
    onOpenChange?.(false);
  }, [onOpenChange]);

  // Seek handler
  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    const time = Number(e.target.value);
    isSeeking.current = true;
    setProgress(time);
    audioPlayerManager.seekTo(time);
    // Reset seeking flag after a short delay to resume progress updates
    setTimeout(() => {
      isSeeking.current = false;
    }, 100);
  };

  if (!scriptContent) return null;

  const showGlow = !hasOpenedBefore && !isOpen;

  const showProgressBar =
    speakerState === "playing" || (speakerState === "off" && progress > 0);

  return (
    <>
      {/* Floating button */}
      <motion.button
        onClick={handleOpenScript}
        className={`fixed bottom-6 right-6 z-40 w-14 h-14 rounded-full
                   bg-primary/90 hover:bg-primary text-foreground
                   shadow-lg hidden lg:flex flex-col items-center justify-center gap-1
                   transition-colors ${showGlow ? "breathing-prominent" : ""}`}
        whileHover={{ scale: 1.1 }}
        whileTap={{ scale: 0.95 }}
        title="查看我的剧本"
        style={
          showGlow
            ? {
                boxShadow:
                  "0 0 20px rgba(var(--primary-rgb, 59, 130, 246), 0.5), 0 0 40px rgba(var(--primary-rgb, 59, 130, 246), 0.3)",
              }
            : undefined
        }
      >
        <BookOpen className="w-6 h-6" />
        {showGlow && (
          <span className="absolute -top-1 -right-1 px-1.5 py-0.5 rounded-full bg-accent text-[10px] font-bold text-accent-foreground animate-pulse">
            新
          </span>
        )}
      </motion.button>

      {/* Modal */}
      <AnimatePresence>
        {visible && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
            onClick={() => {
              handleClose();
            }}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.9, y: 20 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.9, y: 20 }}
              className="bg-card rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] flex flex-col overflow-hidden"
              onClick={(e) => e.stopPropagation()}
            >
              {/* Header */}
              <div className="flex items-center justify-between p-4 border-b border-border/50">
                <div className="flex items-center gap-2">
                  <BookOpen className="w-5 h-5 text-primary" />
                  <h3 className="text-lg font-bold">
                    {characterName ? `${characterName}的剧本` : "我的剧本"}
                  </h3>
                  {(scriptSummary || keyInfo) && (
                    <button
                      onClick={() => setShowQuickOverview((v) => !v)}
                      className={`flex items-center gap-1 ml-2 px-2 py-0.5 rounded-md text-xs font-medium transition-colors
                        ${
                          showQuickOverview
                            ? "bg-primary/20 text-primary"
                            : "bg-secondary/50 text-muted-foreground hover:bg-secondary/70 hover:text-foreground"
                        }`}
                    >
                      <Zap className="w-3 h-3" />
                      快速了解
                    </button>
                  )}
                  <SpeakerIcon
                    state={audioCapability.enabled ? speakerState : "disabled"}
                    onClick={handlePlayScriptAudio}
                    size={16}
                  />
                  <span className="text-[9px] text-muted-foreground/60">
                    {audioCapability.enabled
                      ? "AI 生成语音"
                      : audioCapability.reason}
                  </span>
                </div>
                <button
                  onClick={() => {
                    handleClose();
                  }}
                  className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Quick overview panel */}
              <AnimatePresence>
                {showQuickOverview && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "100vh", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="overflow-hidden border-b border-border/30 bg-secondary/20"
                  >
                    <div className="h-full overflow-y-auto scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                      <div className="px-4 py-3 space-y-3">
                        {scriptSummary && (
                          <div>
                            <h4 className="text-sm font-bold text-primary mb-1">
                              剧本摘要
                            </h4>
                            <p className="text-sm text-muted-foreground leading-relaxed">
                              {scriptSummary}
                            </p>
                          </div>
                        )}
                        {keyInfo && (
                          <div>
                            <h4 className="text-sm font-bold text-primary mb-1">
                              关键信息
                            </h4>
                            <Markdown className="text-sm text-muted-foreground leading-relaxed">
                              {keyInfo}
                            </Markdown>
                          </div>
                        )}
                      </div>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* Audio progress bar + speed control */}
              {showProgressBar && (
                <div className="px-4 pt-2 pb-1 flex items-center gap-2">
                  <span className="text-[10px] text-muted-foreground tabular-nums w-8 text-right">
                    {formatTime(progress)}
                  </span>
                  <input
                    type="range"
                    min={0}
                    max={duration || 0}
                    step={0.1}
                    value={progress}
                    onChange={handleSeek}
                    className="flex-1 h-1 rounded-full appearance-none bg-secondary cursor-pointer
                               [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3
                               [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full
                               [&::-webkit-slider-thumb]:bg-primary"
                  />
                  <span className="text-[10px] text-muted-foreground tabular-nums w-8">
                    {formatTime(duration)}
                  </span>
                  <AudioSpeedButton />
                </div>
              )}

              {/* Guidance tip */}
              <div className="px-4 pt-3">
                <div className="flex items-start gap-2 p-3 rounded-lg bg-primary/5 border border-primary/10">
                  <Lightbulb className="w-4 h-4 text-primary shrink-0 mt-0.5" />
                  <p className="text-xs text-muted-foreground">
                    这是你的完整角色剧本，包含你的身份、背景和秘密。在发言时请保持角色一致性，不要暴露关键信息。如果是凶手，请自然地隐藏身份。
                  </p>
                </div>
              </div>

              {/* Content */}
              <div className="p-4 overflow-y-auto flex-1 min-h-0 scrollbar-thin scrollbar-thumb-border scrollbar-track-transparent">
                <Markdown className="prose-sm">{scriptContent}</Markdown>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
