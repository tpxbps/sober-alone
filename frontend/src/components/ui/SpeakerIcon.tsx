import { Volume2, VolumeX, Loader2 } from 'lucide-react';

export type SpeakerState = 'disabled' | 'off' | 'loading' | 'playing' | 'error';

interface SpeakerIconProps {
  state: SpeakerState;
  onClick: () => void;
  size?: number;
  className?: string;
}

export function SpeakerIcon({
  state,
  onClick,
  size = 14,
  className = '',
}: SpeakerIconProps) {
  const baseClasses =
    'inline-flex items-center justify-center rounded-full transition-all duration-200 cursor-pointer select-none';

  if (state === 'disabled') {
    return (
      <span
        className={`${baseClasses} opacity-30 cursor-not-allowed ${className}`}
        style={{ width: size + 8, height: size + 8 }}
        title="TTS 未启用"
      >
        <VolumeX style={{ width: size, height: size }} className="text-muted-foreground" />
      </span>
    );
  }

  if (state === 'error') {
    return (
      <span
        className={`${baseClasses} opacity-40 cursor-not-allowed ${className}`}
        style={{ width: size + 8, height: size + 8 }}
        title="TTS 不可用"
      >
        <VolumeX style={{ width: size, height: size }} className="text-muted-foreground" />
      </span>
    );
  }

  if (state === 'loading') {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        className={`${baseClasses} ${className}`}
        style={{ width: size + 8, height: size + 8 }}
        title="取消加载"
        aria-label="取消加载语音"
      >
        <Loader2
          style={{ width: size, height: size }}
          className="animate-spin text-primary"
        />
      </button>
    );
  }

  if (state === 'playing') {
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          onClick();
        }}
        className={`${baseClasses} speaker-playing ${className}`}
        style={{ width: size + 8, height: size + 8 }}
        title="停止播放"
        aria-label="停止播放语音"
      >
        <Volume2 style={{ width: size, height: size }} className="text-primary" />
      </button>
    );
  }

  // state === 'off'
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onClick();
      }}
      className={`${baseClasses} hover:bg-primary/10 ${className}`}
      style={{ width: size + 8, height: size + 8 }}
      title="播放语音"
      aria-label="播放语音"
    >
      <Volume2
        style={{ width: size, height: size }}
        className="text-muted-foreground hover:text-primary"
      />
    </button>
  );
}
