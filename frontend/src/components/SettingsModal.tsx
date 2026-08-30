import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import {
  ChevronDown,
  ClipboardCopy,
  KeyRound,
  LoaderCircle,
  Mic,
  MicOff,
} from "lucide-react";
import { useSettingsStore } from "@/stores/settingsStore";
import { systemApi } from "@/lib/api";
import { editorApi } from "@/lib/editorApi";
import { ttsCapability as resolveTtsCapability } from "@/lib/capabilityAdapter";
import {
  clearLegacyOwnerUuids,
  getLegacyOwnerUuids,
  parseLegacyOwnerUuids,
  storeLegacyOwnerUuids,
} from "@/lib/authorKey";

type SettingsMode = "full" | "game" | "editor";

interface SettingsModalProps {
  onClose: () => void;
  /** Controls which sections are visible:
   *  'full' and 'game' show optional TTS settings.
   *  'editor' hides game-only audio settings.
   */
  mode?: SettingsMode;
  onOwnershipClaimed?: () => void | Promise<void>;
}

export function SettingsModal({
  onClose,
  mode = "full",
  onOwnershipClaimed,
}: SettingsModalProps) {
  const { ttsEnabled, setTtsEnabled } = useSettingsStore();
  const [ttsCapability, setTtsCapability] = useState({
    enabled: false,
    reason: "正在检查语音能力…",
  });
  const [detectedLegacyCount, setDetectedLegacyCount] = useState(
    () => getLegacyOwnerUuids().length
  );
  const [showLegacyImport, setShowLegacyImport] = useState(false);
  const [legacyOwnerInput, setLegacyOwnerInput] = useState("");
  const [isClaiming, setIsClaiming] = useState(false);
  const [claimMessage, setClaimMessage] = useState("");
  const [claimError, setClaimError] = useState("");

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

  const recoverLegacyScripts = async (includeImportedValue = false) => {
    const legacyOwnerIds = [
      ...new Set([
        ...getLegacyOwnerUuids(),
        ...(includeImportedValue ? parseLegacyOwnerUuids(legacyOwnerInput) : []),
      ]),
    ];
    if (legacyOwnerIds.length === 0) {
      setClaimMessage("");
      setClaimError("没有识别到可用的迁移信息，请重新复制后再试。");
      return;
    }

    setIsClaiming(true);
    setClaimMessage("");
    setClaimError("");
    storeLegacyOwnerUuids(legacyOwnerIds);
    try {
      const result = await editorApi.claimLegacyOwnership(legacyOwnerIds);
      if (result.matched_count === 0) {
        setClaimError("没有找到可恢复的旧剧本，请确认迁移信息来自当前网站。");
        return;
      }
      clearLegacyOwnerUuids();
      setDetectedLegacyCount(0);
      setLegacyOwnerInput("");
      setShowLegacyImport(false);
      setClaimMessage(
        result.claimed_count > 0
          ? `已恢复 ${result.claimed_count} 个剧本，现在可以直接编辑或删除。`
          : "这些旧剧本已经恢复，无需重复操作。"
      );
      await onOwnershipClaimed?.();
    } catch {
      setClaimError("暂时无法恢复旧剧本，请稍后重试或联系网站维护者。");
    } finally {
      setIsClaiming(false);
    }
  };

  const copyLegacyMigrationInfo = async () => {
    const legacyOwnerIds = getLegacyOwnerUuids();
    if (legacyOwnerIds.length === 0) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(legacyOwnerIds));
      setClaimError("");
      setClaimMessage("迁移信息已复制，可在其他浏览器的设置中粘贴恢复。");
    } catch {
      setClaimMessage("");
      setClaimError("复制失败，请允许浏览器访问剪贴板后重试。");
    }
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

        {mode === "full" && (
          <>
            <div className="border-t border-border/50 my-4" />
            <section aria-labelledby="legacy-script-recovery-title">
              <div className="flex items-start gap-2">
                <KeyRound className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                <div>
                  <h4 id="legacy-script-recovery-title" className="text-sm font-medium">
                    恢复旧版剧本
                  </h4>
                  <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                    恢复后，你可以继续编辑或删除自己在旧版中创作的剧本。
                  </p>
                </div>
              </div>

              {detectedLegacyCount > 0 ? (
                <div className="mt-3 rounded-xl border border-primary/20 bg-primary/10 p-3">
                  <p className="text-xs leading-relaxed text-foreground">
                    检测到此浏览器保存过 {detectedLegacyCount} 份旧版创作记录。
                  </p>
                  <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                    <button
                      type="button"
                      onClick={() => void recoverLegacyScripts(false)}
                      disabled={isClaiming}
                      className="inline-flex items-center justify-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      {isClaiming && <LoaderCircle className="h-3.5 w-3.5 animate-spin" />}
                      {isClaiming ? "正在恢复…" : "一键恢复我的旧剧本"}
                    </button>
                    <button
                      type="button"
                      onClick={() => void copyLegacyMigrationInfo()}
                      disabled={isClaiming}
                      className="inline-flex items-center justify-center gap-2 rounded-lg bg-secondary px-3 py-2 text-xs font-medium transition-colors hover:bg-secondary/80 disabled:opacity-60"
                    >
                      <ClipboardCopy className="h-3.5 w-3.5" />
                      复制迁移信息
                    </button>
                  </div>
                </div>
              ) : (
                <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
                  当前浏览器没有待恢复的旧版记录。
                </p>
              )}

              <button
                type="button"
                onClick={() => setShowLegacyImport((value) => !value)}
                className="mt-3 inline-flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                aria-expanded={showLegacyImport}
              >
                <ChevronDown
                  className={`h-3.5 w-3.5 transition-transform ${
                    showLegacyImport ? "rotate-180" : ""
                  }`}
                />
                换过浏览器？从迁移信息恢复
              </button>

              {showLegacyImport && (
                <div className="mt-3 rounded-xl border border-border/70 bg-background/40 p-3">
                  <label
                    htmlFor="legacy-owner-import"
                    className="block text-xs leading-relaxed text-muted-foreground"
                  >
                    在旧浏览器中点击“复制迁移信息”，然后粘贴到这里。
                  </label>
                  <textarea
                    id="legacy-owner-import"
                    value={legacyOwnerInput}
                    onChange={(event) => setLegacyOwnerInput(event.target.value)}
                    rows={3}
                    spellCheck={false}
                    placeholder="粘贴迁移信息"
                    className="mt-2 w-full resize-y rounded-lg border border-border bg-background/60 px-3 py-2 text-xs outline-none transition-colors placeholder:text-muted-foreground/60 focus:border-primary"
                  />
                  <button
                    type="button"
                    onClick={() => void recoverLegacyScripts(true)}
                    disabled={isClaiming || legacyOwnerInput.trim().length === 0}
                    className="mt-2 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary/15 px-3 py-2 text-xs font-medium text-primary transition-colors hover:bg-primary/25 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isClaiming && <LoaderCircle className="h-3.5 w-3.5 animate-spin" />}
                    导入并恢复
                  </button>
                </div>
              )}

              {claimMessage && (
                <p role="status" className="mt-2 text-xs leading-relaxed text-emerald-400">
                  {claimMessage}
                </p>
              )}
              {claimError && (
                <p role="alert" className="mt-2 text-xs leading-relaxed text-red-400">
                  {claimError}
                </p>
              )}
            </section>
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
