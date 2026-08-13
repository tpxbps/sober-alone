import { motion, AnimatePresence } from 'framer-motion';
import { useEffect } from 'react';
import { STAGE_NAMES, type GameStage } from '@/types/game';

interface StageTransitionOverlayProps {
  show: boolean;
  fromStage: GameStage | null;
  toStage: GameStage;
  message?: string;
  onComplete: () => void;
  autoDismissMs?: number; // 自动关闭时间，默认2秒
}

// Stage icons
const STAGE_ICONS: Record<GameStage, string> = {
  loading: '⏳',
  intro: '📖',
  clue_analysis: '🔍',
  free_discussion: '💬',
  vote: '🗳️',
  summary: '📜',
  review: '🔎',
  completed: '🎉',
};

// 阶段名称映射（确保有默认值）
const getStageName = (stage: GameStage): string => {
  return STAGE_NAMES[stage] || stage;
};

export function StageTransitionOverlay({
  show,
  fromStage,
  toStage,
  message,
  onComplete,
  autoDismissMs = 2000,
}: StageTransitionOverlayProps) {
  // 自动关闭
  useEffect(() => {
    if (show) {
      const timer = setTimeout(() => {
        onComplete();
      }, autoDismissMs);
      return () => clearTimeout(timer);
    }
  }, [show, autoDismissMs, onComplete]);

  // 点击关闭
  const handleClick = () => {
    onComplete();
  };

  // 动画完成后调用 onComplete
  const handleExitComplete = () => {
    onComplete();
  };

  return (
    <AnimatePresence onExitComplete={handleExitComplete}>
      {show && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.3 }}
          onClick={handleClick}
          className="fixed inset-0 z-50 flex items-center justify-center
                     bg-background/90 backdrop-blur-md cursor-pointer"
        >
          <motion.div
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: 1, opacity: 1 }}
            exit={{ scale: 0.8, opacity: 0 }}
            transition={{ type: 'spring', damping: 20, stiffness: 300 }}
            className="text-center"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Icon */}
            <motion.div
              initial={{ scale: 0, rotate: -180 }}
              animate={{ scale: 1, rotate: 0 }}
              transition={{ delay: 0.2, type: 'spring', damping: 15 }}
              className="text-6xl mb-6"
            >
              {STAGE_ICONS[toStage] || '🎮'}
            </motion.div>

            {/* Stage Name */}
            <motion.div
              initial={{ y: 20, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ delay: 0.3 }}
              className="mb-4"
            >
              <h2 className="text-3xl font-bold text-glow mb-2">
                {getStageName(toStage)}
              </h2>
              {fromStage && (
                <p className="text-muted-foreground text-sm">
                  {getStageName(fromStage)} → {getStageName(toStage)}
                </p>
              )}
            </motion.div>

            {/* Message - 使用阶段名称替换字段名 */}
            {message && (
              <motion.p
                initial={{ y: 20, opacity: 0 }}
                animate={{ y: 0, opacity: 1 }}
                transition={{ delay: 0.4 }}
                className="text-lg text-muted-foreground max-w-md mx-auto"
              >
                {formatMessage(message)}
              </motion.p>
            )}

            {/* 点击继续提示 */}
            <motion.p
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.6 }}
              className="text-xs text-muted-foreground/60 mt-6"
            >
              点击任意处继续...
            </motion.p>

            {/* Decorative elements */}
            <motion.div
              initial={{ scale: 0, opacity: 0 }}
              animate={{ scale: 1, opacity: 0.3 }}
              transition={{ delay: 0.1 }}
              className="absolute inset-0 pointer-events-none"
            >
              <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2
                            w-[600px] h-[600px] rounded-full
                            bg-gradient-radial from-primary/20 to-transparent" />
            </motion.div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// 格式化消息，将字段名替换为中文名称
function formatMessage(message: string): string {
  const stageMapping: Record<string, string> = {
    'intro': '自我介绍',
    'clue_analysis': '搜证阶段',
    'free_discussion': '自由讨论',
    'vote': '投票阶段',
    'summary': '总结发言',
    'review': '复盘阶段',
    'completed': '游戏结束',
    'loading': '加载中',
  };

  let formatted = message;
  for (const [key, value] of Object.entries(stageMapping)) {
    formatted = formatted.replace(new RegExp(key, 'g'), value);
  }
  return formatted;
}
