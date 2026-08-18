import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Mic, MicOff } from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { systemApi } from "@/lib/api";
import { ttsCapability as resolveTtsCapability } from "@/lib/capabilityAdapter";

type SettingsMode = "full" | "game" | "editor";

interface SettingsModalProps {
  onClose: () => void;
  /** Controls which sections are visible:
   *  'full' and 'game' show optional TTS settings.
   *  'editor' hides game-only audio settings.
   */
  mode?: SettingsMode;
}

export function SettingsModal({ onClose, mode = "full" }: SettingsModalProps) {
  const { ttsEnabled, setTtsEnabled } = useSettingsStore();
  const [ttsCapability, setTtsCapability] = useState({
    enabled: false,
    reason: "正在检查语音能力…",
  });

  useEffect(() => {
    systemApi
      .getCapabilities()
      .then((capabilities) => {
        const resolved = resolveTtsCapability(capabilities);
        setTtsCapability(resolved);
        if (!resolved.enabled) setTtsEnabled(false);
      })
      .catch(() => setTtsCapability({ enabled: false, reason: "无法读取后端能力状态" }));
  }, [setTtsEnabled]);


  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <motion.div
        initial={{ opacity: 0, scale: 0.9, y: 20 }}
        animate={{ opacity: 1, scale: 1, y: 0 }}
        exit={{ opacity: 0, scale: 0.9, y: 20 }}
        className="bg-card rounded-xl p-6 min-w-[360px] max-w-[420px] max-h-[80vh] overflow-y-auto shadow-2xl border border-border"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-lg font-bold mb-5">设置</h3>

        {/* TTS Toggle — hidden in editor mode */}
        {mode !== "editor" && (
          <>
            <div className="border-t border-border/50 my-4" />
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                {ttsEnabled ? (
                  <Mic className="w-5 h-5 text-primary" />
                ) : (
                  <MicOff className="w-5 h-5 text-muted-foreground" />
                )}
                <div className="flex flex-col">
                  <div className="flex items-center gap-1.5">
                    <span className="text-sm font-medium">语音播报</span>
                    <span className="inline-block px-1.5 py-0 rounded text-[10px] font-medium bg-primary/20 text-primary leading-4">
                      Beta
                    </span>
                  </div>
                  <span className="text-xs text-muted-foreground mt-1">
                    {ttsCapability.enabled
                      ? "AI 角色发言支持以语音形式播报"
                      : ttsCapability.reason}
                  </span>
                </div>
              </div>
              <button
                onClick={() => setTtsEnabled(!ttsEnabled)}
                disabled={!ttsCapability.enabled}
                className={`w-11 h-6 rounded-full transition-colors relative ${
                  ttsEnabled ? "bg-primary" : "bg-secondary"
                } disabled:opacity-50 disabled:cursor-not-allowed`}
              >
                <div
                  className={`w-5 h-5 rounded-full bg-white shadow absolute top-0.5 transition-transform ${
                    ttsEnabled ? "translate-x-5" : "translate-x-0.5"
                  }`}
                />
              </button>
            </div>
          </>
        )}

        <button
          onClick={onClose}
          className="w-full mt-5 px-4 py-2.5 rounded-lg bg-secondary hover:bg-secondary/80
                   text-sm font-medium transition-colors"
        >
          关闭
        </button>
      </motion.div>
    </motion.div>
  );
}
