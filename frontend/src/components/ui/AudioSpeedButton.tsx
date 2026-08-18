import { useState, useCallback } from 'react';
import { audioPlayerManager } from '@/lib/audioPlayerManager';

const SPEED_OPTIONS = [1, 1.5, 2];

interface AudioSpeedButtonProps {
  className?: string;
}

export function AudioSpeedButton({ className }: AudioSpeedButtonProps) {
  const [speed, setSpeed] = useState(() => audioPlayerManager.getPlaybackRate());

  const cycle = useCallback(() => {
    const current = audioPlayerManager.getPlaybackRate();
    const idx = SPEED_OPTIONS.indexOf(current as number);
    const next = SPEED_OPTIONS[(idx + 1) % SPEED_OPTIONS.length];
    audioPlayerManager.setPlaybackRate(next);
    setSpeed(next);
  }, []);

  return (
    <button
      onClick={cycle}
      className={`px-1.5 py-0.5 rounded text-[10px] font-medium tabular-nums
                  bg-secondary/60 hover:bg-secondary text-muted-foreground
                  hover:text-foreground transition-colors shrink-0 ${className || ''}`}
      title="播放倍速"
    >
      {speed}x
    </button>
  );
}
