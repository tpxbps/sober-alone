import { useState, type ReactNode } from 'react';
import type { ClueMedia } from '@/types/cluePresentation';

export function ClueImage({ media, thumbnail, className, fallback = null }: {
  media?: ClueMedia; thumbnail?: boolean; className?: string; fallback?: ReactNode;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const source = media && (thumbnail ? media.thumbnail_url : media.image_url);
  if (!media || media.status !== 'ready' || !source?.startsWith('/images/') || failed === source) return <>{fallback}</>;
  return <img src={source} alt={thumbnail ? '' : media.alt} loading="lazy" decoding="async"
    onError={() => setFailed(source)} className={className}
    style={{ objectPosition: `${(media.focus?.[0] ?? 0.5) * 100}% ${(media.focus?.[1] ?? 0.5) * 100}%` }} />;
}
