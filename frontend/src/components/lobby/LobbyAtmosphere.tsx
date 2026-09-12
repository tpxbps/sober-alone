import { useEffect, useRef } from "react";

export function LobbyAtmosphere({ quiet, paused }: { quiet: boolean; paused: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const pausedRef = useRef(paused);
  useEffect(() => { pausedRef.current = paused; }, [paused]);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const root = element.closest<HTMLElement>(".dream-lobby")!;
    root.dataset.renderer = "still";
    if (quiet || matchMedia("(pointer: coarse)").matches) return;
    let cancelled = false;
    let dispose: (() => void) | undefined;
    void import("./fluidAtmosphere").then(({ createAtmosphere }) => {
      if (cancelled) return;
      try { dispose = createAtmosphere(element, root, () => pausedRef.current); }
      catch (error) { root.dataset.renderer = "fallback"; console.warn("流光不可用，使用静态背景", error); }
    }).catch(() => { root.dataset.renderer = "fallback"; });
    return () => { cancelled = true; dispose?.(); root.dataset.renderer = "still"; };
  }, [quiet]);
  return <canvas ref={canvas} className="lobby-atmosphere" aria-hidden="true" />;
}
