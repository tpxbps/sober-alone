import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Volume2, VolumeX, Mic, MicOff, KeyRound, Plus, X } from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { getOwnerUuids, addOwnerUuid } from "@/stores/editorStore";

type SettingsMode = "full" | "game" | "editor";

interface SettingsModalProps {
  onClose: () => void;
  /** Controls which sections are visible:
   *  'full' = BGM + TTS + script management (homepage)
   *  'game' = BGM + TTS (game page — no script management)
   *  'editor' = BGM only (script editor page)
   */
  mode?: SettingsMode;
}

export function SettingsModal({ onClose, mode = "full" }: SettingsModalProps) {
  const {
    bgmEnabled,
    bgmVolume,
    ttsEnabled,
    setBgmEnabled,
    setBgmVolume,
    setTtsEnabled,
  } = useSettingsStore();

  const [newScriptId, setNewScriptId] = useState("");
  const [ownedIds, setOwnedIds] = useState<string[]>(getOwnerUuids());
  const [addedMsg, setAddedMsg] = useState("");

  const handleAddScriptId = () => {
    const id = newScriptId.trim();
    if (id) {
      addOwnerUuid(id);
      setOwnedIds(getOwnerUuids());
      setNewScriptId("");
      setAddedMsg("已添加");
      setTimeout(() => setAddedMsg(""), 2000);
    }
  };

  const handleRemoveId = (id: string) => {
    const existing = ownedIds.filter((i) => i !== id);
    localStorage.setItem("scriptOwnerIds", JSON.stringify(existing));
    setOwnedIds(existing);
  };

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

        {/* BGM Toggle */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            {bgmEnabled ? (
              <Volume2 className="w-5 h-5 text-primary" />
            ) : (
              <VolumeX className="w-5 h-5 text-muted-foreground" />
            )}
            <span className="text-sm font-medium">背景音乐</span>
          </div>
          <button
            onClick={() => setBgmEnabled(!bgmEnabled)}
            className={`w-11 h-6 rounded-full transition-colors relative ${
              bgmEnabled ? "bg-primary" : "bg-secondary"
            }`}
          >
            <div
              className={`w-5 h-5 rounded-full bg-white shadow absolute top-0.5 transition-transform ${
                bgmEnabled ? "translate-x-5" : "translate-x-0.5"
              }`}
            />
          </button>
        </div>

        {/* Volume Slider */}
        {bgmEnabled && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-4"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-muted-foreground">音量</span>
              <span className="text-xs text-muted-foreground">
                {Math.round(bgmVolume * 100)}%
              </span>
            </div>
            <input
              type="range"
              min="0"
              max="100"
              value={Math.round(bgmVolume * 100)}
              onChange={(e) => setBgmVolume(Number(e.target.value) / 100)}
              className="w-full h-1.5 rounded-full appearance-none bg-secondary cursor-pointer
                         [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4
                         [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:rounded-full
                         [&::-webkit-slider-thumb]:bg-primary [&::-webkit-slider-thumb]:shadow"
            />
          </motion.div>
        )}

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
                    AI 角色发言支持以语音形式播报
                  </span>
                </div>
              </div>
              <button
                onClick={() => setTtsEnabled(!ttsEnabled)}
                className={`w-11 h-6 rounded-full transition-colors relative ${
                  ttsEnabled ? "bg-primary" : "bg-secondary"
                }`}
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

        {/* Script ID Management — hidden in game & editor mode */}
        {mode === "full" && (
          <>
            <div className="border-t border-border/50 my-4" />
            <div>
              <div className="flex items-center gap-2 mb-3">
                <KeyRound className="w-5 h-5 text-primary" />
                <span className="text-sm font-medium">剧本管理</span>
              </div>
              <p className="text-xs text-muted-foreground mb-3">
                导入剧本操作密钥，即可管理你创作的剧本（删除操作）。
              </p>

              {/* Add ID input */}
              <div className="flex items-center gap-2 mb-3">
                <input
                  value={newScriptId}
                  onChange={(e) => setNewScriptId(e.target.value)}
                  placeholder="输入剧本操作密钥"
                  className="flex-1 px-3 py-1.5 text-xs rounded-lg border border-border/50 bg-background focus:outline-none focus:border-primary/50"
                />
                <button
                  onClick={handleAddScriptId}
                  disabled={!newScriptId.trim()}
                  className="shrink-0 p-1.5 rounded-lg bg-primary/10 text-primary hover:bg-primary/20 disabled:opacity-50 transition-colors"
                >
                  <Plus className="w-4 h-4" />
                </button>
              </div>
              {addedMsg && (
                <p className="text-xs text-green-500 mb-2">{addedMsg}</p>
              )}

              {/* Current owned IDs */}
              {ownedIds.length > 0 && (
                <div className="max-h-[200px] overflow-y-auto scrollbar-thin space-y-1.5">
                  <span className="text-xs text-muted-foreground">
                    已保存的ID：
                  </span>
                  {ownedIds.map((id) => (
                    <div
                      key={id}
                      className="flex items-center gap-2 px-2 py-1.5 bg-secondary/30 rounded text-xs"
                    >
                      <code className="flex-1 break-all text-muted-foreground">
                        {id}
                      </code>
                      <button
                        onClick={() => handleRemoveId(id)}
                        className="shrink-0 p-0.5 hover:bg-secondary rounded text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <X className="w-3 h-3" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
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
