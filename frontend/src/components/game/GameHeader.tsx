import { useState } from 'react';
import { motion } from 'framer-motion';
import { Settings, LogOut, BookOpen } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogClose } from '@/components/ui/dialog';
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
      <div className="container mx-auto px-3 lg:px-4 py-2 lg:py-3">
        <div className="flex items-center justify-between gap-2">
          {/* Left: Logo & Script */}
          <div className="flex items-center gap-2 lg:gap-4 shrink-0">
            <div className="flex items-center gap-1.5 lg:gap-2">
              <BookIcon size={36} />
              <span className="font-serif hidden sm:inline">独醒</span>
            </div>

            <button
              onClick={onOpenScript}
              className="flex items-center gap-1.5 lg:gap-2 px-2 lg:px-3 py-1 lg:py-1.5 rounded-lg
                       bg-secondary/30 hover:bg-secondary/50 transition-colors"
            >
              <BookOpen className="w-3.5 h-3.5 lg:w-4 lg:h-4" />
              <span className="font-serif text-xs lg:text-sm truncate max-w-[80px] lg:max-w-[150px]">{scriptTitle}</span>
            </button>
          </div>

          {/* Center: Stage Indicator */}
          <motion.div
            key={stage}
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex items-center gap-1.5 lg:gap-3 px-2.5 lg:px-4 py-1 lg:py-2 rounded-full glass"
          >
            <div className={`w-1.5 h-1.5 lg:w-2 lg:h-2 rounded-full animate-pulse ${stage === 'loading' ? 'bg-muted-foreground' : 'bg-primary'}`} />
            <span className={`text-xs lg:text-sm font-medium ${STAGE_COLORS[stage]}`}>
              {STAGE_NAMES[stage]}
            </span>
            {currentRound > 0 && (
              <span className="text-[10px] lg:text-xs text-muted-foreground">
                第{currentRound}轮
              </span>
            )}
          </motion.div>

          {/* Right: Actions */}
          <div className="flex items-center gap-1 lg:gap-2 shrink-0">
            <button
              onClick={onSettings}
              className="p-1.5 lg:p-2 rounded-lg hover:bg-secondary/50 transition-colors"
              title="设置"
            >
              <Settings className="w-4 h-4 lg:w-5 lg:h-5" />
            </button>
            <button
              onClick={() => setShowExitConfirm(true)}
              className="p-1.5 lg:p-2 rounded-lg hover:bg-danger/20 text-danger transition-colors"
              title="退出游戏"
            >
              <LogOut className="w-4 h-4 lg:w-5 lg:h-5" />
            </button>
          </div>
        </div>
      </div>

      {/* Exit Confirmation Dialog */}
      <Dialog open={showExitConfirm} onOpenChange={setShowExitConfirm}>
        <DialogContent className="sm:max-w-sm">
          <DialogTitle>确认退出</DialogTitle>
          <DialogDescription>确定要退出当前游戏吗？游戏进度不会保存。</DialogDescription>
          <div className="flex gap-3">
            <DialogClose asChild>
              <button className="flex-1 py-2.5 rounded-lg bg-secondary text-secondary-foreground hover:bg-secondary/80">继续游戏</button>
            </DialogClose>
            <button onClick={() => { setShowExitConfirm(false); onExit(); }}
              className="flex-1 py-2.5 rounded-lg bg-destructive text-destructive-foreground font-medium hover:bg-destructive/90">确认退出</button>
          </div>
        </DialogContent>
      </Dialog>
    </header>
  );
}
