import { useState } from "react";

export function StoryCover({ src, alt = "", className, loading }: { src?: string; alt?: string; className?: string; loading?: "lazy" | "eager" }) {
  const [failedSrc, setFailedSrc] = useState<string | undefined>();
  const source = src && src !== failedSrc ? src : "/lobby/theatre.webp";
  return <img src={source} alt={alt} className={className} loading={loading} data-fallback={source !== src || undefined} draggable={false} decoding="async" onError={source === src ? () => setFailedSrc(src) : undefined} />;
}
