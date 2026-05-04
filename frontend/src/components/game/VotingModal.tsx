import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import { X, CheckCircle, AlertTriangle } from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";
import type { Character, VoteResults, VoteInfo } from "@/types/game";

interface VotingModalProps {
  open: boolean;
  characters: Character[];
  humanCharacterId: string | null;
  existingVotes: Record<string, VoteInfo>;
  voteResults: VoteResults | null;
  onVote: (
    suspectId: string,
    suspectName: string,
    reasoning?: string
  ) => Promise<void>;
  onFinalize: () => Promise<void>;
  onClose: () => void;
}

export function VotingModal({
  open,
  characters,
  humanCharacterId,
  existingVotes,
  voteResults,
  onVote,
  onFinalize,
  onClose,
}: VotingModalProps) {
  const [selectedSuspect, setSelectedSuspect] = useState<string | null>(null);
  const [reasoning, setReasoning] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isFinalizing, setIsFinalizing] = useState(false);

  // Check if human has already voted
  const humanVote = humanCharacterId ? existingVotes[humanCharacterId] : null;
  const hasAlreadyVoted = !!humanVote;

  // Get character by ID
  const getCharacter = (id: string) =>
    characters.find((c) => c.character_id === id);

  // Handle vote submission
  const handleSubmit = async () => {
    if (!selectedSuspect || isSubmitting || hasAlreadyVoted) return;

    const selectedChar = getCharacter(selectedSuspect);
    if (!selectedChar) return;

    setIsSubmitting(true);
    try {
      await onVote(
        selectedSuspect,
        selectedChar.name,
        reasoning.trim() || undefined
      );
    } catch (error: unknown) {
      // 重复投票（刷新后状态丢失但后端已记录）→ 关闭模态框
      const msg = error instanceof Error ? error.message : String(error);
      if (msg.includes("已经投过票") || msg.includes("already voted")) {
        onClose();
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  // Auto-finalize after human votes (collect AI votes)
  useEffect(() => {
    if (hasAlreadyVoted && !voteResults && !isFinalizing) {
      setIsFinalizing(true);
      onFinalize().finally(() => setIsFinalizing(false));
    }
  }, [hasAlreadyVoted, voteResults, isFinalizing, onFinalize]);

  // Reset state when modal opens
  const handleOpenChange = (o: boolean) => {
    if (!o) {
      setSelectedSuspect(null);
      setReasoning("");
    }
    if (!o) onClose();
  };

  // Show results if voting is complete
  const showResults = !!voteResults;

  return (
    <Dialog.Root open={open} onOpenChange={handleOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay asChild>
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50"
          />
        </Dialog.Overlay>

        <Dialog.Content asChild>
          <motion.div
            initial={{ opacity: 0, scale: 0.9, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: 20 }}
            transition={{ type: "spring", damping: 25, stiffness: 300 }}
            className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2
                       w-full max-w-lg max-h-[90vh] overflow-auto
                       rounded-2xl glass-dark border border-border shadow-2xl z-50"
          >
            {/* Header */}
            <div className="flex items-center justify-between p-6 border-b border-border/50">
              <Dialog.Title className="text-xl font-bold text-glow">
                {showResults ? "投票结果" : "请投票指认真凶"}
              </Dialog.Title>
              <Dialog.Close asChild>
                <button className="p-2 rounded-lg hover:bg-secondary/50 transition-colors">
                  <X className="w-5 h-5" />
                </button>
              </Dialog.Close>
            </div>

            {/* Content */}
            <div className="p-6 space-y-6">
              {showResults ? (
                /* Show Results */
                <div className="space-y-4">
                  {/* Vote count */}
                  <div className="space-y-2">
                    {Object.entries(voteResults.vote_count ?? {})
                      .filter(([charId]) => charId !== "null" && charId !== "")
                      .sort(([, a], [, b]) => b - a)
                      .map(([charId, count]) => {
                        const char = getCharacter(charId);
                        const isFinal = charId === voteResults.final_suspect;
                        return (
                          <div
                            key={charId}
                            className={`flex items-center justify-between p-3 rounded-lg
                              ${
                                isFinal
                                  ? "bg-primary/20 border border-primary/50"
                                  : "bg-secondary/20"
                              }`}
                          >
                            <div className="flex items-center gap-3">
                              <div
                                className="w-8 h-8 rounded-full bg-gradient-to-br from-primary/30 to-accent/30
                                            flex items-center justify-center text-sm font-bold"
                              >
                                {char?.name?.[0] || "?"}
                              </div>
                              <span
                                className={
                                  isFinal ? "font-medium text-primary" : ""
                                }
                              >
                                {char?.name || charId}
                              </span>
                              {isFinal && (
                                <span className="text-xs text-primary">
                                  最终指认
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-2">
                              <span
                                className={`font-bold ${
                                  isFinal ? "text-primary" : ""
                                }`}
                              >
                                {count} 票
                              </span>
                            </div>
                          </div>
                        );
                      })}
                  </div>

                  {/* Review message */}
                  {voteResults.final_suspect && (
                    <div className="p-4 rounded-lg bg-accent/10 border border-accent/30">
                      <p className="text-sm text-center">
                        最终，「{getCharacter(voteResults.final_suspect)?.name}
                        」 以 {voteResults.final_suspect_votes}{" "}
                        票成为最大嫌疑人。
                      </p>
                    </div>
                  )}

                  {/* Abstention info */}
                  {voteResults.details &&
                    Object.values(voteResults.details).some(
                      (d) => d.suspect_id === null || d.suspect_id === undefined
                    ) && (
                      <div className="p-3 rounded-lg bg-warning/10 border border-warning/30">
                        <p className="text-xs text-muted-foreground text-center">
                          {Object.entries(voteResults.details ?? {})
                            .filter(
                              ([, d]) =>
                                d.suspect_id === null ||
                                d.suspect_id === undefined
                            )
                            .map(([charId]) => getCharacter(charId)?.name)
                            .filter(Boolean)
                            .join("、")}{" "}
                          弃票
                        </p>
                      </div>
                    )}
                </div>
              ) : hasAlreadyVoted ? (
                /* Already voted - collecting AI votes (simple loading) */
                <div className="text-center py-8 space-y-4">
                  <CheckCircle className="w-10 h-10 text-success mx-auto" />
                  <h3 className="text-base font-medium">你已完成投票</h3>
                  <p className="text-sm text-muted-foreground">
                    投票给了「{getCharacter(humanVote.suspect_id)?.name}」
                    {humanVote.reasoning && `，理由：${humanVote.reasoning}`}
                  </p>
                  {isFinalizing && (
                    <div className="flex items-center justify-center gap-3 pt-2">
                      <div className="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
                      <span className="text-sm text-muted-foreground">
                        正在收集其他玩家投票...
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                /* Voting Form */
                <>
                  <p className="text-muted-foreground text-sm">
                    请选择你认为是凶手的角色，并填写投票理由（可选）。
                  </p>

                  {/* Character Selection */}
                  <div className="space-y-2">
                    {characters
                      .filter((c) => c.character_id !== humanCharacterId)
                      .map((char) => (
                        <motion.button
                          key={char.character_id}
                          whileHover={{ scale: 1.01 }}
                          whileTap={{ scale: 0.99 }}
                          onClick={() => setSelectedSuspect(char.character_id)}
                          className={`w-full flex items-center gap-4 p-4 rounded-xl transition-all
                            ${
                              selectedSuspect === char.character_id
                                ? "bg-primary/20 border-2 border-primary glow"
                                : "bg-secondary/20 border-2 border-transparent hover:border-border"
                            }`}
                        >
                          {/* Avatar */}
                          <div
                            className="w-12 h-12 rounded-full overflow-hidden shrink-0
                                        bg-gradient-to-br from-primary/30 to-accent/30
                                        flex items-center justify-center text-lg font-bold"
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
                          </div>

                          {/* Info */}
                          <div className="flex-1 text-left">
                            <div className="font-medium">{char.name}</div>
                            <div className="text-xs text-muted-foreground">
                              {char.occupation}
                            </div>
                          </div>

                          {/* Selection indicator */}
                          {selectedSuspect === char.character_id && (
                            <CheckCircle className="w-6 h-6 text-primary" />
                          )}
                        </motion.button>
                      ))}
                  </div>

                  {/* Reasoning Input */}
                  <div className="space-y-2">
                    <label className="text-sm font-medium">
                      投票理由{" "}
                      <span className="text-muted-foreground">(可选)</span>
                    </label>
                    <div className="relative">
                      <textarea
                        value={reasoning}
                        onChange={(e) => setReasoning(e.target.value)}
                        placeholder="请说明你投票给该角色的理由..."
                        rows={3}
                        maxLength={1000}
                        className="w-full pl-4 pr-14 py-3 rounded-xl bg-secondary/30 border border-border/50
                                 focus:outline-none focus:ring-2 focus:ring-primary/50
                                 resize-none"
                      />
                      <span className={`absolute top-1.5 right-3 text-[10px] leading-none pointer-events-none select-none ${reasoning.length > 800 ? 'text-destructive' : 'text-muted-foreground/40'}`}>
                        {reasoning.length}/1000
                      </span>
                    </div>
                  </div>

                  {/* Warning */}
                  <div className="flex items-start gap-3 p-4 rounded-lg bg-warning/10 border border-warning/30">
                    <AlertTriangle className="w-5 h-5 text-warning shrink-0 mt-0.5" />
                    <p className="text-sm text-muted-foreground">
                      投票后不可更改，请谨慎选择。
                    </p>
                  </div>
                </>
              )}
            </div>

            {/* Footer */}
            {!showResults && !hasAlreadyVoted && (
              <div className="p-6 border-t border-border/50">
                <button
                  onClick={handleSubmit}
                  disabled={!selectedSuspect || isSubmitting}
                  className="w-full py-4 rounded-xl bg-primary text-primary-foreground font-medium
                           hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed
                           transition-all flex items-center justify-center gap-2 glow"
                >
                  {isSubmitting ? (
                    <>
                      <div className="w-5 h-5 border-2 border-primary-foreground border-t-transparent rounded-full animate-spin" />
                      提交中...
                    </>
                  ) : (
                    "确认投票"
                  )}
                </button>
              </div>
            )}
          </motion.div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
