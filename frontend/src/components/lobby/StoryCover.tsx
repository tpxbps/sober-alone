import { useEffect, useRef, useState } from "react";
import type { ImageVariant } from '@/types/game';

export function StoryCover({ src, variants = [], sizes = '(max-width: 639px) 92vw, (max-width: 1199px) 30vw, 340px', alt = "", className, loading }: { src?: string; variants?: ImageVariant[]; sizes?: string; alt?: string; className?: string; loading?: "lazy" | "eager" }) {
  const [failedSrc, setFailedSrc] = useState<string | undefined>();
  const [variantFailed, setVariantFailed] = useState<string | undefined>();
  const [nearby, setNearby] = useState(loading !== 'lazy');
  const image = useRef<HTMLImageElement>(null);
  useEffect(() => {
    if (nearby || !image.current) return;
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { setNearby(true); observer.disconnect(); }
    }, { rootMargin: '180px' });
    observer.observe(image.current);
    return () => observer.disconnect();
  }, [nearby]);
  const source = src && src !== failedSrc ? src : "/lobby/theatre.webp";
  const responsive = source === src && variantFailed !== src && variants.length > 0;
  return <img ref={image} src={nearby ? responsive ? variants[0].url : source : undefined}
    srcSet={nearby && responsive ? variants.map(v => `${v.url} ${v.width}w`).join(', ') : undefined}
    sizes={responsive ? sizes : undefined} alt={alt} className={className}
    loading={nearby ? 'eager' : 'lazy'} data-fallback={source !== src || undefined} draggable={false} decoding="async"
    onError={responsive ? () => setVariantFailed(src) : source === src ? () => setFailedSrc(src) : undefined} />;
}
