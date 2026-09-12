/**
 * BookIcon — 展示透明龙形标志，带龙灵动效
 */
interface BookIconProps {
  size?: number;
  className?: string;
}

export function BookIcon({ size = 48, className = '' }: BookIconProps) {
  return (
    <img
      src="/lobby/dragon.png"
      alt="独醒"
      className={`icon-dragon ${className}`}
      style={{ width: size, height: size, objectFit: 'contain' }}
      draggable={false}
    />
  );
}
