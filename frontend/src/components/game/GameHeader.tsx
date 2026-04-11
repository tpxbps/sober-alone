import { useState } from 'react';
import { motion } from 'framer-motion';
import { Settings, LogOut, BookOpen, X } from 'lucide-react';
import * as Dialog from '@radix-ui/react-dialog';
import { STAGE_NAMES, type GameStage } from '@/types/game';
import { BookIcon } from '@/components/ui/BookIcon';

interface GameHeaderProps {
  stage: GameStage;
  currentRound: number;
  scriptTitle: string;
  onOpenScript: () => void;
  onSettings: () => void;
  onExit: () => void;
}

// Stage color mapping
const STAGE_COLORS: Record<GameStage, string> = {
  loading: 'text-muted-foreground',
  intro: 'text-accent',
  clue_analysis: 'text-warning',
  free_discussion: 'text-primary',
  vote: 'text-danger',
  summary: 'text-success',
  review: 'text-info',
  completed: 'text-success',
};

export function GameHeader({
  stage,
  currentRound,
  scriptTitle,
  onOpenScript,
  onSettings,
  onExit,
}: GameHeaderProps) {
  const [showExitConfirm, setShowExitConfirm] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-border/50 bg-background/80 backdrop-blur-xl">
      <div className="container mx-auto px-4 py-3">
        <div className="flex items-center justify-between">
          {/* Left: Logo & Script */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <BookIcon size={44} />
              <span className="font-bold text-glow hidden sm:inline">独醒</span>
            </div>

            <button
              onClick={onOpenScript}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg
                       bg-secondary/30 hover:bg-secondary/50 transition-colors"
            >
              <BookOpen className="w-4 h-4" />
              <span className="text-sm truncate max-w-[150px]">{scriptTitle}</span>
            </button>
          </div>

          {/* Center: Stage Indicator */}
          <motion.div
            key={stage}
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-3 px-4 py-2 rounded-full glass"
          >
            <div className={`w-2 h-2 rounded-full animate-pulse ${stage === 'loading' ? 'bg-muted-foreground' : 'bg-primary'}`} />
            <span className={`font-medium ${STAGE_COLORS[stage]}`}>
              {STAGE_NAMES[stage]}
            </span>
            {currentRound > 0 && (
              <span className="text-xs text-muted-foreground">
                第 {currentRound} 轮
              </span>
            )}
          </motion.div>

          {/* Right: Actions */}
          <div className="flex items-center gap-2">
            <button
              onClick={onSettings}
              className="p-2 rounded-lg hover:bg-secondary/50 transition-colors"
              title="设置"
            >
              <Settings className="w-5 h-5" />
            </button>
            <button
              onClick={() => setShowExitConfirm(true)}
              className="p-2 rounded-lg hover:bg-danger/20 text-danger transition-colors"
              title="退出游戏"
            >
              <LogOut className="w-5 h-5" />
            </button>
          </div>
        </div>
      </div>

      {/* Exit Confirmation Dialog */}
      <Dialog.Root open={showExitConfirm} onOpenChange={setShowExitConfirm}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50" />
          <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2
                                     w-full max-w-sm rounded-2xl glass-dark border border-border
                                     shadow-2xl z-50 p-6">
            <div className="flex items-center justify-between mb-4">
              <Dialog.Title className="text-lg font-bold">确认退出</Dialog.Title>
              <Dialog.Close asChild>
                <button className="p-2 rounded-lg hover:bg-secondary/50 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </Dialog.Close>
            </div>
            <p className="text-sm text-muted-foreground mb-6">
              确定要退出当前游戏吗？游戏进度不会保存。
            </p>
            <div className="flex gap-3">
              <Dialog.Close asChild>
                <button
                  className="flex-1 py-2.5 rounded-xl bg-secondary/50 border border-border/50 font-medium
                           hover:bg-secondary/70 transition-colors"
                >
                  继续游戏
                </button>
              </Dialog.Close>
              <button
                onClick={() => {
                  setShowExitConfirm(false);
                  onExit();
                }}
                className="flex-1 py-2.5 rounded-xl bg-danger text-danger-foreground font-medium
                         hover:bg-danger/90 transition-colors"
              >
                确认退出
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </header>
  );
}
